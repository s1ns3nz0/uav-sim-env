#!/usr/bin/env bash
#
# deploy_mps_mvp.sh
# UAV AI SOC — MPS(Mission Planning Service) MVP 배포 + 검증 원샷 스크립트
#
# 흐름:
#   1) 수신 측 준비   : 테이블 3개 + DCR(stream/datasource/dataflow) 배포
#   2) 송신 측 준비   : VM에서 컨테이너 재빌드/재시작 + AMA 재시작
#   3) 검증           : MPS 워크플로우 한 사이클(정상 + 위반) 호출
#   4) KQL 확인       : 5분 대기 후 3개 테이블 조회
#
# 사용법:  ./deploy_mps_mvp.sh
#
set -euo pipefail

# ─────────────────────────────────────────────────────────────
# 0. 설정값 (환경에 맞게 수정)
# ─────────────────────────────────────────────────────────────
DATA_RG="dah-data-rg"          # 데이터 평면 리소스 그룹 (LAW/DCR/테이블)
SIM_RG="dah-sim-rg"            # 시뮬레이션 리소스 그룹 (드론 VM)
WORKSPACE_NAME="dah-data-law"  # Log Analytics Workspace 이름
VM_DEPLOY_NAME="uavsim-mvp"    # VM 배포 이름 (FQDN 출력값 보유)
SSH_USER="azureuser"
INFRA_DIR="${HOME}/uav-sim-env/infra/sentinel"
MPS_PORT="8100"
WAIT_SECONDS=300               # KQL 조회 전 인제스트 대기(초)

log() { printf '\n\033[1;36m▶ %s\033[0m\n' "$*"; }

cd "${INFRA_DIR}"

# ─────────────────────────────────────────────────────────────
# 1. 수신 측: 테이블 3개 + DCR 배포 (각 1~2분)
# ─────────────────────────────────────────────────────────────
log "[1/4] 테이블 3개 배포 (tables.bicep)"
az deployment group create -g "${DATA_RG}" -f tables.bicep -n tables-mvp \
  -p workspaceName="${WORKSPACE_NAME}"

log "[1/4] DCR stream/datasource/dataflow 배포 (dcr.bicep)"
az deployment group create -g "${DATA_RG}" -f dcr.bicep -n dcr-mvp \
  -p workspaceName="${WORKSPACE_NAME}"

# ─────────────────────────────────────────────────────────────
# 2. 송신 측: VM 갱신 (telemetry-tap 재빌드 + 새 서비스 2개) + AMA 재시작
# ─────────────────────────────────────────────────────────────
log "[2/4] VM FQDN 조회"
FQDN=$(az deployment group show -g "${SIM_RG}" -n "${VM_DEPLOY_NAME}" \
  --query properties.outputs.fqdn.value -o tsv)
echo "FQDN = ${FQDN}"

log "[2/4] 컨테이너 재빌드 + 기동 (telemetry-tap / service-audit / mps-stub)"
ssh "${SSH_USER}@${FQDN}" "
  set -e
  cd /opt/uav-sim-env
  sudo git pull
  sudo docker compose build telemetry-tap service-audit mps-stub
  sudo docker compose up -d --force-recreate telemetry-tap
  sudo docker compose up -d service-audit mps-stub
"

log "[2/4] AMA(Azure Monitor Agent) 재시작 — 새 DCR 적용"
ssh "${SSH_USER}@${FQDN}" 'sudo systemctl restart azuremonitoragent'

log "[2/4] 로그 파일 생성 확인 (mission/service-audit/mps.ndjson 보여야 정상)"
ssh "${SSH_USER}@${FQDN}" 'sudo ls -la /var/log/uav-sim-env/'

# ─────────────────────────────────────────────────────────────
# 3. 검증: MPS 워크플로우 한 사이클 (정상 경로 + 위반 시도)
# ─────────────────────────────────────────────────────────────
log "[3/4] 정상 계획 생성"
PLAN=$(curl -s -X POST "http://${FQDN}:${MPS_PORT}/plans" \
  -H "Content-Type: application/json" \
  -d '{
    "uav_id":"MPD-001","planner":"lt.kim","callsign":"FALCON-1",
    "waypoints":[
      {"seq":0,"lat":37.5326,"lon":127.0246,"alt_m":30,"action":"navigate"},
      {"seq":1,"lat":37.5390,"lon":127.0290,"alt_m":120,"action":"loiter"}
    ],
    "roe":"recon-only","payload_config":"EO_IR"
  }' | jq -r '.plan_id')
echo "Plan: ${PLAN}"

log "[3/4] 승인 (계획자 != 승인자: capt.park)"
curl -s -X POST "http://${FQDN}:${MPS_PORT}/plans/${PLAN}/approve" \
  -H "Content-Type: application/json" \
  -d '{"approver":"capt.park","comment":"ROE checked"}'
echo

log "[3/4] 릴리즈"
curl -s -X POST "http://${FQDN}:${MPS_PORT}/plans/${PLAN}/release" \
  -H "Content-Type: application/json" \
  -d '{"released_by":"capt.park"}'
echo

log "[3/4] 위반 시도 — 같은 사람이 계획+승인 (403 + 위반 이벤트 기대)"
PLAN2=$(curl -s -X POST "http://${FQDN}:${MPS_PORT}/plans" \
  -H "Content-Type: application/json" \
  -d '{
    "uav_id":"MPD-001","planner":"lt.kim","callsign":"FALCON-2",
    "waypoints":[
      {"seq":0,"lat":37.5326,"lon":127.0246,"alt_m":30,"action":"navigate"}
    ],
    "roe":"engage-confirmed-hostile","payload_config":"STRIKE_870G"
  }' | jq -r '.plan_id')
echo "Plan2: ${PLAN2}"

# self-approve: 403 예상이므로 실패해도 스크립트 중단하지 않도록 처리
curl -s -o /dev/null -w "self-approve HTTP status: %{http_code}\n" \
  -X POST "http://${FQDN}:${MPS_PORT}/plans/${PLAN2}/approve" \
  -H "Content-Type: application/json" \
  -d '{"approver":"lt.kim","comment":"self-approve attempt"}' || true

# ─────────────────────────────────────────────────────────────
# 4. KQL 검증: 인제스트 대기 후 3개 테이블 조회
# ─────────────────────────────────────────────────────────────
log "[4/4] 인제스트 대기 (${WAIT_SECONDS}초)"
sleep "${WAIT_SECONDS}"

log "[4/4] Workspace GUID(customerId) 조회"
WORKSPACE_GUID=$(az monitor log-analytics workspace show \
  -g "${DATA_RG}" -n "${WORKSPACE_NAME}" --query customerId -o tsv)
echo "Workspace GUID = ${WORKSPACE_GUID}"

log "[4/4] UAVMissionEvent_CL"
az monitor log-analytics query -w "${WORKSPACE_GUID}" \
  --analytics-query "UAVMissionEvent_CL | take 5" --timespan PT24H -o jsonc

log "[4/4] UAVServiceAudit_CL"
az monitor log-analytics query -w "${WORKSPACE_GUID}" \
  --analytics-query "UAVServiceAudit_CL | take 5" --timespan PT24H -o jsonc

log "[4/4] UAVMissionPlan_CL"
az monitor log-analytics query -w "${WORKSPACE_GUID}" \
  --analytics-query "UAVMissionPlan_CL | take 10" --timespan PT24H -o jsonc

log "완료 ✅  — 위 결과에 정상/위반 이벤트가 보이면 파이프라인 정상 동작"
