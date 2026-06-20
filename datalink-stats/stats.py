"""datalink-stats — UAV datalink + service resource emitter.

Three sinks per poll cycle:

1. UAVDatalink_CL  — network counters for the datalink container (RX/TX bytes,
                     packets, errors, dropped + CPU/mem).
2. UAVResourceMetrics_CL — same network/CPU/mem for every container in the
                            compose project (project="uav-sim-env").
3. UAVDatalinkConn_CL — snapshot of established TCP connections on the
                        mavlink-router data channels (5760, 5790, 14550).

Each sink writes to its own NDJSON file so the DCR can route them to the
matching tables.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Iterable

import docker


CONTAINER_NAME: str = os.environ.get("TARGET_CONTAINER", "uav-datalink-los")
POLL_INTERVAL: int = int(os.environ.get("POLL_INTERVAL", "30"))
LOG_FILE_PATH: str = os.environ.get("LOG_FILE_PATH", "")
RESOURCE_FILE_PATH: str = os.environ.get("RESOURCE_FILE_PATH", "")
CONN_FILE_PATH: str = os.environ.get("CONN_FILE_PATH", "")
PROJECT_LABEL_FILTER: str = os.environ.get("PROJECT_LABEL", "uav-sim-env")
CONN_PORTS: tuple[str, ...] = tuple(
    p.strip() for p in os.environ.get("CONN_PORTS", "5760,5790,14550").split(",") if p.strip()
)


def _log(line: str) -> None:
    sys.stderr.write(f"[datalink-stats] {line}\n")
    sys.stderr.flush()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _open(path: str):
    if not path:
        return None
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    return open(path, "a", encoding="utf-8")


def _cpu_pct(stats: dict[str, Any]) -> float:
    cpu = stats.get("cpu_stats", {}) or {}
    precpu = stats.get("precpu_stats", {}) or {}
    cpu_delta = cpu.get("cpu_usage", {}).get("total_usage", 0) - precpu.get("cpu_usage", {}).get("total_usage", 0)
    system_delta = cpu.get("system_cpu_usage", 0) - precpu.get("system_cpu_usage", 0)
    online = cpu.get("online_cpus") or 1
    if system_delta > 0 and cpu_delta > 0:
        return round((cpu_delta / system_delta) * online * 100.0, 3)
    return 0.0


def _project_network(name: str, stats: dict[str, Any]) -> dict[str, Any]:
    networks = stats.get("networks", {}) or {}
    eth_name = "eth0" if "eth0" in networks else next(iter(networks.keys()), "")
    eth = networks.get(eth_name, {})
    mem = stats.get("memory_stats", {}) or {}
    return {
        "TimeGenerated": _now_iso(),
        "ContainerName": name,
        "InterfaceName": eth_name,
        "RxBytes": eth.get("rx_bytes", 0),
        "RxPackets": eth.get("rx_packets", 0),
        "RxErrors": eth.get("rx_errors", 0),
        "RxDropped": eth.get("rx_dropped", 0),
        "TxBytes": eth.get("tx_bytes", 0),
        "TxPackets": eth.get("tx_packets", 0),
        "TxErrors": eth.get("tx_errors", 0),
        "TxDropped": eth.get("tx_dropped", 0),
        "CpuUsagePct": _cpu_pct(stats),
        "MemoryUsageBytes": mem.get("usage", 0),
        "MemoryLimitBytes": mem.get("limit", 0),
    }


def _project_resource(name: str, stats: dict[str, Any]) -> dict[str, Any]:
    networks = stats.get("networks", {}) or {}
    rx = sum(n.get("rx_bytes", 0) for n in networks.values())
    tx = sum(n.get("tx_bytes", 0) for n in networks.values())
    mem = stats.get("memory_stats", {}) or {}
    blkio = stats.get("blkio_stats", {}).get("io_service_bytes_recursive", []) or []
    read_bytes = sum(item.get("value", 0) for item in blkio if item.get("op", "").lower() == "read")
    write_bytes = sum(item.get("value", 0) for item in blkio if item.get("op", "").lower() == "write")
    return {
        "TimeGenerated": _now_iso(),
        "ContainerName": name,
        "CpuUsagePct": _cpu_pct(stats),
        "MemoryUsageBytes": mem.get("usage", 0),
        "MemoryLimitBytes": mem.get("limit", 0),
        "NetworkRxBytes": rx,
        "NetworkTxBytes": tx,
        "BlockReadBytes": read_bytes,
        "BlockWriteBytes": write_bytes,
    }


def _parse_ss_lines(text: str) -> Iterable[dict[str, Any]]:
    """Parse `ss -tn -H` output. Columns: State Recv-Q Send-Q Local Peer ...

    Connection counted if EITHER local OR peer port is in CONN_PORTS — captures
    both inbound (local port = listener) and outbound (peer port = listener).
    """
    for raw in text.splitlines():
        parts = raw.split()
        if len(parts) < 5:
            continue
        state, _recvq, _sendq, local, peer = parts[0], parts[1], parts[2], parts[3], parts[4]
        if ":" not in local or ":" not in peer:
            continue
        local_ip, local_port = local.rsplit(":", 1)
        peer_ip, peer_port = peer.rsplit(":", 1)
        if CONN_PORTS and local_port not in CONN_PORTS and peer_port not in CONN_PORTS:
            continue
        yield {
            "TimeGenerated": _now_iso(),
            "State": state,
            "LocalIp": local_ip,
            "LocalPort": int(local_port) if local_port.isdigit() else 0,
            "PeerIp": peer_ip,
            "PeerPort": int(peer_port) if peer_port.isdigit() else 0,
        }


def _emit(handle, record: dict[str, Any]) -> None:
    if handle is None:
        return
    handle.write(json.dumps(record, separators=(",", ":"), default=str) + "\n")
    handle.flush()


def main() -> int:
    main_handle = _open(LOG_FILE_PATH)
    if main_handle is not None:
        _log(f"datalink sink active: {LOG_FILE_PATH}")
    resource_handle = _open(RESOURCE_FILE_PATH)
    if resource_handle is not None:
        _log(f"resource-metrics sink active: {RESOURCE_FILE_PATH}")
    conn_handle = _open(CONN_FILE_PATH)
    if conn_handle is not None:
        _log(f"connections sink active: {CONN_FILE_PATH}")

    _log(f"polling {CONTAINER_NAME} + project={PROJECT_LABEL_FILTER} every {POLL_INTERVAL}s")
    client = docker.from_env()

    while True:
        # 1) datalink container network stats
        try:
            datalink_container = client.containers.get(CONTAINER_NAME)
            stats = datalink_container.stats(stream=False)
            _emit(main_handle, _project_network(CONTAINER_NAME, stats))
        except docker.errors.NotFound:
            _log(f"target container {CONTAINER_NAME} not found")
        except Exception as exc:  # noqa: BLE001
            _log(f"datalink poll error: {exc}")

        # 2) resource metrics for every project container.
        # Iterating the list yields docker SDK Container objects that lazily
        # 404 if a container was removed between list and inspect — guard each
        # entry so one transient peer death doesn't skip the rest of the cycle.
        containers: list[Any] = []
        try:
            containers = client.containers.list(
                filters={"label": f"com.docker.compose.project={PROJECT_LABEL_FILTER}"}
            )
        except Exception as exc:  # noqa: BLE001
            _log(f"container list error: {exc}")
        for container in containers:
            try:
                cstats = container.stats(stream=False)
                _emit(resource_handle, _project_resource(container.name, cstats))
            except docker.errors.NotFound:
                _log(f"container disappeared mid-poll: {getattr(container, 'name', '?')}")
            except Exception as exc:  # noqa: BLE001
                _log(f"resource poll error for {getattr(container, 'name', '?')}: {exc}")

        # 3) connection snapshot via docker exec ss inside the datalink container
        try:
            datalink_container = client.containers.get(CONTAINER_NAME)
            exec_result = datalink_container.exec_run(["ss", "-tn", "-H"], demux=False)
            text = exec_result.output.decode("utf-8", errors="replace") if exec_result.output else ""
            for conn in _parse_ss_lines(text):
                _emit(conn_handle, conn)
        except Exception as exc:  # noqa: BLE001
            _log(f"connection poll error: {exc}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    sys.exit(main() or 0)
