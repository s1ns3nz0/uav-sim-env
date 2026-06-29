#!/usr/bin/env python3
"""mavlink-router stats parser — stdin (merged stdout+stderr) → NDJSON to stdout.

DCR Custom-UAVRouterStats 컬럼: TimeGenerated, EndpointName, MsgRx, MsgTx, MsgDropped, CrcErrors.
Marker = EndpointName (fluent-bit rewrite_tag 가 이 키로 stats 라인만 분기).

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
import re
import sys
from datetime import datetime, timezone

HDR = re.compile(r"^\w+ Endpoint \[(?P<id>-?\d+)\](?P<name>\S+) \{$")
RX_HDR = re.compile(r"^\tReceived messages \{$")
TX_HDR = re.compile(r"^\tTransmitted messages \{$")
CRC = re.compile(r"^\t\tCRC error:\s+(\d+)")
LOST = re.compile(r"^\t\tSequence lost:\s+(\d+)")
TOTAL = re.compile(r"^\t\tTotal:\s+(\d+)")
INNER_CLOSE = re.compile(r"^\t\}$")
OUTER_CLOSE = re.compile(r"^\}$")


def emit(state: dict) -> None:
    rec = {
        "TimeGenerated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "EndpointName": state.get("name", "unknown"),
        "MsgRx": state.get("rx_total", 0),
        "MsgTx": state.get("tx_total", 0),
        "MsgDropped": state.get("dropped", 0),
        "CrcErrors": state.get("crc", 0),
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
