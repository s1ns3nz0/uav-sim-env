#!/usr/bin/env bash
# full-ingest.sh — one-shot deploy + verify of the full UAV ingest pipeline.
#
# Resilient: every step is idempotent and every external call is wrapped in
# retry. Designed to be re-runnable from a clean repo at any time.
#
# Pipeline order:
#   1) preflight (working tree, az login, repo at origin/main)
#   2) bicep deploy: tables.bicep + dcr.bicep
#   3) NSG rules for 8400/8500/8600 (idempotent)
#   4) ssh vm: git pull, docker compose build + up -d, restart AMA
#   5) per-service health wait (curl localhost with retry)
#   6) fire test events for every new service
#   7) wait 5 minutes for AMA / DCR ingest
#   8) KQL verify against every UAV* table
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SIM_RG="dah-sim-rg"
DATA_RG="dah-data-rg"
SIM_DEPLOY="uavsim-mvp"
DATA_WS="dah-data-law"
NSG_NAME="uavsim-nsg"
INGEST_WAIT_SEC="${INGEST_WAIT_SEC:-300}"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
hr()   { printf -- '─%.0s' {1..72}; printf '\n'; }
step() { hr; bold "▶ $*"; }
warn() { printf '\033[33m⚠ %s\033[0m\n' "$*" >&2; }
fail() { printf '\033[31m✘ %s\033[0m\n' "$*" >&2; exit 1; }


retry() {
    # retry COUNT SLEEP CMD...
    local count="$1" sleep_s="$2"; shift 2
    local i
    for (( i = 1; i <= count; i++ )); do
        if "$@"; then
            return 0
        fi
        sleep "$sleep_s"
    done
    return 1
}


wait_for_health() {
    # wait_for_health HOST PORT [path]
    local host="$1" port="$2" path="${3:-/health}" max_iter=60 i
    bold "  waiting for $host:$port$path"
    for (( i = 1; i <= max_iter; i++ )); do
        local code
        code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://$host:$port$path" || true)
        if [[ "$code" =~ ^2[0-9][0-9]$ ]]; then
            bold "  ok ($code) after ${i}s"
            return 0
        fi
        sleep 1
    done
    fail "health check timed out for $host:$port$path"
}


fire() {
    # fire DESCRIPTION URL [JSON-BODY]
    local desc="$1" url="$2" body="${3:-}"
    bold "[fire] $desc"
    if [[ -n "$body" ]]; then
        curl -sS --max-time 10 -X POST "$url" \
            -H "Content-Type: application/json" \
            -d "$body" | (jq -c . 2>/dev/null || cat)
    else
        curl -sS --max-time 10 "$url" | (jq -c . 2>/dev/null || cat)
    fi
}


step "[1/8] preflight"
cd "$REPO_DIR"
if [[ -n "$(git status --porcelain)" ]]; then
    git status --short
    fail "working tree dirty — commit/stash first"
fi
git fetch --quiet origin
LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse @{u})"
if [[ "$LOCAL" != "$REMOTE" ]]; then
    bold "  local behind remote, fast-forward"
    git pull --ff-only
fi
command -v az  >/dev/null || fail "az CLI not installed"
command -v jq  >/dev/null || fail "jq not installed"
command -v ssh >/dev/null || fail "ssh not installed"
az account show >/dev/null || fail "az not logged in (run: az login)"


step "[2/8] bicep deploy (tables + dcr)"
cd "$REPO_DIR/infra/sentinel"
retry 3 5 az deployment group create -g "$DATA_RG" -f tables.bicep \
    -n tables-mvp -p workspaceName="$DATA_WS" >/dev/null
bold "  tables.bicep applied"
retry 3 5 az deployment group create -g "$DATA_RG" -f dcr.bicep \
    -n dcr-mvp -p workspaceName="$DATA_WS" >/dev/null
bold "  dcr.bicep applied"


