"""web-stub — ground IT-layer attack surface (S48~S55, C14~C18 killchain).

uav-sim-env's own scenario matrix originally stopped at the UAV telemetry
plane (S1/S3/S4/A4) — everything IT-layer (webshell, SUID/GTFOBins,
container escape, cron hijack, IDOR, archive path traversal) was undetected
not because blue lacked rules, but because **no service in this repo
exercised those techniques at all** (docs/sentinel-schemas.md §16, killchain
C14~C18: "UAV Sentinel 완전 사각 — 컨테이너/호스트/웹 로깅 시급").

Safety note — this stub follows the same convention as every other attack
surface in this repo (`datalink-satcom` `/satcom/inject`, `counter-uas`
"no real transmission"): each endpoint **simulates the technique's
detectable signature via an explicit control call**, it does not implement
a genuinely exploitable primitive. Nothing here actually executes uploaded
content, actually escalates a real Linux privilege, actually escapes a
real container, or actually installs a real crontab — those would be live
vulnerabilities in a cloud-hosted pod, not a controlled simulation. The one
exception (archive extraction, S53~S55) performs *real* zipfile/tarfile
extraction — but only into a per-request ephemeral temp directory that is
deleted immediately after, so a genuine Zip Slip write only ever lands in
disposable container-local storage.

Feeds two tables:
  UAVWebAudit_CL     — S48~S52 (IDOR, webshell, SUID/GTFOBins, container
                       escape, cron hijack)
  UAVArchiveAudit_CL — S53~S55 (Zip Slip, tar symlink escape, absolute path)
"""
from __future__ import annotations

import json
import os
import re
import tarfile
import tempfile
import zipfile
from base64 import b64decode
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


LOG_FILE_PATH: str = os.environ.get("LOG_FILE_PATH", "")
ARCHIVE_LOG_FILE_PATH: str = os.environ.get("ARCHIVE_LOG_FILE_PATH", "")

# S49 — 웹셸 시그니처(파일 콘텐츠에 대한 패턴 매칭만 수행. 절대 실행/eval 안 함).
WEBSHELL_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"<\?php", r"<%.*eval", r"eval\s*\(", r"exec\s*\(", r"system\s*\(",
        r"passthru\s*\(", r"shell_exec\s*\(", r"base64_decode\s*\(",
    )
)

# S50 — GTFOBins 로 잘 알려진 privesc 발판 바이너리(시뮬레이션 판정용 목록).
GTFOBINS_KNOWN: frozenset[str] = frozenset({
    "find", "vim", "less", "awk", "python3", "perl", "nmap", "cp", "tar",
})

app = FastAPI(
    title="web-stub",
    version="0.1.0",
    description="Ground IT-layer attack-surface simulation (S48~S55).",
)

_operators: dict[str, dict[str, Any]] = {
    "operator-01": {"name": "sgt.yang", "role": "loader"},
    "operator-02": {"name": "lt.kim", "role": "mission_planner"},
    "operator-03": {"name": "capt.park", "role": "commander"},
}
_log_file_handle = None
_archive_log_file_handle = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _emit(event: dict[str, Any]) -> None:
    if _log_file_handle is None:
        return
    # StreamWebAudit — 항상 채워지는 문자열 마커(fluentbit rewrite_tag 용).
    # UAVWebAudit_CL 의 5개 EventType 은 공통 필드가 없어 telemetry-tap 과 동일하게
    # 전용 마커 키를 명시적으로 추가한다.
    enriched = {"TimeGenerated": _now_iso(), "StreamWebAudit": "web", **event}
    _log_file_handle.write(json.dumps(enriched, separators=(",", ":"), default=str) + "\n")
    _log_file_handle.flush()


def _emit_archive(event: dict[str, Any]) -> None:
    handle = _archive_log_file_handle or _log_file_handle
    if handle is None:
        return
    enriched = {"TimeGenerated": _now_iso(), "StreamArchive": "archive", **event}
    handle.write(json.dumps(enriched, separators=(",", ":"), default=str) + "\n")
    handle.flush()


