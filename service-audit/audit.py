"""service-audit — Kubernetes Event stream -> NDJSON.

Watches core/v1 Events across all namespaces via the Kubernetes API and emits
one JSON line per pod-lifecycle event to LOG_FILE_PATH. Downstream Fluent Bit
ships these into UAVServiceAudit_CL so the SOC can detect "telemetry-tap
crashed mid-mission", "a component was killed/evicted", or similar
infrastructure-side anomalies during a UAV operation.

AKS runs containerd (no /var/run/docker.sock — dockershim was removed from
Kubernetes years ago), so this watches the Kubernetes API instead of the
Docker daemon. Requires an in-cluster ServiceAccount bound to a ClusterRole
with get/list/watch on events (see local-k8s/helm/uav-sim/templates/
service-audit.yaml).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any

from kubernetes import client, config, watch
from kubernetes.client.rest import ApiException


LOG_FILE_PATH: str = os.environ.get("LOG_FILE_PATH", "")

# core/v1 Event reasons worth keeping — filters kubelet/controller chatter down
# to lifecycle-relevant events (mirrors the old INTERESTING_ACTIONS Docker set).
INTERESTING_REASONS: frozenset[str] = frozenset({
    "Pulled", "Created", "Started", "Killing", "Preempted", "Evicted",
    "SuccessfulDelete", "BackOff", "Failed", "FailedScheduling", "Unhealthy",
    "OOMKilling", "NodeNotReady",
})

# S47(드론 anti-forensics/로그삭제)·S66(데이터 파괴) — 전용 공격 코드는 없지만,
# 이 서비스가 이미 관측 중인 Kubernetes 이벤트만으로도 "로그를 만들어내는 자산
# 자체를 파괴/종료"하는 행위는 잡을 수 있다(신규 producer 불필요, 기존 신호 재해석).
DESTRUCTIVE_REASONS: frozenset[str] = frozenset({
    "Killing", "Preempted", "Evicted", "SuccessfulDelete", "OOMKilling",
})
LOG_BEARING_NAME_HINTS: tuple[str, ...] = (
    "telemetry-tap", "datalink-satcom", "datalink-los", "gcs-qgc", "counter-uas",
    "sar-stub", "pgse-stub", "auth-stub", "ti-stub", "mps-stub", "c4i-stub",
    "weapon-stub", "cyber-posture-stub", "service-audit", "fluentbit",
    "log", "ndjson",
)

_EXIT_CODE_RE = re.compile(r"exit code (-?\d+)", re.IGNORECASE)
_CONTAINER_FIELD_RE = re.compile(r"spec\.containers\{(.+?)\}")


def _log(line: str) -> None:
    sys.stderr.write(f"[service-audit] {line}\n")
    sys.stderr.flush()


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _is_log_bearing(name: str) -> bool:
    """True if a pod/container name hints it holds or produces NDJSON logs.

    Heuristic name-match only (no filesystem access) — flags the destruction
    of the telemetry pipeline's own components as a distinct signal from
    ordinary pod lifecycle churn (scale-downs, routine restarts, etc.).
    """
    lowered = (name or "").lower()
    return any(hint in lowered for hint in LOG_BEARING_NAME_HINTS)


def _record_from_event(evt: Any) -> dict[str, Any] | None:
    """Project a Kubernetes core/v1 Event into a flat NDJSON record."""
    reason = evt.reason or ""
    if reason not in INTERESTING_REASONS:
        return None

    involved = evt.involved_object
    field_path = involved.field_path or ""
    container_name = involved.name or ""
    m = _CONTAINER_FIELD_RE.search(field_path)
    if m:
        container_name = m.group(1)

    message = evt.message or ""
    exit_match = _EXIT_CODE_RE.search(message)

    return {
        "TimeGenerated": _now_iso(),
        "EventType": involved.kind or "",
        "Action": reason,
        "ActorId": involved.uid or "",
        "ContainerName": container_name,
        "ImageName": "",  # core/v1 Event 에는 이미지명이 없음(파드 spec 조회 필요, 미구현)
        "ExitCode": exit_match.group(1) if exit_match else "",
        "Signal": "",
        "ServiceLabel": involved.namespace or "",
        "ProjectLabel": "uav-sim-env",
        "Scope": (evt.source.component if evt.source else "") or "",
        # S47/S66 — 기존 신호(Action/ContainerName)만으로 파생하는 파괴행위 지표.
        "IsDestructiveAction": reason in DESTRUCTIVE_REASONS,
        "LogBearingTargetSuspected": _is_log_bearing(container_name),
    }


def _watch_loop(v1: client.CoreV1Api, handle) -> None:
    # timeout_seconds=0 은 "무한 대기"가 아니라 즉시 스트림을 닫아버려 이벤트를 받기도
    # 전에 재연결을 반복하는 버그였다. 지정하지 않으면 서버 기본값(보통 30~60분)까지
    # 유지되고, 끊기면 바깥 while 루프가 재연결한다.
    w = watch.Watch()
    for event in w.stream(v1.list_event_for_all_namespaces):
        record = _record_from_event(event["object"])
        if record is None:
            continue
        line = json.dumps(record, separators=(",", ":"), default=str) + "\n"
        sys.stdout.write(line)
        sys.stdout.flush()
        if handle is not None:
            handle.write(line)
            handle.flush()


def main() -> int:
    handle = None
    if LOG_FILE_PATH:
        os.makedirs(os.path.dirname(LOG_FILE_PATH) or ".", exist_ok=True)
        handle = open(LOG_FILE_PATH, "a", encoding="utf-8")
        _log(f"file sink active: {LOG_FILE_PATH}")

    _log("loading in-cluster kube config")
    config.load_incluster_config()
    v1 = client.CoreV1Api()
    _log("ready, watching cluster-wide events")

    try:
        while True:
            try:
                _watch_loop(v1, handle)
                _log("watch stream closed cleanly, reconnecting")
            except ApiException as exc:
                _log(f"watch stream error ({exc.status}), reconnecting in 5s")
                time.sleep(5)
    except KeyboardInterrupt:
        _log("interrupted, exiting")
        return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
