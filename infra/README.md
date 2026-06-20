# infra — Azure deployment

Three-RG layout. Each Bicep is independently deployable and idempotent.

```
main.bicep        uav-sim-env VM   -> dah-sim-rg
data.bicep        Log Analytics + Sentinel -> dah-data-rg
soc.bicep         AKS + ACR        -> dah-soc-rg
cloud-init.yaml   VM bootstrap consumed by main.bicep
```

**왜 3-RG**: 수명주기 분리. 시뮬은 자유롭게 재배포, AKS는 해커톤 내내 유지, Log Analytics는 가장 오래 살아남는 데이터 저장소 → 각자 격리.

---

## 1. 사전 조건

- Azure CLI 2.55 이상 — `az --version`
- 구독 + 리소스 그룹 생성 권한
- SSH 공개키 (`~/.ssh/id_ed25519.pub` 또는 `id_rsa.pub`)
- 본인 공인 IP (NSG에 화이트리스트 등록용)

```bash
az login
az account set --subscription "<subscription-id-or-name>"
```

---

## 2. 배포

```bash
# 1) Resource group
RG=uav-sim-rg
LOCATION=koreacentral
az group create -n "$RG" -l "$LOCATION"

# 2) Parameters
MY_IP="$(curl -s ifconfig.me)/32"
PUBKEY="$(cat ~/.ssh/id_ed25519.pub)"

# 3) Deploy
cd infra
az deployment group create \
  -g "$RG" \
  -f main.bicep \
  -p adminPublicKey="$PUBKEY" \
  -p allowedSourceIp="$MY_IP"
```

배포 자체는 ~3분. 그러나 **VM 안에서 첫 Docker build는 약 30분** (ArduPilot 소스 컴파일 + QGC AppImage 압축 풀기 + Gazebo Garden 설치).

---

## 3. 출력값 확인

```bash
az deployment group show -g "$RG" -n main --query properties.outputs
```

예시 출력:
```json
{
  "publicIp":       { "value": "20.39.x.x" },
  "fqdn":           { "value": "uavsim-abc123.koreacentral.cloudapp.azure.com" },
  "sshCommand":     { "value": "ssh azureuser@uavsim-abc123.koreacentral.cloudapp.azure.com" },
  "novncUrl":       { "value": "http://uavsim-abc123.koreacentral.cloudapp.azure.com:8080/vnc.html" },
  "pgseDocsUrl":    { "value": "http://uavsim-abc123.koreacentral.cloudapp.azure.com:8000/docs" }
}
```

---

## 4. 부트스트랩 진행 상황 보기

```bash
ssh azureuser@<fqdn>
sudo journalctl -u uav-sim-env.service -f
# 또는
sudo docker compose -f /opt/uav-sim-env/docker-compose.yml ps
```

`Active: active (exited)` 가 뜨면 `docker compose ps`에서 5개 서비스 모두 Up 상태여야 한다.

---

## 5. 노출 포트 (NSG에 본인 IP만 허용)

| 포트 | 프로토콜 | 용도 |
|---|---|---|
| 22 | TCP | SSH |
| 8080 | TCP | noVNC (브라우저로 QGroundControl) |
| 5790 | TCP | mavlink-router 평문 채널 (A4 attack surface) |
| 8000 | TCP | pgse-stub REST + `/docs` Swagger UI |
| 14550 | UDP | MAVLink router GCS endpoint |
| 14552 | UDP | telemetry tap endpoint |

---

## 6. 재배포 / 업데이트

`main` 브랜치에 새로 push한 변경을 VM에 반영:

```bash
ssh azureuser@<fqdn> 'sudo systemctl restart uav-sim-env.service'
```

systemd 유닛이 `git pull` → `docker compose build` → `up -d` 를 다시 돈다.

---

## 7. 정리

```bash
az group delete -n "$RG" --yes --no-wait
```

리소스 그룹 통째로 삭제 → VM, 디스크, NSG, PIP 모두 정리. 비용은 D4s_v5 Pay-As-You-Go 기준 시간당 약 ₩300, 월 ₩200,000 안팎. Spot으로 옮기면 1/3 수준.

---

## 8. 한계와 다음 단계

- VM 단일 → 가용성 SLA 없음. 시연/PoC 용도.
- Docker build를 VM 안에서 수행 → 첫 부팅이 느림. ACR 사전 푸시 (`soc.bicep`로 만든 레지스트리) + `docker compose pull` 로 단축 가능.
- Sentinel ingest 회선은 별도 작업 — Azure Monitor Agent를 telemetry-tap stdout에 붙이고 DCR(Data Collection Rule)을 정의해야 한다.

---

## 9. data.bicep — Log Analytics + Sentinel

```bash
az group create -n dah-data-rg -l koreacentral
az deployment group create -g dah-data-rg -f data.bicep -n data-mvp

# 출력값 (workspaceId 등 다른 RG에서 참조)
az deployment group show -g dah-data-rg -n data-mvp --query properties.outputs
```

기본값:
- 워크스페이스 이름 `dah-data-law`
- 보존기간 30일
- 일일 인제스트 캡 1 GB (비용 안전선)
- Microsoft Sentinel 자동 활성화

재배포는 같은 명령 그대로 다시 실행 (no-op). 보존기간만 늘리고 싶으면:
```bash
az deployment group create -g dah-data-rg -f data.bicep -n data-mvp -p retentionInDays=90
```

---

## 10. soc.bicep — AKS + ACR

```bash
# 1) Log Analytics workspace id 가져오기
WORKSPACE_ID=$(az deployment group show -g dah-data-rg -n data-mvp \
  --query properties.outputs.workspaceId.value -o tsv)

# 2) RG 만들고 배포
az group create -n dah-soc-rg -l koreacentral
az deployment group create -g dah-soc-rg -f soc.bicep -n soc-mvp \
  -p workspaceId="$WORKSPACE_ID"

# 3) kubeconfig 가져오기
az aks get-credentials -g dah-soc-rg -n dah-soc-aks --overwrite-existing
kubectl get nodes

# 4) kagent 설치
helm install kagent oci://ghcr.io/kagent-dev/kagent \
  --namespace kagent --create-namespace
```

기본값:
- AKS `dah-soc-aks`, Kubernetes 1.30, system 노드 2× D4s_v5
- ACR Basic SKU, 이름은 `dahsocacr<hash>` 형태로 자동 유니크
- AKS kubelet 신원이 ACR `AcrPull` 자동 부여 → `ImagePullSecrets` 불필요
- `workspaceId` 전달 시 Container Insights 자동 활성화 → AKS 로그가 Sentinel과 같은 워크스페이스로

재배포 시 노드 수만 조정:
```bash
az deployment group create -g dah-soc-rg -f soc.bicep -n soc-mvp -p systemNodeCount=3
```

---

## 11. 전체 재배포 한 번에 (필요 시)

```bash
# 1) 데이터 레이어 먼저
az deployment group create -g dah-data-rg -f data.bicep -n data-mvp

# 2) SOC (데이터 레이어 출력 의존)
WORKSPACE_ID=$(az deployment group show -g dah-data-rg -n data-mvp \
  --query properties.outputs.workspaceId.value -o tsv)
az deployment group create -g dah-soc-rg -f soc.bicep -n soc-mvp \
  -p workspaceId="$WORKSPACE_ID"

# 3) 시뮬 (독립)
az deployment group create -g dah-sim-rg -f main.bicep -n uavsim-mvp \
  -p adminPublicKey="$(cat ~/.ssh/id_ed25519.pub)" \
  -p allowedSourceIp="$(curl -s ifconfig.me)/32"
```