step "[3/8] NSG rules (idempotent)"
declare -A PORT_RULES=(
    [c4i-rest]="1060:8200"
    [cyber-posture-rest]="1070:8300"
    [weapon-rest]="1080:8400"
    [ti-rest]="1090:8500"
    [auth-rest]="1100:8600"
)
for name in "${!PORT_RULES[@]}"; do
    val="${PORT_RULES[$name]}"
    prio="${val%%:*}"
    port="${val##*:}"
    if az network nsg rule show -g "$SIM_RG" --nsg-name "$NSG_NAME" -n "$name" >/dev/null 2>&1; then
        bold "  $name already exists"
    else
        az network nsg rule create -g "$SIM_RG" --nsg-name "$NSG_NAME" \
            -n "$name" --priority "$prio" \
            --access Allow --protocol Tcp \
            --source-address-prefixes "*" --source-port-ranges "*" \
            --destination-address-prefixes "*" --destination-port-ranges "$port" \
            >/dev/null
        bold "  $name created (port $port)"
    fi
done


step "[4/8] resolve VM FQDN + workspace guid"
FQDN="$(az deployment group show -g "$SIM_RG" -n "$SIM_DEPLOY" \
    --query properties.outputs.fqdn.value -o tsv)"
WORKSPACE_GUID="$(az monitor log-analytics workspace show -g "$DATA_RG" -n "$DATA_WS" \
    --query customerId -o tsv)"
bold "  FQDN:           $FQDN"
bold "  WORKSPACE_GUID: $WORKSPACE_GUID"


step "[5/8] vm: git pull + build + up -d + AMA restart"
ssh -o StrictHostKeyChecking=accept-new "azureuser@$FQDN" bash -se <<'EOF'
set -euo pipefail
cd /opt/uav-sim-env
sudo git pull
# Build everything; docker layer cache handles untouched services.
sudo docker compose build \
    telemetry-tap pgse-stub datalink-stats \
    weapon-stub ti-stub auth-stub \
    c4i-stub cyber-posture-stub mps-stub service-audit
sudo docker compose up -d --force-recreate \
    telemetry-tap pgse-stub datalink-stats \
    weapon-stub ti-stub auth-stub
sudo docker compose up -d c4i-stub cyber-posture-stub mps-stub service-audit
sudo systemctl restart azuremonitoragent
echo "vm-side deploy complete"
EOF


step "[6/8] per-service health checks (vm-internal localhost)"
for ep in "8000:/health" "8100:/health" "8200:/health" "8300:/health" "8400:/health" "8500:/health" "8600:/health"; do
    port="${ep%%:*}"
    path="${ep##*:}"
    ssh "azureuser@$FQDN" bash -c "
        for i in {1..60}; do
            code=\$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://localhost:${port}${path} || true)
            if [[ \"\$code\" =~ ^2 ]]; then echo ok\${port}=\${code}; exit 0; fi
            sleep 1
        done
        echo FAIL\${port}; exit 1
    " || warn "service on $port not healthy yet, continuing"
done


step "[7/8] fire test events"
fire "pgse-stub valid preflight"  "http://$FQDN:8000/preflight/check" '{
    "uav_id":"MPD-001",
    "image_hash":"sha256:0000000000000000000000000000000000000000000000000000000000000001",
    "sbom_components":["ardupilot/Plane-4.5"],
    "operator":"sgt.yang","serial":"MPD-AC-0001"
}'
fire "pgse-stub malicious preflight"  "http://$FQDN:8000/preflight/check" '{
    "uav_id":"MPD-001",
    "image_hash":"sha256:DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEF",
    "sbom_components":["unsigned/malicious-payload-v1"],
    "operator":"attacker","serial":"MPD-AC-0001"
}'

fire "pgse-stub battery cycle"        "http://$FQDN:8000/maintenance/battery/cycle" '{
    "uav_id":"MPD-001","battery_id":"BAT-001","cycle_count":42,
    "voltage_min":13.6,"voltage_max":16.8,"operator":"tech.han"
}'
fire "pgse-stub calibration"          "http://$FQDN:8000/maintenance/calibration" '{
    "uav_id":"MPD-001","component":"compass","operator":"tech.han","notes":"normal"
}'
fire "pgse-stub inspection sign"      "http://$FQDN:8000/maintenance/inspection/sign" '{
    "uav_id":"MPD-001","checklist_id":"PFC-2026-06-21","items_passed":18,"items_total":18,
    "operator":"tech.han"
}'

fire "mps-stub plan"                  "http://$FQDN:8100/plans" '{
    "uav_id":"MPD-001","planner":"lt.kim","callsign":"FALCON-1",
    "waypoints":[{"seq":0,"lat":37.5326,"lon":127.0246,"alt_m":30,"action":"navigate"}],
    "roe":"recon-only","payload_config":"EO_IR"
}'

