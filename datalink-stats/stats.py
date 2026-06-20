"""datalink-stats — UAV datalink health emitter.

Polls Docker for the uav-datalink-los container every POLL_INTERVAL seconds
and projects its network + cpu counters into one NDJSON row per cycle. Feeds
UAVDatalink_CL so the SOC can spot link degradation, jamming-like packet loss
spikes and unauthorised additional traffic flowing through the router.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

import docker


CONTAINER_NAME: str = os.environ.get("TARGET_CONTAINER", "uav-datalink-los")
POLL_INTERVAL: int = int(os.environ.get("POLL_INTERVAL", "30"))
LOG_FILE_PATH: str = os.environ.get("LOG_FILE_PATH", "")


def _log(line: str) -> None:
    sys.stderr.write(f"[datalink-stats] {line}\n")
    sys.stderr.flush()


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _project_stats(name: str, stats: dict[str, Any]) -> dict[str, Any]:
    """Flatten Docker stats payload into a single NDJSON record."""
    networks = stats.get("networks", {}) or {}
    eth = networks.get("eth0", {}) if "eth0" in networks else next(iter(networks.values()), {})
    cpu = stats.get("cpu_stats", {}) or {}
    precpu = stats.get("precpu_stats", {}) or {}
    cpu_usage = cpu.get("cpu_usage", {}).get("total_usage", 0) - precpu.get("cpu_usage", {}).get("total_usage", 0)
    system_usage = cpu.get("system_cpu_usage", 0) - precpu.get("system_cpu_usage", 0)
    online_cpus = cpu.get("online_cpus") or 1
    cpu_pct = 0.0
    if system_usage > 0 and cpu_usage > 0:
        cpu_pct = (cpu_usage / system_usage) * online_cpus * 100.0

    mem = stats.get("memory_stats", {}) or {}
    return {
        "TimeGenerated": _now_iso(),
        "ContainerName": name,
        "RxBytes": eth.get("rx_bytes", 0),
        "RxPackets": eth.get("rx_packets", 0),
        "RxErrors": eth.get("rx_errors", 0),
        "RxDropped": eth.get("rx_dropped", 0),
        "TxBytes": eth.get("tx_bytes", 0),
        "TxPackets": eth.get("tx_packets", 0),
        "TxErrors": eth.get("tx_errors", 0),
        "TxDropped": eth.get("tx_dropped", 0),
        "CpuUsagePct": round(cpu_pct, 3),
        "MemoryUsageBytes": mem.get("usage", 0),
        "MemoryLimitBytes": mem.get("limit", 0),
        "InterfaceName": "eth0" if "eth0" in networks else next(iter(networks.keys()), ""),
    }


def main() -> int:
    handle = None
    if LOG_FILE_PATH:
        os.makedirs(os.path.dirname(LOG_FILE_PATH) or ".", exist_ok=True)
        handle = open(LOG_FILE_PATH, "a", encoding="utf-8")
        _log(f"file sink active: {LOG_FILE_PATH}")

    _log(f"connecting to docker daemon; polling {CONTAINER_NAME} every {POLL_INTERVAL}s")
    client = docker.from_env()

    while True:
        try:
            container = client.containers.get(CONTAINER_NAME)
            stats = container.stats(stream=False)
            record = _project_stats(CONTAINER_NAME, stats)
            line = json.dumps(record, separators=(",", ":"), default=str) + "\n"
            sys.stdout.write(line)
            sys.stdout.flush()
            if handle is not None:
                handle.write(line)
                handle.flush()
        except docker.errors.NotFound:
            _log(f"target container {CONTAINER_NAME} not found, retrying")
        except Exception as exc:  # noqa: BLE001 — best-effort sidecar
            _log(f"poll error: {exc}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    sys.exit(main() or 0)
