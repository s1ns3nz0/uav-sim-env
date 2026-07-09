#!/usr/bin/env python3
"""mavlink-router stats parser — stdin (merged stdout+stderr) → NDJSON to stdout.

DCR Custom-UAVRouterStats 컬럼: TimeGenerated, EndpointName, MsgRx, MsgTx, MsgDropped,
CrcErrors, UnexpectedEndpoint.
Marker = EndpointName (fluent-bit rewrite_tag 가 이 키로 stats 라인만 분기).

T1557(텔레메트리 릴레이 MITM, grilling 세션 결정) — 정상 라우팅 토폴로지는
KNOWN_ENDPOINTS(env `KNOWN_ENDPOINTS`, 콤마구분)에 고정된 이름만 갖는다. mavlink-router
설정에 없던 엔드포인트가 통계 블록에 나타나면(=누군가 conf 를 바꿔 중계경로에
프록시를 끼워넣음) UnexpectedEndpoint=true 로 플래그. 정적 conf(compose)/동적 conf
(k8s, entrypoint.sh GEN_CONF=1) 양쪽 다 이름이 결정론적이라 오탐 없이 적용 가능.

mavlink-routerd ReportStats=true 출력 (block 단위):
    <Type> Endpoint [<id>]<name> {
        Received messages {
            CRC error: <n> <pct>% <KB>KB
            Sequence lost: <n> <pct>%
            Handled: <n> <KB>KB
            Total: <n>
        }
        Transmitted messages {
            Total: <n> <KB>KB
        }
    }

Non-stats 라인(연결 메시지 등)은 stderr 로 passthrough — fluent-bit 가 marker 없는 라인은 drop.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone

# 기본값 = docs/sentinel-schemas.md §20.4 에 문서화된 정적/동적 conf 엔드포인트 이름.
# k8s 동적 conf(GEN_CONF=1)는 편대(av_in_0..N)라 개수가 가변적이므로 접두사로 매칭.
_DEFAULT_KNOWN = "av_in,gcs_out,tap_out,tcp_5790"
KNOWN_ENDPOINT_NAMES: frozenset[str] = frozenset(
    e.strip() for e in os.environ.get("KNOWN_ENDPOINTS", _DEFAULT_KNOWN).split(",") if e.strip()
)
KNOWN_ENDPOINT_PREFIXES: tuple[str, ...] = ("av_in_",)

HDR = re.compile(r"^\w+ Endpoint \[(?P<id>-?\d+)\](?P<name>\S+) \{$")
RX_HDR = re.compile(r"^\tReceived messages \{$")
TX_HDR = re.compile(r"^\tTransmitted messages \{$")
CRC = re.compile(r"^\t\tCRC error:\s+(\d+)")
LOST = re.compile(r"^\t\tSequence lost:\s+(\d+)")
TOTAL = re.compile(r"^\t\tTotal:\s+(\d+)")
INNER_CLOSE = re.compile(r"^\t\}$")
OUTER_CLOSE = re.compile(r"^\}$")


def _is_known_endpoint(name: str) -> bool:
    return name in KNOWN_ENDPOINT_NAMES or name.startswith(KNOWN_ENDPOINT_PREFIXES)


def emit(state: dict) -> None:
    name = state.get("name", "unknown")
    rec = {
        "TimeGenerated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "EndpointName": name,
        "MsgRx": state.get("rx_total", 0),
        "MsgTx": state.get("tx_total", 0),
        "MsgDropped": state.get("dropped", 0),
        "CrcErrors": state.get("crc", 0),
        "UnexpectedEndpoint": not _is_known_endpoint(name),
    }
    sys.stdout.write(json.dumps(rec, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> None:
    state = None
    section = None
    for raw in sys.stdin:
        line = raw.rstrip("\n")
        m = HDR.match(line)
        if m:
            state = {"name": m.group("name"), "id": int(m.group("id"))}
            section = None
            continue
        if state is None:
            sys.stderr.write(raw)
            sys.stderr.flush()
            continue
        if RX_HDR.match(line):
            section = "rx"
            continue
        if TX_HDR.match(line):
            section = "tx"
            continue
        m = CRC.match(line)
        if m:
            state["crc"] = int(m.group(1))
            continue
        m = LOST.match(line)
        if m:
            state["dropped"] = int(m.group(1))
            continue
        m = TOTAL.match(line)
        if m:
            n = int(m.group(1))
            if section == "rx":
                state["rx_total"] = n
            elif section == "tx":
                state["tx_total"] = n
            continue
        if INNER_CLOSE.match(line):
            section = None
            continue
        if OUTER_CLOSE.match(line):
            emit(state)
            state = None
            section = None


if __name__ == "__main__":
    main()