@app.on_event("startup")
def _open_sinks() -> None:
    global _log_file_handle, _archive_log_file_handle
    if LOG_FILE_PATH:
        os.makedirs(os.path.dirname(LOG_FILE_PATH) or ".", exist_ok=True)
        _log_file_handle = open(LOG_FILE_PATH, "a", encoding="utf-8")
    if ARCHIVE_LOG_FILE_PATH:
        os.makedirs(os.path.dirname(ARCHIVE_LOG_FILE_PATH) or ".", exist_ok=True)
        _archive_log_file_handle = open(ARCHIVE_LOG_FILE_PATH, "a", encoding="utf-8")


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


# ---- S48: 인증우회 / IDOR --------------------------------------------------

@app.get("/weapon/{operator_id}", tags=["idor"])
def get_operator_profile(operator_id: str, session_operator: str = "") -> dict[str, Any]:
    """Return an operator's weapon-panel profile.

    S48(IDOR) — no ownership check against the caller's own session
    identity(`session_operator`), matching the killchain C18 example
    (`GET /weapon/operator-02`) verbatim. IDOR itself is intentionally not
    blocked here(that's the vulnerability being modelled) — the audit trail
    is what lets blue catch it.
    """
    profile = _operators.get(operator_id)
    idor_suspected = bool(session_operator) and session_operator != operator_id
    _emit({
        "EventType": "operator_profile_access",
        "RequesterId": session_operator,
        "TargetId": operator_id,
        "IdorSuspected": idor_suspected,
        "StatusCode": 200 if profile else 404,
    })
    if profile is None:
        raise HTTPException(404, f"Unknown operator {operator_id}")
    return {"operator_id": operator_id, **profile}


# ---- S49: 파일업로드 웹셸 ---------------------------------------------------

class UploadRequest(BaseModel):
    filename: str = Field(..., examples=["imagery.php"])
    content: str = Field("", max_length=4096, examples=["<?php system($_GET['c']); ?>"])


@app.post("/imagery/upload", tags=["upload"])
def upload_imagery(req: UploadRequest) -> dict[str, Any]:
    """Accept an imagery/mission-artifact upload.

    S49(파일업로드 웹셸) — content is only pattern-matched in memory, never
    written to an executable path or evaluated. Detection, not execution.
    """
    matched = next((p.pattern for p in WEBSHELL_PATTERNS if p.search(req.content)), None)
    _emit({
        "EventType": "imagery_upload",
        "Filename": req.filename,
        "ContentSnippet": req.content[:200],
        "WebshellSignatureDetected": matched is not None,
        "MatchedPattern": matched or "",
        "StatusCode": 200,
    })
    return {"filename": req.filename, "accepted": True}


# ---- S50: SUID/GTFOBins 권한상승 ------------------------------------------

class HostExecRequest(BaseModel):
    binary: str = Field(..., examples=["find"])
    args: str = Field("", examples=[". -exec /bin/sh -p \\; -quit"])
    privilege_before: str = Field("operator", examples=["operator"])


@app.post("/host/exec", tags=["privesc"])
def host_exec(req: HostExecRequest) -> dict[str, Any]:
    """Simulate invoking a (SUID-bit or GTFOBins-listed) binary.

    S50 — no real subprocess is spawned; this only classifies the binary
    against a known GTFOBins set and logs the simulated privilege outcome.
    """
    is_gtfobins = req.binary in GTFOBINS_KNOWN
    privilege_after = "root" if is_gtfobins else req.privilege_before
    _emit({
        "EventType": "host_exec_attempt",
        "Binary": req.binary,
        "Args": req.args,
        "GtfobinsMatch": is_gtfobins,
        "PrivilegeBefore": req.privilege_before,
        "PrivilegeAfter": privilege_after,
        "StatusCode": 200,
    })
    return {"binary": req.binary, "privilege_after": privilege_after}


