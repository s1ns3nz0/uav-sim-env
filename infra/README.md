# infra — Azure deployment

Single-VM deployment of `uav-sim-env` on Azure Korea Central, defined in Bicep.

```
main.bicep        VM + VNet + NSG + PIP + NIC (resource-group scope)
cloud-init.yaml   First-boot bootstrap (Docker install, repo clone, systemd unit)
```

The companion SOC platform (`pollack-ai`, LangGraph + kagent) runs on AKS in a separate deployment; this VM is intentionally simple because the simulation stack is UDP-heavy, GUI-heavy, and stateful, which all map poorly onto Kubernetes.

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
- Docker build를 VM 안에서 수행 → 첫 부팅이 느림. Phase 2에서 Azure Container Registry로 이미지 사전 푸시 + `docker compose pull` 만 수행하도록 변경 권장.
- Sentinel ingest 회선은 별도 작업 — Azure Monitor Agent를 telemetry-tap stdout에 붙이고 DCR(Data Collection Rule)을 정의해야 한다.
