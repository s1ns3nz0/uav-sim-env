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

# S47(드론 anti-forensics/로그삭제)·S66(데이터 파괴) — 전용 공격 코드는 없지만,
# 이 서비스가 이미 관측 중인 Docker 데몬 이벤트만으로도 "로그를 만들어내는 자산 자체를
# 파괴/삭제"하는 행위는 실제로 잡을 수 있다(신규 producer 불필요, 기존 신호 재해석).
DESTRUCTIVE_ACTIONS: frozenset[str] = frozenset({"destroy", "delete", "kill"})
LOG_BEARING_NAME_HINTS: tuple[str, ...] = (
    "telemetry-tap", "datalink-satcom", "datalink-los", "gcs-qgc", "counter-uas",
    "sar-stub", "pgse-stub", "auth-stub", "ti-stub", "mps-stub", "c4i-stub",
    "weapon-stub", "cyber-posture-stub", "service-audit", "fluentbit",
    "log", "ndjson",
)


def _is_log_bearing(name: str) -> bool:
    """True if a container/volume name hints it holds or produces NDJSON logs.

    Heuristic name-match only (no filesystem access) — flags the destruction
    of the telemetry pipeline's own components as a distinct signal from
    ordinary container lifecycle churn.
    """
    lowered = (name or "").lower()
    return any(hint in lowered for hint in LOG_BEARING_NAME_HINTS)


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
    """Project a Docker engine event into a flat NDJSON record matching the DCR stream schema."""
    actor = event.get("Actor") or {}
    attrs = actor.get("Attributes") or {}
    action = event.get("Action") or event.get("status") or ""
    base_action = action.split(":", 1)[0]
    container_name = attrs.get("name", "")
    actor_id = actor.get("ID") or event.get("id") or ""
    target_name = container_name or actor_id
    return {
        "TimeGenerated": _now_iso(),
        "EventType": event.get("Type"),
        "Action": action,
        "ActorId": actor_id,
        "ContainerName": container_name,
        "ImageName": attrs.get("image", "") or event.get("from", ""),
        "ExitCode": str(attrs.get("exitCode", "")),
        "Signal": str(attrs.get("signal", "")),
        "ServiceLabel": attrs.get("com.docker.compose.service", ""),
        "ProjectLabel": attrs.get("com.docker.compose.project", ""),
        "Scope": event.get("scope") or "",
        # S47/S66 — 기존 신호(Action/ContainerName)만으로 파생하는 파괴행위 지표.
        "IsDestructiveAction": base_action in DESTRUCTIVE_ACTIONS,
        "LogBearingTargetSuspected": _is_log_bearing(target_name),
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
