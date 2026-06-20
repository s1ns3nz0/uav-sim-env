#!/usr/bin/env bash
# smoke-ingest.sh — end-to-end smoke test for the UAV SOC ingest pipeline.
#
# Generates one event in each table source and reports the file + KQL
# state. Safe to re-run; every call is idempotent or generates a new record.
#
# Requires:
#   az CLI logged in (correct subscription)
#   ssh access to uavsim-vm (key already loaded)
#   jq
#
# Usage:
#   ./scripts/smoke-ingest.sh                       # run everything
#   ./scripts/smoke-ingest.sh kql                   # KQL checks only
#   ./scripts/smoke-ingest.sh fire                  # event generation only

set -euo pipefail

SIM_RG="dah-sim-rg"
DATA_RG="dah-data-rg"
SIM_DEPLOY="uavsim-mvp"
DATA_WS="dah-data-law"
SUBCMD="${1:-all}"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
hr()   { printf -- '─%.0s' {1..72}; printf '\n'; }
step() { bold "▶ $*"; }

resolve_fqdn() {
    az deployment group show -g "$SIM_RG" -n "$SIM_DEPLOY" \
        --query properties.outputs.fqdn.value -o tsv
}

resolve_workspace_guid() {
    az monitor log-analytics workspace show -g "$DATA_RG" -n "$DATA_WS" \
        --query customerId -o tsv
}

FQDN="${FQDN:-$(resolve_fqdn)}"
WORKSPACE_GUID="${WORKSPACE_GUID:-$(resolve_workspace_guid)}"
bold "FQDN:           $FQDN"
bold "WORKSPACE_GUID: $WORKSPACE_GUID"
hr

fire_pgse() {
    step "[pgse-stub] valid preflight"
    curl -sS -X POST "http://$FQDN:8000/preflight/check" \
        -H "Content-Type: application/json" \
        -d '{
            "uav_id":"MPD-001",
            "image_hash":"sha256:0000000000000000000000000000000000000000000000000000000000000001",
            "sbom_components":["ardupilot/Plane-4.5","mavlink/c-library/v2"],
            "operator":"sgt.yang",
            "serial":"MPD-AC-0001"
        }' | jq -c '.uav_id, .passed'

    step "[pgse-stub] malicious preflight (hash + sbom)"
    curl -sS -X POST "http://$FQDN:8000/preflight/check" \
        -H "Content-Type: application/json" \
        -d '{
            "uav_id":"MPD-001",
            "image_hash":"sha256:DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEF",
            "sbom_components":["unsigned/malicious-payload-v1"],
            "operator":"attacker",
            "serial":"MPD-AC-0001"
        }' | jq -c '.uav_id, .passed, .sbom_forbidden_components'
}

fire_mps_cycle() {
    step "[mps-stub] create -> approve -> release (normal cycle)"
    local plan_id
    plan_id=$(curl -sS -X POST "http://$FQDN:8100/plans" \
        -H "Content-Type: application/json" \
        -d '{
            "uav_id":"MPD-001",
            "planner":"lt.kim",
            "callsign":"FALCON-1",
            "waypoints":[
                {"seq":0,"lat":37.5326,"lon":127.0246,"alt_m":30,"action":"navigate"},
                {"seq":1,"lat":37.5390,"lon":127.0290,"alt_m":120,"action":"loiter"}
            ],
            "roe":"recon-only",
            "payload_config":"EO_IR"
        }' | jq -r .plan_id)
    bold "  plan_id: $plan_id"

    curl -sS -X POST "http://$FQDN:8100/plans/$plan_id/approve" \
        -H "Content-Type: application/json" \
        -d '{"approver":"capt.park","comment":"ROE confirmed"}' | jq -c '.status'

    curl -sS -X POST "http://$FQDN:8100/plans/$plan_id/release" \
        -H "Content-Type: application/json" \
        -d '{"released_by":"capt.park"}' | jq -c '.status'

    step "[mps-stub] two-person rule violation"
    local plan2
    plan2=$(curl -sS -X POST "http://$FQDN:8100/plans" \
        -H "Content-Type: application/json" \
        -d '{
            "uav_id":"MPD-001",
            "planner":"lt.kim",
            "callsign":"FALCON-2",
            "waypoints":[
                {"seq":0,"lat":37.5326,"lon":127.0246,"alt_m":30,"action":"navigate"}
            ],
            "roe":"engage-confirmed-hostile",
            "payload_config":"STRIKE_870G"
        }' | jq -r .plan_id)
    bold "  plan_id: $plan2"

    curl -sS -X POST "http://$FQDN:8100/plans/$plan2/approve" \
        -H "Content-Type: application/json" \
        -d '{"approver":"lt.kim","comment":"self-approve attempt"}' | jq -c '.detail // .status'

    step "[mps-stub] release-before-approval violation"
    local plan3
    plan3=$(curl -sS -X POST "http://$FQDN:8100/plans" \
        -H "Content-Type: application/json" \
        -d '{
            "uav_id":"MPD-001",
            "planner":"lt.kim",
            "callsign":"FALCON-3",
            "waypoints":[
                {"seq":0,"lat":37.5326,"lon":127.0246,"alt_m":30,"action":"navigate"}
            ],
            "roe":"recon-only",
            "payload_config":"EO_IR"
        }' | jq -r .plan_id)
    bold "  plan_id: $plan3"

    curl -sS -X POST "http://$FQDN:8100/plans/$plan3/release" \
        -H "Content-Type: application/json" \
        -d '{"released_by":"capt.park"}' | jq -c '.detail // .status'
}

