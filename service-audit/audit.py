"""service-audit — Docker daemon event stream -> NDJSON.

Subscribes to the Docker engine event stream on /var/run/docker.sock and emits
one JSON line per container/image/network event to LOG_FILE_PATH. Downstream
Azure Monitor Agent ships these into UAVServiceAudit_CL so the SOC can detect
"av-mpd crashed mid-mission", "an unexpected image was pulled", or similar
infrastructure-side anomalies during a UAV operation.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

import docker


LOG_FILE_PATH: str = os.environ.get("LOG_FILE_PATH", "")
INTERESTING_TYPES: frozenset[str] = frozenset({"container", "image", "network", "volume"})
INTERESTING_ACTIONS: frozenset[str] = frozenset({
    "create", "start", "die", "stop", "kill", "restart", "destroy",
    "oom", "health_status",
    "pull", "push", "delete",
    "exec_create", "exec_start",
    "connect", "disconnect",
})


def _log(line: str) -> None:
    sys.stderr.write(f"[service-audit] {line}\n")
    sys.stderr.flush()


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _record_from_event(event: dict[str, Any]) -> dict[str, Any]:
    """Project a Docker engine event into a flat NDJSON-friendly record."""
    actor = event.get("Actor") or {}
    attrs = actor.get("Attributes") or {}
    return {
        "TimeGenerated": _now_iso(),
        "EventType": event.get("Type"),
        "Action": event.get("Action") or event.get("status"),
        "ActorId": actor.get("ID") or event.get("id"),
        "ContainerName": attrs.get("name", ""),
        "ImageName": attrs.get("image", "") or event.get("from", ""),
        "ExitCode": attrs.get("exitCode", ""),
        "Signal": attrs.get("signal", ""),
        "ServiceLabel": attrs.get("com.docker.compose.service", ""),
        "ProjectLabel": attrs.get("com.docker.compose.project", ""),
        "Scope": event.get("scope"),
        "Raw": event,
    }


def main() -> int:
    handle = None
    if LOG_FILE_PATH:
        os.makedirs(os.path.dirname(LOG_FILE_PATH) or ".", exist_ok=True)
        handle = open(LOG_FILE_PATH, "a", encoding="utf-8")
        _log(f"file sink active: {LOG_FILE_PATH}")

    _log("connecting to docker daemon")
    client = docker.from_env()
    _log("ready, streaming events")

    try:
        for event in client.events(decode=True):
            event_type = event.get("Type")
            action = event.get("Action") or event.get("status") or ""
            if event_type not in INTERESTING_TYPES:
                continue
            base_action = action.split(":", 1)[0]
            if base_action not in INTERESTING_ACTIONS:
                continue
            record = _record_from_event(event)
            line = json.dumps(record, separators=(",", ":"), default=str) + "\n"
            sys.stdout.write(line)
            sys.stdout.flush()
            if handle is not None:
                handle.write(line)
                handle.flush()
    except KeyboardInterrupt:
        _log("interrupted, exiting")
        return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
