#!/usr/bin/env bash
# satcom-ingest.sh — KUS-FS SATCOM/SAR ingest 소스를 라이브로 연결 + 검증.
#
# datalink-satcom (→ UAVSatcomLink_CL) 와 sar-stub (→ UAVSarPayload_CL) 를 VM 에서
# 띄우고, ext2 DCR 을 VM 에 연결하여 데이터가 Sentinel 까지 흐르는지 확인한다.
#
# 전제: 신규 컴포넌트(datalink-satcom/, sar-stub/, compose 변경)가 origin/main 에
#       push 되어 있어야 한다 — VM 은 git pull 로 받기 때문.
#
# 단계:
#   1) preflight (작업트리 clean + push 됨 + az 로그인)
#   2) bicep: tables + dcr-ext2 적용, vm-monitoring 으로 ext2 DCRA 연결 (멱등)
#   3) ssh vm: git pull → datalink-satcom·sar-stub build+up → AMA 재시작
#   4) S3 주입 + SAR 캡처 이벤트 발생 (VM 내부 localhost)
#   5) AMA ingest 대기
#   6) KQL 검증 (UAVSatcomLink_CL + UAVSarPayload_CL)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SIM_RG="dah-sim-rg"
DATA_RG="dah-data-rg"
SIM_DEPLOY="uavsim-mvp"
DATA_WS="dah-data-law"
INGEST_WAIT_SEC="${INGEST_WAIT_SEC:-300}"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
step() { bold "▶ $*"; }
fail() { printf '\033[31m✘ %s\033[0m\n' "$*" >&2; exit 1; }

step "[1/6] preflight"
cd "$REPO_DIR"
if [[ -n "$(git status --porcelain)" ]]; then
    git status --short
    fail "작업트리 dirty — 'git add -A && git commit && git push' 먼저 (VM 은 git pull 로 받음)"
fi
git fetch --quiet origin
if [[ "$(git rev-parse HEAD)" != "$(git rev-parse '@{u}')" ]]; then
    fail "local != origin — 'git push' 먼저."
fi
command -v az  >/dev/null || fail "az CLI 없음"
command -v jq  >/dev/null || fail "jq 없음"
command -v ssh >/dev/null || fail "ssh 없음"
az account show >/dev/null || fail "az 로그인 필요 (az login)"

step "[2/6] bicep: dcr-ext2 적용 + ext2 DCRA 연결 (멱등)"
cd "$REPO_DIR/infra/sentinel"
az deployment group create -g "$DATA_RG" -f tables.bicep -n tables-mvp \
    -p workspaceName="$DATA_WS" >/dev/null
az deployment group create -g "$DATA_RG" -f dcr-ext2.bicep -n dcr-ext2-mvp \
    -p workspaceName="$DATA_WS" >/dev/null
# DCR id 들은 이름으로 조회(배포명에 비의존, 더 견고).
DCR_PRIMARY_ID="$(az monitor data-collection rule show -g "$DATA_RG" -n dah-data-uav-dcr        --query id -o tsv)"
DCR_EXTRAS_ID="$(az monitor data-collection rule show  -g "$DATA_RG" -n dah-data-uav-dcr-extras --query id -o tsv)"
DCR_EXT2_ID="$(az monitor data-collection rule show    -g "$DATA_RG" -n dah-data-uav-dcr-ext2   --query id -o tsv)"
[[ -n "$DCR_EXT2_ID" ]] || fail "dah-data-uav-dcr-ext2 DCR 을 못 찾음"
bold "  ext2 DCR: $DCR_EXT2_ID"
az deployment group create -g "$SIM_RG" -f vm-monitoring.bicep -n vm-mon-mvp \
    -p dcrId="$DCR_PRIMARY_ID" -p dcrIdExtras="$DCR_EXTRAS_ID" -p dcrIdExt2="$DCR_EXT2_ID" >/dev/null
bold "  ext2 DCRA 연결됨 (AMA 가 satcom.ndjson/sar.ndjson 타일)"

step "[3/6] VM 배포 (git pull → build+up → AMA 재시작)"
FQDN="$(az deployment group show -g "$SIM_RG" -n "$SIM_DEPLOY" \
    --query properties.outputs.fqdn.value -o tsv)"
WORKSPACE_GUID="$(az monitor log-analytics workspace show -g "$DATA_RG" -n "$DATA_WS" \
    --query customerId -o tsv)"
bold "  FQDN: $FQDN"
ssh -o StrictHostKeyChecking=accept-new "azureuser@$FQDN" bash -se <<'EOF'
set -euo pipefail
cd /opt/uav-sim-env
sudo git pull
sudo docker compose build datalink-satcom sar-stub
sudo docker compose up -d datalink-satcom sar-stub
sudo systemctl restart azuremonitoragent
echo "vm-side deploy complete"
EOF

step "[4/6] S3 주입 + SAR 캡처 (VM 내부 localhost)"
# datalink-satcom 은 5초마다 정상 레코드를 자동 emit → 표가 기본으로 채워짐.
# 여기서 S3(무결성/하이재킹/재밍) + SAR 프레임을 추가 발생.
ssh "azureuser@$FQDN" bash -se <<'EOF'
set -uo pipefail
post() { curl -sS --max-time 5 -X POST "$1" -H 'content-type: application/json' -d "$2" || true; echo; }
post http://localhost:8800/satcom/inject '{"type":"integrity","duration_sec":30}'
post http://localhost:8800/satcom/inject '{"type":"hijack"}'
post http://localhost:8800/satcom/inject '{"type":"jam","duration_sec":20}'
post http://localhost:8700/sar/capture  '{"uav_id":"MUAV-001","target_lat":38.01,"target_lon":127.20,"sensor_mode":"spot","resolution":"0.3m"}'
post http://localhost:8700/sar/capture  '{"uav_id":"MUAV-001","target_lat":38.05,"target_lon":127.30,"sensor_mode":"gmti"}'
echo "events fired"
EOF

step "[5/6] AMA ingest 대기 (${INGEST_WAIT_SEC}s)"
sleep "$INGEST_WAIT_SEC"

step "[6/6] KQL 검증"
kql() { bold "▶ $1"; az monitor log-analytics query -w "$WORKSPACE_GUID" \
    --analytics-query "$2" --timespan PT1H -o jsonc | head -40; }
kql "UAVSatcomLink_CL (recent)" \
    "UAVSatcomLink_CL | project TimeGenerated, UAVId, LinkId, SessionId, Seq, IntegrityStatus, RttMs, JamIndicator | order by TimeGenerated desc | take 10"
kql "UAVSatcomLink_CL (S3 만)" \
    "UAVSatcomLink_CL | where IntegrityStatus != 'ok' or JamIndicator > 0.5 | order by TimeGenerated desc | take 10"
kql "UAVSarPayload_CL (recent)" \
    "UAVSarPayload_CL | project TimeGenerated, UAVId, FrameId, SensorMode, Resolution, SizeBytes | order by TimeGenerated desc | take 10"

bold "done ✅ — UAVSatcomLink_CL 에 행이 보이면 S3 가 Sentinel 까지 흐르는 것."