# ---- S51: 컨테이너 escape --------------------------------------------------

class EscapeAttemptRequest(BaseModel):
    method: Literal["docker_sock_mount", "privileged_flag", "hostpath_mount", "cap_sys_admin"]
    target_path: str = Field("", examples=["/var/run/docker.sock"])


@app.post("/container/escape-attempt", tags=["escape"])
def container_escape_attempt(req: EscapeAttemptRequest) -> dict[str, Any]:
    """Log a container-escape technique attempt. No real escape is performed."""
    _emit({
        "EventType": "container_escape_attempt",
        "EscapeMethod": req.method,
        "TargetPath": req.target_path,
        "StatusCode": 200,
    })
    return {"method": req.method, "logged": True}


# ---- S52: cron 하이재킹 -----------------------------------------------------

class CronInstallRequest(BaseModel):
    entry: str = Field(..., examples=["* * * * * root /opt/rogue"])
    installed_by: str = Field("", examples=["www-data"])


class RootkitInstallRequest(BaseModel):
    method: Literal["kernel_module", "ld_preload", "syscall_hook"]
    target_path: str = Field("", examples=["/lib/modules/rogue.ko"])
    inhibits_alarms: bool = Field(
        False, description="T0851 — rootkit also suppresses SOC/failsafe alarm reporting"
    )


@app.post("/cron/install", tags=["persistence"])
def cron_install(req: CronInstallRequest) -> dict[str, Any]:
    """Log a cron-persistence install attempt. Never touches a real crontab."""
    _emit({
        "EventType": "cron_entry_installed",
        "CronEntry": req.entry,
        "InstalledBy": req.installed_by,
        "StatusCode": 200,
    })
    return {"entry": req.entry, "logged": True}


# ---- S62: rootkit 설치 / 경보 억제 ------------------------------------------

@app.post("/host/rootkit-install", tags=["persistence"])
def rootkit_install(req: RootkitInstallRequest) -> dict[str, Any]:
    """Log a rootkit-install attempt. No real kernel module/hook is loaded.

    T1014(Rootkit)/T0851(Rootkit — Inhibit Response) — `inhibits_alarms=true`
    models the variant that also suppresses alarm/response reporting (the
    ICS-side sibling technique), reusing `EscapeMethod`/`TargetPath` from the
    container-escape schema rather than growing the table further.
    """
    _emit({
        "EventType": "rootkit_install_attempt",
        "EscapeMethod": req.method,
        "TargetPath": req.target_path,
        "AlarmsInhibited": req.inhibits_alarms,
        "StatusCode": 200,
    })
    return {"method": req.method, "logged": True}


# ---- S53~S55: 아카이브 경로순회(Zip Slip) / tar 심볼릭 링크 / 절대경로 -------

class ArchiveExtractRequest(BaseModel):
    archive_name: str = Field(..., examples=["firmware-bundle.zip"])
    archive_b64: str = Field(..., description="base64-encoded zip/tar archive, size-capped")
    archive_type: Literal["zip", "tar"] = "zip"
    mode: Literal["safe", "vulnerable"] = Field(
        "safe", description="vulnerable = no path sanitisation (Zip Slip reproduced)"
    )


def _entry_findings(name: str) -> dict[str, bool]:
    return {
        "path_traversal": ".." in Path(name).parts,
        "absolute_path": os.path.isabs(name),
    }