fire_service_audit() {
    step "[service-audit] bounce av-mpd to generate container lifecycle events"
    ssh -o StrictHostKeyChecking=accept-new "azureuser@$FQDN" \
        'sudo docker restart uav-av-mpd >/dev/null && echo "av-mpd restarted"'
}

show_files() {
    step "log file inventory on uavsim-vm"
    ssh "azureuser@$FQDN" 'sudo ls -la /var/log/uav-sim-env/'
}

kql_one() {
    local title="$1" query="$2"
    step "$title"
    az monitor log-analytics query -w "$WORKSPACE_GUID" \
        --analytics-query "$query" --timespan PT24H -o jsonc | head -40
    hr
}

run_kql() {
    kql_one "UAVTelemetry_CL (recent count)" \
        "UAVTelemetry_CL | where TimeGenerated > ago(15m) | summarize Count = count() by MsgType | top 10 by Count"
    kql_one "UAVPgse_CL (recent)" \
        "UAVPgse_CL | where TimeGenerated > ago(15m) | project TimeGenerated, EventType, UAVId, Operator, HashMatch, Passed, FailReason | order by TimeGenerated desc | take 10"
    kql_one "UAVOperator_CL (recent)" \
        "UAVOperator_CL | where TimeGenerated > ago(15m) | project TimeGenerated, UAVId, ActionName, MsgType, Command | order by TimeGenerated desc | take 10"
    kql_one "UAVMissionEvent_CL (recent)" \
        "UAVMissionEvent_CL | where TimeGenerated > ago(15m) | project TimeGenerated, UAVId, EventName, MsgType, Seq, Lat, Lon | order by TimeGenerated desc | take 10"
    kql_one "UAVMissionPlan_CL (recent)" \
        "UAVMissionPlan_CL | where TimeGenerated > ago(15m) | project TimeGenerated, EventType, PlanId, Planner, Approver, Status, FailReason | order by TimeGenerated desc | take 20"
    kql_one "UAVServiceAudit_CL (recent)" \
        "UAVServiceAudit_CL | where TimeGenerated > ago(15m) | project TimeGenerated, EventType, Action, ContainerName, ServiceLabel, ExitCode | order by TimeGenerated desc | take 20"
}

case "$SUBCMD" in
    all)
        fire_pgse
        fire_mps_cycle
        fire_service_audit
        show_files
        bold "waiting 5 minutes for AMA to ship..."
        sleep 300
        run_kql
        ;;
    fire)
        fire_pgse
        fire_mps_cycle
        fire_service_audit
        show_files
        ;;
    kql)
        run_kql
        ;;
    *)
        echo "Usage: $0 {all|fire|kql}" >&2
        exit 2
        ;;
esac

bold "done ✅"
