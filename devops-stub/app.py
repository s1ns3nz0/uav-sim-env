"""devops-stub — build/deploy pipeline attack surface (S67~S76 minus S70/S73,
S77 — fried-pollack-ai extended "공급망/DevSecOps"+"미들웨어" themes).

`supply-chain-stub` already covers artifact-signature bypass (S73) and mTLS
certificate forgery (S70). `pgse-stub`/`companion-stub` cover firmware and
modem supply chain. This stub covers the remaining DevSecOps meta-layer
techniques that had no producer anywhere: container-registry tampering,
CI/CD pipeline compromise, secrets-vault theft, dependency confusion, IaC
drift, build-provenance forgery, plus two UAV-adjacent middleware surfaces
(DDS/ROS2 discovery flood, MQTT bus poisoning).

Note on scope — these attack the software supply chain that *builds and
deploys* this simulation (or a real UAS program's equivalent), not the UAS
itself. Kept intentionally lightweight (grilling-session decision): this is
the one surface in this repo whose domain is "our own delivery pipeline"
rather than "the UAV/ground segment", so it gets a single consolidated stub
rather than being woven into UAV-specific services.

Safety note — same convention as every other stub here: no real registry
pull, CI/CD trigger, vault access, IaC apply, or MQTT/DDS traffic occurs.

Feeds one table: UAVDevOps_CL
  registry_image_pull    — S67(T1195.002, registry image tamper)
  cicd_pipeline_trigger  — S68(T1195.001, CI/CD pipeline compromise)
  vault_secret_access    — S69(T1552, secrets vault theft)
  dependency_resolve     — S71(T1195.001, dependency confusion)
  iac_apply              — S72(T1195, IaC tamper)
  build_provenance_verify— S74(T1195, build provenance attack)
  dds_discovery_flood    — S75(T1499, DDS/ROS2 discovery flood)
  mqtt_publish            — S76(T1565.001, MQTT bus poison)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field


LOG_FILE_PATH: str = os.environ.get("LOG_FILE_PATH", "")

TRUSTED_VAULT_ACCESSORS: frozenset[str] = frozenset({"ci-pipeline-sa", "deploy-controller-sa"})
DDS_FLOOD_THRESHOLD: int = 200

app = FastAPI(
    title="devops-stub",
    version="0.1.0",
    description="Build/deploy pipeline + UAV middleware attack-surface simulation (S67~S76).",
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


# ---- S67: 컨테이너 레지스트리 이미지 변조 ------------------------------------

class RegistryImagePullRequest(BaseModel):
    image_ref: str = Field(..., examples=["acr.uav-sim.io/web-stub:1.4.0"])
    digest_expected: str = Field(..., examples=["sha256:aaaa"])
    digest_pulled: str = Field(..., examples=["sha256:aaaa"])


@app.post("/registry/image-pull", tags=["registry"])
def registry_image_pull(req: RegistryImagePullRequest) -> dict[str, Any]:
    """Pull a container image and compare against the expected digest. T1195.002."""
    mismatch = req.digest_expected != req.digest_pulled
    _emit({
        "EventType": "registry_image_pull",
        "Target": req.image_ref,
        "DigestMismatch": mismatch,
        "StatusCode": 200,
    })
    return {"image_ref": req.image_ref, "digest_mismatch": mismatch}


# ---- S68: CI/CD 파이프라인 침해 ----------------------------------------------

class CicdTriggerRequest(BaseModel):
    pipeline_name: str = Field(..., examples=["deploy-uav-sim"])
    triggered_by: str = Field(..., examples=["github-actions"])
    source_ref: str = Field(..., examples=["refs/heads/main"])
    is_authorized_source: bool = Field(True)


@app.post("/cicd/pipeline-trigger", tags=["cicd"])
def cicd_pipeline_trigger(req: CicdTriggerRequest) -> dict[str, Any]:
    """Trigger a CI/CD pipeline run. T1195.001 — a trigger from an unrecognised source/ref."""
    _emit({
        "EventType": "cicd_pipeline_trigger",
        "Target": req.pipeline_name,
        "Actor": req.triggered_by,
        "UnauthorizedTrigger": not req.is_authorized_source,
        "StatusCode": 200,
    })
    return {"pipeline_name": req.pipeline_name, "unauthorized": not req.is_authorized_source}


# ---- S69: 시크릿/키 관리(Vault) 탈취 -----------------------------------------

class VaultAccessRequest(BaseModel):
    secret_path: str = Field(..., examples=["secret/uav-sim/dce-token"])
    accessor: str = Field(..., examples=["ci-pipeline-sa"])
    purpose: str = Field("", examples=["deploy"])


@app.post("/vault/secret-access", tags=["vault"])
def vault_secret_access(req: VaultAccessRequest) -> dict[str, Any]:
    """Read a secret from the vault. T1552 — accessor outside the known service-account allowlist."""
    exfil_suspected = req.accessor not in TRUSTED_VAULT_ACCESSORS
    _emit({
        "EventType": "vault_secret_access",
        "Target": req.secret_path,
        "Actor": req.accessor,
        "SecretExfilSuspected": exfil_suspected,
        "StatusCode": 200,
    })
    return {"secret_path": req.secret_path, "exfil_suspected": exfil_suspected}


# ---- S71: 의존성 혼동(dependency confusion) ----------------------------------

class DependencyResolveRequest(BaseModel):
    package_name: str = Field(..., examples=["uav-sim-internal-utils"])
    resolved_source: str = Field(..., examples=["public"])
    expected_source: str = Field("internal", examples=["internal"])


@app.post("/registry/dependency-resolve", tags=["registry"])
def dependency_resolve(req: DependencyResolveRequest) -> dict[str, Any]:
    """Resolve a package during a build. T1195.001 — an internal-only package name
    resolved from a public registry instead of the internal one."""
    confusion_suspected = req.resolved_source != req.expected_source
    _emit({
        "EventType": "dependency_resolve",
        "Target": req.package_name,
        "DependencyConfusionSuspected": confusion_suspected,
        "StatusCode": 200,
    })
    return {"package_name": req.package_name, "confusion_suspected": confusion_suspected}


# ---- S72: IaC(Terraform/Helm) 변조 -------------------------------------------

class IacApplyRequest(BaseModel):
    resource: str = Field(..., examples=["azurerm_network_security_rule.allow_5790"])
    diff_summary: str = Field("", examples=["+ destination_port_range: 5790"])
    applied_by: str = Field(..., examples=["operator-01"])
    planned: bool = Field(True, description="applied from a reviewed plan output vs. ad-hoc")


@app.post("/iac/apply", tags=["iac"])
def iac_apply(req: IacApplyRequest) -> dict[str, Any]:
    """Apply an infrastructure-as-code change. T1195 — applied without a prior plan/review step."""
    _emit({
        "EventType": "iac_apply",
        "Target": req.resource,
        "Actor": req.applied_by,
        "UnplannedApply": not req.planned,
        "StatusCode": 200,
    })
    return {"resource": req.resource, "unplanned": not req.planned}


# ---- S74: 빌드 프로버넌스/재현성 무결성 공격 ---------------------------------

class BuildProvenanceRequest(BaseModel):
    artifact: str = Field(..., examples=["uav-sim/web-stub:1.4.0"])
    build_id: str = Field(..., examples=["gha-run-9931"])
    provenance_hash: str = Field(..., examples=["sha256:bbbb"])
    expected_hash: str = Field(..., examples=["sha256:bbbb"])


@app.post("/build/provenance-verify", tags=["build"])
def build_provenance_verify(req: BuildProvenanceRequest) -> dict[str, Any]:
    """Verify an artifact's build-provenance attestation (SLSA-style). T1195 — reproducibility mismatch."""
    mismatch = req.provenance_hash != req.expected_hash
    _emit({
        "EventType": "build_provenance_verify",
        "Target": req.artifact,
        "Actor": req.build_id,
        "ProvenanceMismatch": mismatch,
        "StatusCode": 200,
    })
    return {"artifact": req.artifact, "provenance_mismatch": mismatch}