fire "c4i-stub ATCIS order"           "http://$FQDN:8200/atcis/orders" '{
    "callsign":"FALCON-1","operation_name":"WHITE_TIGER","objective":"recon-north-bridge",
    "roe":"recon-only","area_lat":37.5410,"area_lon":127.0310,"area_radius_m":500,
    "target_priority":"HIGH","issued_by":"maj.cho"
}'
fire "c4i-stub MIMS target"           "http://$FQDN:8200/mims/targets" '{
    "lat":37.5410,"lon":127.0310,"classification":"HOSTILE","confidence_pct":78,
    "source":"sigint","reported_by":"hq-intel"
}'

fire "cyber-posture CT-2"             "http://$FQDN:8300/posture" '{
    "level":"CT-2","changed_by":"capt.park","reason":"intel-warning","source":"국정원"
}'
fire "cyber-posture CT-1"             "http://$FQDN:8300/posture" '{
    "level":"CT-1","changed_by":"col.lee","reason":"active-jamming","source":"사이버사"
}'

fire "weapon-stub safety ARMED"       "http://$FQDN:8400/weapon/safety" '{
    "state":"ARMED","operator":"sgt.yang"
}'
fire "weapon-stub lock"               "http://$FQDN:8400/weapon/lock" '{
    "target_id":"T-001","operator":"capt.park"
}'
fire "weapon-stub fire 2-person OK"   "http://$FQDN:8400/weapon/fire" '{
    "operator":"capt.park","target_id":"T-001"
}'
fire "weapon-stub fire 2-person VIOLATION" "http://$FQDN:8400/weapon/fire" '{
    "operator":"sgt.yang","target_id":"T-001"
}' || true

fire "ti-stub indicator (CVE)"        "http://$FQDN:8500/ti/indicators" '{
    "type":"cve","indicator":"CVE-2026-12345","severity":"CRITICAL",
    "confidence_pct":95,"source":"NVD",
    "description":"ArduPilot mavlink parser remote code execution"
}'
fire "ti-stub feed bulk"              "http://$FQDN:8500/ti/feeds" '{
    "feed_name":"CISA-KEV-2026-06",
    "indicators":[
        {"type":"hash","indicator":"sha256:dead...","severity":"HIGH","confidence_pct":80,"source":"CISA","description":"malicious-firmware-blob"},
        {"type":"ip","indicator":"185.220.101.42","severity":"MEDIUM","confidence_pct":65,"source":"AbuseIPDB","description":"tor-exit-known-bad"}
    ]
}'
fire "ti-stub posture recommendation" "http://$FQDN:8500/ti/posture-recommendation" '{
    "suggested_level":"CT-2","reason":"new-CVE-affects-fleet","confidence_pct":80
}'

fire "auth-stub login OK"             "http://$FQDN:8600/auth/login" '{
    "username":"capt.park","password":"uav-pw-3","client_ip":"10.0.0.42","user_agent":"qgc-desktop"
}'
fire "auth-stub login FAIL"           "http://$FQDN:8600/auth/login" '{
    "username":"capt.park","password":"wrong","client_ip":"10.0.0.99","user_agent":"unknown"
}' || true


step "[7/8] wait ${INGEST_WAIT_SEC}s for AMA to ship"
sleep "$INGEST_WAIT_SEC"


step "[8/8] KQL verify (per table)"
kql_one() {
    local title="$1" query="$2"
    bold "▶ $title"
    az monitor log-analytics query -w "$WORKSPACE_GUID" \
        --analytics-query "$query" --timespan PT24H -o jsonc 2>&1 | head -20
    hr
}

for tbl in UAVTelemetry_CL UAVPgse_CL UAVOperator_CL \
           UAVMissionEvent_CL UAVMissionPlan_CL UAVServiceAudit_CL \
           UAVDatalink_CL UAVC4I_CL UAVCyberPosture_CL \
           UAVWeapon_CL UAVThreatIntel_CL UAVOpAudit_CL \
           UAVFailsafe_CL UAVMavsec_CL UAVMaintenance_CL \
           UAVImagery_CL UAVConfigAudit_CL UAVResourceMetrics_CL \
           UAVDatalinkConn_CL ; do
    kql_one "$tbl (recent)" "$tbl | take 3"
done

bold "done ✅"
