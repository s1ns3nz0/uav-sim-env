"""supply-chain-stub — artifact signing + mTLS certificate control plane.

`pgse-stub` already audits *firmware image* supply-chain integrity
(hash/SBOM allowlist). This stub covers two adjacent DevSecOps surfaces that
had no producer anywhere in this repo: build-artifact signature verification
(container images, deployment manifests) and mTLS certificate issuance for
service-to-service auth — both named explicitly in `fried-pollack-ai`'s
extended scenario catalogue (S70 mTLS forge, S73 signature-verification
bypass) with no corresponding target-side telemetry.

Safety note — same convention as every other attack-surface stub in this
repo: signatures/certs are toy in-memory constructs, not real cosign/x509
material. Nothing here actually signs or trusts a real deployable artifact.

Feeds one table: UAVSupplyChain_CL
  artifact_signature_verify — T1553(Subvert Trust Controls)
  cert_issued / cert_validated — T1649(Steal/Forge Auth Certificates)
"""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field


LOG_FILE_PATH: str = os.environ.get("LOG_FILE_PATH", "")

# Known-good signing keys per artifact class (toy — a real deployment would
# use cosign/sigstore against a transparency log).
TRUSTED_SIGNERS: frozenset[str] = frozenset({"key:release-sign-2026", "key:ci-pipeline-prod"})
# Issued mTLS certs — serial -> {subject, issuer}. Populated by /mtls/issue-cert.
_issued_certs: dict[str, dict[str, str]] = {}

app = FastAPI(
    title="supply-chain-stub",
    version="0.1.0",
    description="Artifact signing + mTLS certificate control plane (S70/S73).",
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


# ---- S73: 아티팩트 서명 우회 -------------------------------------------------

class SignatureVerifyRequest(BaseModel):
    artifact_name: str = Field(..., examples=["uav-sim/web-stub:1.4.0"])
    signer_key: str = Field(..., examples=["key:release-sign-2026"])
    force_accept: bool = Field(
        False, description="deploy pipeline overrides a failed verification"
    )


@app.post("/artifact/verify-signature", tags=["artifact"])
def verify_signature(req: SignatureVerifyRequest) -> dict[str, Any]:
    """Verify an artifact's signature against the trusted-signer set.

    T1553(Subvert Trust Controls) — the vulnerability being modelled is
    `force_accept=true`: a pipeline that deploys an artifact *despite* an
    untrusted/unknown signer, matching the same "don't block, audit"
    convention as web-stub's IDOR endpoint.
    """
    signature_valid = req.signer_key in TRUSTED_SIGNERS
    bypass_suspected = req.force_accept and not signature_valid
    _emit({
        "EventType": "artifact_signature_verify",
        "Subject": req.artifact_name,
        "Issuer": req.signer_key,
        "SignatureValid": signature_valid,
        "BypassSuspected": bypass_suspected,
        "StatusCode": 200,
    })
    return {"artifact_name": req.artifact_name, "signature_valid": signature_valid,
            "deployed": signature_valid or req.force_accept}


# ---- S70: mTLS 인증서 위조 ---------------------------------------------------

class CertIssueRequest(BaseModel):
    subject: str = Field(..., examples=["telemetry-tap.soc.svc.cluster.local"])
    issuer: str = Field("uav-sim-ca", examples=["uav-sim-ca"])


@app.post("/mtls/issue-cert", tags=["mtls"])
def issue_cert(req: CertIssueRequest) -> dict[str, Any]:
    """Issue an mTLS client certificate for service-to-service auth."""
    serial = secrets.token_hex(8)
    _issued_certs[serial] = {"subject": req.subject, "issuer": req.issuer}
    _emit({
        "EventType": "cert_issued",
        "Subject": req.subject,
        "Issuer": req.issuer,
        "CertSerial": serial,
        "StatusCode": 200,
    })
    return {"serial": serial, "subject": req.subject, "issuer": req.issuer}


class CertValidateRequest(BaseModel):
    serial: str = Field(..., examples=["a1b2c3d4e5f60718"])
    presented_subject: str = Field(..., examples=["telemetry-tap.soc.svc.cluster.local"])
    presented_issuer: str = Field(..., examples=["uav-sim-ca"])


@app.post("/mtls/validate-cert", tags=["mtls"])
def validate_cert(req: CertValidateRequest) -> dict[str, Any]:
    """Validate a presented mTLS certificate against the issuance registry.

    T1649 — a certificate whose serial is unknown, or whose presented
    subject/issuer doesn't match what was actually issued for that serial,
    is a forged/stolen credential (self-signed or copied from another
    subject). Not rejected here (audit-only, same convention as elsewhere).
    """
    issued = _issued_certs.get(req.serial)
    forged_suspected = issued is None or (
        issued["subject"] != req.presented_subject or issued["issuer"] != req.presented_issuer
    )
    _emit({
        "EventType": "cert_validated",
        "Subject": req.presented_subject,
        "Issuer": req.presented_issuer,
        "CertSerial": req.serial,
        "CertForgedSuspected": forged_suspected,
        "StatusCode": 200 if issued else 404,
    })
    return {"serial": req.serial, "forged_suspected": forged_suspected}
