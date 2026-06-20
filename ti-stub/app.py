"""ti-stub — Threat Intelligence feed mock.

Models the slice that external feeds (CISA KEV, NVD, ATLAS, internal SIGINT)
would push to the SOC. Each indicator triggers UAVThreatIntel_CL audit events
so KQL rules can correlate "new HOSTILE indicator referenced UAV component"
or "feed update suggesting CT-2 posture elevation".
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field


LOG_FILE_PATH: str = os.environ.get("LOG_FILE_PATH", "")

app = FastAPI(title="ti-stub", version="0.1.0",
              description="Threat Intelligence feed mock for UAV SOC.")

_log_file_handle = None
_indicators: list[dict[str, Any]] = []


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


class Indicator(BaseModel):
    indicator_type: Literal["cve", "ip", "hash", "domain", "url"] = Field(..., alias="type")
    indicator: str
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    confidence_pct: int = Field(default=70, ge=0, le=100)
    source: str = "internal"
    description: str = ""

    model_config = {"populate_by_name": True}


class FeedUpdate(BaseModel):
    feed_name: str
    indicators: list[Indicator]


class PostureRecommendation(BaseModel):
    suggested_level: Literal["CT-3", "CT-2", "CT-1"]
    reason: str
    confidence_pct: int = Field(ge=0, le=100)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ti/indicators", tags=["indicators"])
def add_indicator(ind: Indicator) -> dict[str, Any]:
    record = ind.model_dump(by_alias=False)
    _indicators.append(record)
    _emit({
        "EventType": "indicator_added",
        "IndicatorType": record["indicator_type"],
        "Indicator": record["indicator"],
        "Severity": record["severity"],
        "ConfidencePct": record["confidence_pct"],
        "Source": record["source"],
        "Description": record["description"],
        "StatusCode": 200,
    })
    return record


@app.post("/ti/feeds", tags=["feeds"])
def post_feed(update: FeedUpdate) -> dict[str, Any]:
    _emit({
        "EventType": "feed_update",
        "FeedName": update.feed_name,
        "IndicatorCount": len(update.indicators),
        "StatusCode": 200,
    })
    for ind in update.indicators:
        record = ind.model_dump(by_alias=False)
        _indicators.append(record)
        _emit({
            "EventType": "indicator_added",
            "FeedName": update.feed_name,
            "IndicatorType": record["indicator_type"],
            "Indicator": record["indicator"],
            "Severity": record["severity"],
            "ConfidencePct": record["confidence_pct"],
            "Source": record["source"],
            "Description": record["description"],
            "StatusCode": 200,
        })
    return {"feed": update.feed_name, "count": len(update.indicators)}


@app.post("/ti/posture-recommendation", tags=["posture"])
def post_recommendation(rec: PostureRecommendation) -> dict[str, Any]:
    payload = rec.model_dump()
    _emit({
        "EventType": "posture_recommendation",
        "Recommendation": rec.suggested_level,
        "ConfidencePct": rec.confidence_pct,
        "Description": rec.reason,
        "StatusCode": 200,
    })
    return payload


@app.get("/ti/recent-indicators", tags=["indicators"])
def recent(limit: int = 25) -> list[dict[str, Any]]:
    return _indicators[-limit:]
