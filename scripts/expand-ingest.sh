#!/usr/bin/env bash
# expand-ingest.sh — deploy + smoke 3 new ingest sources.
#
# Adds UAVDatalink_CL, UAVC4I_CL, UAVCyberPosture_CL on top of the existing
# six-table pipeline. Idempotent: re-running is a no-op for resources that
# already match the desired state.
#
# Steps:
#   1) git pull (refuse if working tree dirty)
#   2) bicep deploy tables.bicep + dcr.bicep -> dah-data-rg
#   3) NSG rules for 8200 (c4i), 8300 (cyber-posture) -> dah-sim-rg
#   4) ssh to uavsim-vm: git pull, docker compose build + recreate new services
#   5) restart AMA so it picks up the new logFiles datasources
#   6) fire events against c4i-stub + cyber-posture-stub
#   7) wait 5 minutes
#   8) KQL verify new + old tables
#
# Usage: ./scripts/expand-ingest.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SIM_RG="dah-sim-rg"
DATA_RG="dah-data-rg"
SIM_DEPLOY="uavsim-mvp"
DATA_WS="dah-data-law"
NSG_NAME="uavsim-nsg"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
hr()   { printf -- '─%.0s' {1..72}; printf '\n'; }
step() { bold "▶ $*"; }

step "[1/8] preflight: working tree clean?"
cd "$REPO_DIR"
if [[ -n "$(git status --porcelain)" ]]; then
    echo "✘ working tree dirty. commit or stash first." >&2
    git status --short >&2
    exit 1
fi
git pull --ff-only

step "[2/8] bicep deploy: tables.bicep + dcr.bicep"
cd "$REPO_DIR/infra/sentinel"
az deployment group create -g "$DATA_RG" -f tables.bicep -n tables-mvp \
    -p workspaceName="$DATA_WS" >/dev/null
bold "  tables.bicep applied"
az deployment group create -g "$DATA_RG" -f dcr.bicep -n dcr-mvp \
    -p workspaceName="$DATA_WS" >/dev/null
bold "  dcr.bicep applied"

step "[3/8] NSG rules: 8200 c4i, 8300 cyber-posture"
for port_rule in "c4i:1060:8200" "cyber-posture:1070:8300"; do
    name="${port_rule%%:*}"
    rest="${port_rule#*:}"
    prio="${rest%%:*}"
    port="${rest##*:}"
    az network nsg rule create -g "$SIM_RG" --nsg-name "$NSG_NAME" \
        -n "${name}-rest" --priority "$prio" \
        --access Allow --protocol Tcp \
        --source-address-prefixes "*" --source-port-ranges "*" \
        --destination-address-prefixes "*" --destination-port-ranges "$port" \
        >/dev/null 2>&1 || bold "  rule ${name}-rest already exists, skipping"
    bold "  NSG ${name} port ${port} open"
done

step "[4/8] resolve VM fqdn + workspace guid"
FQDN="$(az deployment group show -g "$SIM_RG" -n "$SIM_DEPLOY" \
    --query properties.outputs.fqdn.value -o tsv)"
WORKSPACE_GUID="$(az monitor log-analytics workspace show -g "$DATA_RG" -n "$DATA_WS" \
    --query customerId -o tsv)"
bold "  FQDN:           $FQDN"
bold "  WORKSPACE_GUID: $WORKSPACE_GUID"

step "[5/8] vm: git pull + build new services + recreate + AMA restart"
ssh -o StrictHostKeyChecking=accept-new "azureuser@$FQDN" bash -s <<'EOF'
set -euo pipefail
cd /opt/uav-sim-env
sudo git pull
sudo docker compose build datalink-stats c4i-stub cyber-posture-stub
sudo docker compose up -d datalink-stats c4i-stub cyber-posture-stub
sudo systemctl restart azuremonitoragent
echo "vm-side deploy complete"
EOF

step "[6/8] fire events against new services"
bold "[c4i-stub] ATCIS operation order"
curl -sS -X POST "http://$FQDN:8200/atcis/orders" \
    -H "Content-Type: application/json" \
    -d '{
        "callsign":"FALCON-1",
        "operation_name":"WHITE_TIGER",
        "objective":"recon-north-bridge",
        "roe":"recon-only",
        "area_lat":37.5410,
        "area_lon":127.0310,
        "area_radius_m":500,
        "target_priority":"HIGH",
        "issued_by":"maj.cho"
    }' | jq -c '.order_id, .roe'

bold "[c4i-stub] MIMS target intel"
curl -sS -X POST "http://$FQDN:8200/mims/targets" \
    -H "Content-Type: application/json" \
    -d '{
        "lat":37.5410,
        "lon":127.0310,
        "classification":"HOSTILE",
        "confidence_pct":78,
        "source":"sigint",
        "reported_by":"hq-intel"
    }' | jq -c '.target_id, .classification'

bold "[c4i-stub] friendly position"
curl -sS -X POST "http://$FQDN:8200/atcis/friendly-positions" \
    -H "Content-Type: application/json" \
    -d '{
        "unit_callsign":"RAVEN-3",
        "lat":37.5380,
        "lon":127.0290,
        "alt_m":50
    }' | jq -c '.unit_callsign, .lat, .lon'

bold "[cyber-posture-stub] CT-3 -> CT-2 transition"
curl -sS -X POST "http://$FQDN:8300/posture" \
    -H "Content-Type: application/json" \
    -d '{
        "level":"CT-2",
        "changed_by":"capt.park",
        "reason":"intel-warning-2026-06-21",
        "source":"국정원"
    }' | jq -c '.level, .changed_by'

bold "[cyber-posture-stub] CT-2 -> CT-1 escalation"
curl -sS -X POST "http://$FQDN:8300/posture" \
    -H "Content-Type: application/json" \
    -d '{
        "level":"CT-1",
        "changed_by":"col.lee",
        "reason":"active-jamming-detected",
        "source":"사이버사"
    }' | jq -c '.level, .changed_by'

step "[7/8] wait 5 minutes for AMA to ship"
sleep 300

step "[8/8] KQL verify"
kql_one() {
    local title="$1" query="$2"
    bold "▶ $title"
    az monitor log-analytics query -w "$WORKSPACE_GUID" \
        --analytics-query "$query" --timespan PT24H -o jsonc | head -40
    hr
}

kql_one "UAVDatalink_CL (recent)" \
    "UAVDatalink_CL | take 5"
kql_one "UAVC4I_CL (recent)" \
    "UAVC4I_CL | project TimeGenerated, EventType, OrderId, Roe, Classification, ConfidencePct, UnitCallsign | order by TimeGenerated desc | take 10"
kql_one "UAVCyberPosture_CL (recent)" \
    "UAVCyberPosture_CL | project TimeGenerated, EventType, PreviousLevel, Level, ChangedBy, Reason | order by TimeGenerated desc | take 10"

bold "done ✅"
