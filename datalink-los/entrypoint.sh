#!/usr/bin/env bash
# datalink-los entrypoint — apply tc netem (delay/loss/jitter), then run mavlink-router
set -euo pipefail

LINK_DELAY_MS="${LINK_DELAY_MS:-50}"
LINK_LOSS_PCT="${LINK_LOSS_PCT:-1}"
LINK_JITTER_MS="${LINK_JITTER_MS:-5}"
IFACE="${IFACE:-eth0}"

echo "[datalink-los] applying netem: delay=${LINK_DELAY_MS}ms jitter=${LINK_JITTER_MS}ms loss=${LINK_LOSS_PCT}%"

if tc qdisc show dev "$IFACE" | grep -q netem; then
    tc qdisc del dev "$IFACE" root || true
fi

tc qdisc add dev "$IFACE" root netem \
    delay "${LINK_DELAY_MS}ms" "${LINK_JITTER_MS}ms" distribution normal \
    loss "${LINK_LOSS_PCT}%" || {
    echo "[datalink-los] WARN: tc netem failed (need NET_ADMIN cap)" >&2
}

echo "[datalink-los] launching mavlink-router"
exec mavlink-routerd -c /etc/mavlink-router/main.conf