@app.post("/archive/extract", tags=["archive"])
def archive_extract(req: ArchiveExtractRequest) -> dict[str, Any]:
    """Extract an uploaded archive into an ephemeral, per-request temp dir.

    S53(Zip Slip)/S54(tar symlink escape)/S55(절대경로 추출) — `mode="vulnerable"`
    reproduces the real bug (extracts entries as-is, no `..`/absolute-path/
    symlink sanitisation) so blue can observe genuine escape behaviour, but
    the blast radius is capped: extraction target is a `tempfile.
    TemporaryDirectory()` deleted at the end of the request, never a shared
    or persistent volume.
    """
    raw = b64decode(req.archive_b64)
    if len(raw) > 5_000_000:
        raise HTTPException(413, "archive too large for this stub (5MB cap)")

    blocked = 0
    extracted = 0
    entries: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="web-stub-archive-") as tmpdir:
        archive_path = Path(tmpdir) / "in.archive"
        archive_path.write_bytes(raw)

        try:
            if req.archive_type == "zip":
                with zipfile.ZipFile(archive_path) as zf:
                    for info in zf.infolist():
                        findings = _entry_findings(info.filename)
                        is_bad = findings["path_traversal"] or findings["absolute_path"]
                        if is_bad and req.mode == "safe":
                            blocked += 1
                        else:
                            if req.mode == "vulnerable" and is_bad:
                                # 실제 zip slip 재현 — 그러나 tmpdir 자체가 이 요청이
                                # 끝나면 통째로 삭제되는 격리 디렉터리.
                                dest = Path(tmpdir) / info.filename
                            else:
                                dest = Path(tmpdir) / "safe_out" / Path(info.filename).name
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            try:
                                dest.write_bytes(zf.read(info.filename))
                                extracted += 1
                            except (OSError, IsADirectoryError):
                                pass
                        entries.append({"name": info.filename, **findings})
            else:
                # tar 는 멤버 분류(경로순회/절대경로/심볼릭링크)만 수행하고 실제
                # tf.extract()는 호출하지 않는다 — Python 3.11 tarfile 의 기본
                # extractall/extract 는 그 자체로 알려진 CVE(예 CVE-2007-4559)의
                # 대상이라, 탐지 목적상 진짜로 파일을 풀 필요가 없는 한 그 경로를
                # 열지 않는다(zip 은 자체 구현 경로라 위 로직으로 격리 제어됨).
                with tarfile.open(archive_path) as tf:
                    for member in tf.getmembers():
                        findings = _entry_findings(member.name)
                        symlink_escape = member.issym() or member.islnk()
                        findings["symlink_escape"] = symlink_escape
                        is_bad = findings["path_traversal"] or findings["absolute_path"] or symlink_escape
                        if is_bad and req.mode == "safe":
                            blocked += 1
                        else:
                            extracted += 1
                        entries.append({"name": member.name, **findings})
        except (zipfile.BadZipFile, tarfile.TarError) as exc:
            raise HTTPException(400, f"invalid archive: {exc}") from exc

    any_path_traversal = any(e["path_traversal"] for e in entries)
    any_absolute = any(e["absolute_path"] for e in entries)
    any_symlink = any(e.get("symlink_escape") for e in entries)

    for e in entries:
        _emit_archive({
            "EventType": "archive_entry_extracted",
            "ArchiveName": req.archive_name,
            "Mode": req.mode,
            "EntryPath": e["name"],
            "PathTraversalDetected": e["path_traversal"],
            "AbsolutePathDetected": e["absolute_path"],
            "SymlinkEscapeDetected": e.get("symlink_escape", False),
            "StatusCode": 200,
        })
    _emit_archive({
        "EventType": "archive_extract_summary",
        "ArchiveName": req.archive_name,
        "Mode": req.mode,
        "PathTraversalDetected": any_path_traversal,
        "AbsolutePathDetected": any_absolute,
        "SymlinkEscapeDetected": any_symlink,
        "ExtractedCount": extracted,
        "BlockedCount": blocked,
        "StatusCode": 200,
    })
    return {
        "archive_name": req.archive_name,
        "mode": req.mode,
        "entries": len(entries),
        "extracted": extracted,
        "blocked": blocked,
        "path_traversal_detected": any_path_traversal,
        "absolute_path_detected": any_absolute,
        "symlink_escape_detected": any_symlink,
    }
