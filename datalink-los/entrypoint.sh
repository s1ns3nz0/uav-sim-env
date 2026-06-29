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

# conf 선택:
#  - compose(VM): GEN_CONF 미설정 → 정적 /etc/mavlink-router/main.conf (기존 동작 유지)
#  - k8s: GEN_CONF=1 → 서비스 DNS 를 IP 로 resolve 해서 conf 동적 생성
#    (mavlink-router 는 호스트명을 직접 해석 못 하므로 IP 로 박아준다)
CONF=/etc/mavlink-router/main.conf
if [ "${GEN_CONF:-0}" = "1" ]; then
    resolve() {
        local i ip
        for i in $(seq 1 30); do
            ip="$(getent hosts "$1" | awk '{print $1; exit}')"
            [ -n "$ip" ] && { echo "$ip"; return 0; }
            sleep 2
        done
        echo "[datalink-los] WARN: could not resolve $1" >&2
        echo ""
    }
    GCS_IP="$(resolve "${GCS_HOST:-gcs-qgc.ground.svc.cluster.local}")"
    TAP_IP="$(resolve "${TAP_HOST:-telemetry-tap.soc.svc.cluster.local}")"
    echo "[datalink-los] resolved gcs=$GCS_IP tap=$TAP_IP"
    CONF=/tmp/main.conf
    cat > "$CONF" <<EOF
[General]
TcpServerPort=5790
ReportStats=true
MavlinkDialect=common
Log=/tmp/mavlink-router.log
LogMode=while-armed

[UdpEndpoint gcs_out]
Mode=Normal
Address=${GCS_IP}
Port=${GCS_PORT:-14550}

[UdpEndpoint tap_out]
Mode=Normal
Address=${TAP_IP}
Port=${TAP_PORT:-14552}
EOF
    # 편대(StatefulSet) — av-muav-0/1/2.av-muav.air.svc 다 별도 TcpEndpoint.
    # SITL 의 mavlink TCP port = 5760 + 10*ORD. AV_STS=StatefulSet 이름, AV_NS=ns,
    # AV_REPLICAS=N. 차트에서 env 로 넘겨준다.
    AV_STS="${AV_STS:-av-muav}"
    AV_NS="${AV_NS:-air}"
    AV_REPLICAS="${AV_REPLICAS:-1}"
    for i in $(seq 0 $((AV_REPLICAS - 1))); do
        AV_FQDN="${AV_STS}-${i}.${AV_STS}.${AV_NS}.svc.cluster.local"
        AV_IP="$(resolve "$AV_FQDN")"
        AV_PORT=$((5760 + 10*i))
        echo "[datalink-los] av_in_${i}: $AV_FQDN ($AV_IP):$AV_PORT"
        cat >> "$CONF" <<EOF

[TcpEndpoint av_in_${i}]
Address=${AV_IP}
Port=${AV_PORT}
RetryTimeout=3
EOF
    done
fi

echo "[datalink-los] launching mavlink-router (conf=$CONF) → router_stats_to_ndjson sidecar"
# stdout+stderr → router_stats_to_ndjson parser → container stdout (NDJSON for UAVRouterStats_CL).
# Parser 가 stats block 만 NDJSON 으로 변환, 평문은 stderr 로 passthrough → marker EndpointName 없는 라인 자연 drop.
exec mavlink-routerd -c "$CONF" 2>&1 | python3 -u /usr/local/bin/router_stats_to_ndjson.py