# ---- S75: DDS/ROS2 discovery 플러딩 ------------------------------------------

class DdsDiscoveryFloodRequest(BaseModel):
    participant_count: int = Field(..., ge=0, examples=[850])
    window_sec: int = Field(10, ge=1)


@app.post("/dds/discovery-flood", tags=["middleware"])
def dds_discovery_flood(req: DdsDiscoveryFloodRequest) -> dict[str, Any]:
    """Report a DDS/ROS2 discovery-traffic sample. T1499 — participant-announcement flood
    (RTPS SPDP amplification) starving legitimate discovery."""
    flood_suspected = req.participant_count > DDS_FLOOD_THRESHOLD
    _emit({
        "EventType": "dds_discovery_flood",
        "ParticipantCount": req.participant_count,
        "FloodSuspected": flood_suspected,
        "StatusCode": 200,
    })
    return {"participant_count": req.participant_count, "flood_suspected": flood_suspected}


# ---- S76: MQTT/메시지버스 텔레메트리 오염 ------------------------------------

class MqttPublishRequest(BaseModel):
    topic: str = Field(..., examples=["uav/MPD-001/telemetry"])
    payload: str = Field("", max_length=1024)
    retained: bool = False
    authorized: bool = False


@app.post("/mqtt/publish", tags=["middleware"])
def mqtt_publish(req: MqttPublishRequest) -> dict[str, Any]:
    """Publish onto the MQTT telemetry bus. T1565.001 — unauthorized publisher poisoning a
    retained topic (subsequent subscribers immediately receive the poisoned value)."""
    _emit({
        "EventType": "mqtt_publish",
        "Topic": req.topic,
        "UnauthorizedPublish": not req.authorized,
        "StatusCode": 200,
    })
    return {"topic": req.topic, "unauthorized": not req.authorized, "retained": req.retained}
