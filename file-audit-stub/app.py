"""file-audit-stub — host/container file & process execution audit.

`UAVFileAudit_CL` (infra/sentinel/tables.bicep) was scaffolded ahead of a
producer in an earlier pass, intended for a real eBPF/Falco DaemonSet. That
requires privileged access to AKS nodes — a meaningfully different risk/ops
profile than every other attack-surface simulator in this repo. Until that
tradeoff is worth making, this stub gives the table a producer the same way
`web-stub` gives S48~S55 one: an explicit, audited control call standing in
for what a real runtime sensor would observe on its own.

Safety note — same convention as every other stub here: no real filesystem
or process operation happens. A caller declares "this access/exec occurred"
and the stub only records it.

Feeds one table: UAVFileAudit_CL
  file_access  — S47(anti-forensics/log deletion), S57(cron persistence file)
  exec_attempt — S50(SUID/GTFOBins), S51/S56(container-escape follow-on),
                 T0809/T1485(data destruction)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field


LOG_FILE_PATH: str = os.environ.get("LOG_FILE_PATH", "")

# Paths whose access/deletion is itself the signal (log/evidence stores,
# persistence launch points) — mirrors UAVServiceAudit_CL's
# LogBearingTargetSuspected heuristic, applied at the file layer.
LOG_BEARING_PATH_HINTS: tuple[str, ...] = ("/var/log/uav-sim-env", "ndjson", "audit")
PERSISTENCE_PATH_HINTS: tuple[str, ...] = ("/etc/cron.d", "/etc/ld.so.preload", "startup.d")

app = FastAPI(
    title="file-audit-stub",
    version="0.1.0",
    description="Host/container file + process execution audit (UAVFileAudit_CL producer).",
)

_log_file_handle = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _emit(event: dict[str, Any]) -> None:
    if _log_file_handle is None:
        return
    enriched = {"TimeGenerated": _now_iso(), **event}
    _log_file_handle.write(json.dumps(enriched, separators=(",", ":"), default=str) + "\n")
    _log_file_handle.flush()


@app.on_event("startup")
def _open_sink() -> None:
    global _log_file_handle
    if not LOG_FILE_PATH:
        return
    os.makedirs(os.path.dirname(LOG_FILE_PATH) or ".", exist_ok=True)
    _log_file_handle = open(LOG_FILE_PATH, "a", encoding="utf-8")


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


class FileAccessRequest(BaseModel):
    container_name: str = Field(..., examples=["telemetry-tap"])
    pid: int = Field(..., examples=[4821])
    process_name: str = Field(..., examples=["python3"])
    operation: str = Field(..., examples=["read", "write", "delete", "create", "chmod"])
    file_path: str = Field(..., examples=["/var/log/uav-sim-env/telemetry.ndjson"])
    bytes_accessed: int = Field(0, ge=0)
    user: str = Field("root", examples=["root"])


@app.post("/file/access", tags=["file"])
def file_access(req: FileAccessRequest) -> dict[str, Any]:
    """Record a file-level operation (read/write/delete/create/chmod).

    S47(anti-forensics) — `LogBearingTargetSuspected` reuses the same
    heuristic as `UAVServiceAudit_CL.LogBearingTargetSuspected` (S47/S66) at
    the file layer: is the target itself an evidence store? `Persistent`
    flags launch-point paths (cron.d, ld.so.preload) for S57-adjacent
    persistence review even outside web-stub's dedicated cron endpoint.
    """
    path_lower = req.file_path.lower()
    log_bearing = req.operation in ("delete", "write") and any(
        h in path_lower for h in LOG_BEARING_PATH_HINTS
    )
    persistent = any(h in path_lower for h in PERSISTENCE_PATH_HINTS)
    _emit({
        "ContainerName": req.container_name,
        "Pid": req.pid,
        "ProcessName": req.process_name,
        "Operation": req.operation,
        "FilePath": req.file_path,
        "BytesAccessed": req.bytes_accessed,
        "User": req.user,
        "Syscall": {"read": "read", "write": "write", "delete": "unlink",
                    "create": "open", "chmod": "chmod"}.get(req.operation, req.operation),
        "LogBearingTargetSuspected": log_bearing,
        "PersistenceTargetSuspected": persistent,
    })
    return {"logged": True, "operation": req.operation, "log_bearing_target": log_bearing}


class ExecAttemptRequest(BaseModel):
    container_name: str = Field(..., examples=["web-stub"])
    pid: int = Field(..., examples=[9931])
    process_name: str = Field(..., examples=["find"])
    args: str = Field("", examples=[". -exec /bin/sh -p \\; -quit"])
    user: str = Field("root", examples=["root"])


@app.post("/exec/attempt", tags=["exec"])
def exec_attempt(req: ExecAttemptRequest) -> dict[str, Any]:
    """Record a process-execution event (execve syscall)."""
    _emit({
        "ContainerName": req.container_name,
        "Pid": req.pid,
        "ProcessName": req.process_name,
        "Operation": "exec",
        "FilePath": req.args,
        "BytesAccessed": 0,
        "User": req.user,
        "Syscall": "execve",
    })
    return {"logged": True, "process_name": req.process_name}
