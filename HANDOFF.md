# HANDOFF → Claude Code

이 문서는 진행 중인 작업을 Claude Code가 이어받기 위한 **컨텍스트 + 현재 블로커 + 잔여 로드맵**이다.
바로 다음 작업(권장): **mission-planner 페이지로 9 stub HTTP 트래픽 자동화** (UAVC4I/MissionPlan/Weapon/Pgse/Maintenance/ThreatIntel/OpAudit/SarPayload/CyberPosture). 인프라(파이프) + SITL 트래픽은 끝, VM 폐기 완료.

---

## 0. 한 줄 요약

LIG D&A 해커톤 UAV SOC 시뮬을 **단일 VM → AKS(GitOps/Helm/ArgoCD)** 로 이전 완료. 도메인·데이터패스·**Sentinel 17-stream 일원화**·HTTPS(`https://sim.pollak.store/vnc.html` HTTP/2 200) 다 동작. **VM 폐기됨 (deallocated, disk 유지)**. 라이브 트래픽 = QGC noVNC 에서 SITL 비행 → telemetry-tap 7 + datalink-satcom 1 stream.

## 1. 리소스 식별자 (전부 koreacentral)

| 항목 | 값 |
|---|---|
| Subscription | `b7acdba2-f2d6-4ff5-a059-008b20432f79` |
| RG: 시뮬+VM | `dah-sim-rg` |
| RG: Sentinel/LA | `dah-data-rg` |
| RG: SOC(kagent) | `dah-soc-rg` |
| RG: DNS 존 | `dah-shared-rg` (zone `pollak.store`) |
| AKS (시뮬) | `dah-sim-aks` / node RG `dah-sim-rg-aks-nodes` / nodepools `system`,`sitl`,`satcom`(D2s_v5) / Calico NetworkPolicy / workload identity on |
| ACR | `dahsimacr2kv7vfcrafu3o` (이미지 `:v1`) |
| Log Analytics | `dah-data-law` (`az monitor log-analytics workspace show -g dah-data-rg -n dah-data-law --query customerId`) |
| DCE ingest | `https://dah-data-dce-ttt8.koreacentral-1.ingest.monitor.azure.com` |
| DCR immutableId | primary `dcr-5c6adbefd9f449799791298a56d92189` / extras `dcr-3fcc15a7fb0d4c4ba69e96c90ffedaf5` / ext2 `dcr-1aad0b1cd2f9416e9fb954b402abc58d` |
| Fluent Bit SP | `uav-fluentbit-sp` appId `ba886feb-dd39-45c4-89df-cc24d3567338` (secret in k8s `soc/fluentbit-azure`) |
| 도메인 | `sim.pollak.store` |
| IP: gcs HTTP LB (동작함) | `20.249.193.191` (svc `ground/gcs-qgc-lb`) |
| IP: ingress 고정 (외부 안 통함) | `20.194.99.116` (publicIp `uav-ingress-ip` in node RG, svc `ingress-nginx/ingress-nginx-controller`) |
| VM | `uavsim-vm` (docker-compose 스택, **라이브 Sentinel 인제스트 소스**) |

GitOps: 차트 `local-k8s/helm/uav-sim` (base `values.yaml` + `values-aks.yaml`), ArgoCD `Application uav-sim` (namespace `argocd`). 변경 = git push → ArgoCD 자동 sync. `kubectl -n argocd patch application uav-sim --type merge -p '{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"hard"}}}'` 로 강제 리프레시.

## 2. 동작 확인된 것 (✅)

- AKS에 전체 워크로드 GitOps 배포(air/link/ground/c4i/soc namespace + NetworkPolicy 신뢰경계 + 노드풀 배치). ArgoCD `Synced/Healthy`.
- 데이터패스: `av-muav(SITL) → datalink-los(mavlink-router) → gcs-qgc(noVNC)`, GCS에 차량 표시.
- 도메인 컷오버 (단, 지금 DNS가 깨진 ingress IP를 가리킴 — §3 주의).
- **Sentinel 일원화 PoC**: `datalink-satcom` NDJSON(stdout) → `soc/fluentbit` DaemonSet → Logs Ingestion API(SP 인증) → DCR ext2 → `UAVSatcomLink_CL`. AKS 출처는 `UAVId == 'MUAV-AKS-001'` 로 구분. http_status=204 확인됨.
- cert-manager + ingress-nginx 설치됨.

## 3. HTTPS / ingress LB — ✅ 해결 (2026-06-26)

`https://sim.pollak.store/vnc.html` → `HTTP/2 200`, `certificate gcs-qgc-tls` `Ready True`. LE prod issuer 그대로 사용.

**근본 원인 (2개 동시 적중):**
1. **LB health probe HTTP `/` → ingress-nginx default backend가 `404` 반환 → probe unhealthy → LB가 80/443 trafficc drop.**
   같은 LB의 `8080`(gcs-qgc-lb)이 외부 정상 동작했던 이유는 그건 **TCP probe** 였기 때문 — 차이는 probe 프로토콜이었음.
2. **ground `default-deny` NetworkPolicy 가 cert-manager HTTP-01 solver pod 의 :8089 인입을 차단** → controller 가 challenge solver upstream으로 connect timeout → challenge 영구 `pending`.

**적용한 픽스:**
- `kubectl -n ingress-nginx patch svc ingress-nginx-controller -p '{"spec":{"externalTrafficPolicy":"Local"}}'` → `healthCheckNodePort` 자동 생성, probe path가 `/healthz` 로 바뀌어 200 → healthy. 영구화:
  ```bash
  helm upgrade ingress-nginx ingress-nginx/ingress-nginx -n ingress-nginx \
    --version 4.15.1 --reuse-values \
    --set controller.service.externalTrafficPolicy=Local
  ```
  (release values: `controller.service.loadBalancerIP=20.194.99.116` + `externalTrafficPolicy=Local`. helm release는 ArgoCD 밖, hand-managed.)
- 차트 `local-k8s/helm/uav-sim/templates/networkpolicies.yaml` 에 `allow-acme-solver` NP 추가:
  - podSelector `acme.cert-manager.io/http01-solver=true`, ingress from ns `ingress-nginx` port 8089/TCP.
  - challenge 진행 중에만 매칭됨(solver pod이 그때만 떠있음). 평상시 매칭 0.

**검증 명령** (회귀 시 다시 실행):
```bash
curl -sI https://sim.pollak.store/vnc.html | head -1   # HTTP/2 200
kubectl -n ground get certificate gcs-qgc-tls          # READY True
az network lb probe list -g dah-sim-rg-aks-nodes --lb-name kubernetes \
  --query "[?contains(name,'a5501dda')].{n:name,p:port,path:requestPath}" -o table
# → /healthz 로 떠야 정상. `/` 로 보이면 externalTrafficPolicy 가 Cluster 로 돌아온 것.
```

**리스크 / 메모:**
- `externalTrafficPolicy=Local` + controller `replicas=1` = controller 있는 노드 1개만 LB healthy → SPOF. 가용성 필요하면 `controller.replicaCount=2` + topology spread + sitl 노드풀이 ≥2여야.
- helm `--reuse-values` 통해 향후 ingress-nginx upgrade 시 externalTrafficPolicy 가 유지되는지 매번 확인. 누락되면 즉시 다시 set.
- `loadBalancerIP` 는 deprecated. 향후 Azure cloud-provider 가 강제 제거하면 `service.beta.kubernetes.io/azure-pip-name=uav-ingress-ip` annotation 방식으로 바꿔야 함.

**예전 복구 절차 (이제 불필요, 회귀 대비 보존):** §6의 `bash scripts/fix-ingress-https.sh --revert` 가 DNS 를 `20.249.193.191` 로 되돌리고 ingress off 안내까지 출력함.

## 4. 잔여 로드맵 (선택, 우선순위 낮음)

### 4-1. Sentinel 완전 일원화 (VM 폐기 목표) — `H3b`

**진행 상태 (2026-06-26):**

✅ 완료:
- `datalink-satcom` (H3a, ext2 DCR → `UAVSatcomLink_CL`).
- 노드 재배치: `ground stubs` / `c4i-stub` / `telemetry-tap` 가 system 풀(maxPods=30) 꽉 차서 21h Pending 이었음 → `sitl` 풀로 옮김. `values-aks.yaml` 의 `groundStubsNodePool`, `c4i.nodePool`, `telemetryTap.nodePool` = `sitl`.
- `LOG_FILE_PATH=/dev/stdout` 토글: `groundStubsLogToStdout=true` + `c4i.logPath=/dev/stdout` (없으면 NDJSON 이 emptyDir 파일에만 쓰여 FB tail 가 못 잡음).
- **8개 신규 stream 등록 (FB plugin init 정상, OUTPUT 9개 다 떠있음)**: 
  - 단순 6개: `mps-stub→UAVMissionPlan(PlanId)`, `c4i-stub→UAVC4I(OrderId)`, `weapon-stub→UAVWeapon(SafetyState)`, `cyber-posture-stub→UAVCyberPosture(Level)`, `ti-stub→UAVThreatIntel(Indicator)`, `auth-stub→UAVOpAudit(SessionId)`.
  - pgse 분기 2개(같은 컨테이너 → 2 stream): `pgse-stub→UAVPgse(ImageHashSubmitted, primary)`, `pgse-stub→UAVMaintenance(BatteryId, extras)`. `MAINT_FILE_PATH=/dev/stdout` 으로 두 NDJSON 이 같은 stdout 에 섞여 흐름. `ImageHashSubmitted`/`BatteryId` 가 상대 stream 에 절대 안 나오는 유일 필드라 grep 안전.
  - 차트 fluentbit Tag 를 `s_{container}_{stream}.*` 로 변경 → 동일 container 다중 stream 라우팅 가능.
- FB DS `nodeAffinity: pool ∈ {sitl, satcom}` → system 풀 Pending 해소 (DESIRED=2, 2/2 Running).

⏳ 트래픽 대기:
- 8개 stub 은 외부 호출이 와야 NDJSON 발행(현재 health probe 외 트래픽 0). 사용자가 테스트 비행 시작하면 자연스럽게 흘러감. KQL 로 도착 확인:
  ```kql
  union UAVMissionPlan_CL, UAVC4I_CL, UAVWeapon_CL, UAVCyberPosture_CL,
        UAVThreatIntel_CL, UAVOpAudit_CL, UAVPgse_CL, UAVMaintenance_CL
  | where TimeGenerated > ago(1h)
  | summarize count() by Type
  ```

✅ Batch3 도 완료:
- **telemetry-tap 7 stream + sar-stub 1 stream 추가**. 총 OUTPUT 17개 다 init + telemetry/operator/mission/config-audit/mavsec 실제 204 확인.
- **차트 fluentbit 구조 변경 (핵심)**: 같은 path 의 multi-INPUT 등록은 fluent-bit tail 에서 첫 매칭조차 못 함(Inotify Off/per-INPUT DB 등 다 시도 후 확인). → `range .streams` 를 container 별 grouping 후 container 마다 INPUT 1번 + `rewrite_tag` filter rule 로 stream Tag 분기. INPUT 수가 stream 수 → container 수로 축소되고, 같은 container 의 multi-stream 도 안전.
- **rewrite_tag value 타입 함정**: `Rule $KEY .+ NEW_TAG false` 에서 KEY 의 value 가 **integer 면 `.+` 매칭 실패**. value 를 string 으로 두면 매칭 성공. (telemetry-tap 의 7 marker 키 값을 `1` → `"telemetry"`/`"operator"`/… 로 변경. v5 이미지.)
- **sar-stub**: `./sar-stub/` 빌드(`sar:v1`) → ACR push → ground-stubs 한 줄 추가(`{name: sar-stub, image: sar, port: 8700, ...}`) → stream `UAVSarPayload(FrameId)`, ext2 DCR.

🟨 트래픽 들어와야 검증되는 것:
- `UAVFailsafe`/`UAVImagery` 는 mavlink STATUSTEXT(warning) / CAMERA_TRIGGER 등 특정 이벤트가 발생해야 NDJSON 생성. 일반 telemetry 흐름엔 안 옴 → 비행 시나리오 트리거 필요.
- ground/c4i 6 stub + sar 는 외부 API 호출이 와야 NDJSON.

위 둘 다 트래픽 측면이고 인프라 측은 정상.

✅ VM 폐기 (2026-06-26): `az vm deallocate -g dah-sim-rg -n uavsim-vm` 완료. compute 과금 중단, disk 유지(필요 시 `az vm start` 으로 복귀). **주의: `dah-sim-rg` 통째 삭제 금지(AKS도 거기).**

✅ 트래픽 검증 (30분 비행, 2026-06-26):
- UAVTelemetry 68,352 / UAVOperator 3,171 / UAVMissionEvent 3,078 / UAVSatcomLink 403 / UAVConfigAudit 169 / UAVMavsec 55 / UAVFailsafe 4 — 다 정상 도착, UAVId=MUAV-AKS-001 (datalink-satcom + telemetry-tap 둘 다 override).
- UAVImagery 0 = mission 에 CAMERA_TRIGGER waypoint 없어서. 향후 mission-planner 가 박으면 흐름.
- 9 stub HTTP stream (UAVC4I/MissionPlan/Weapon/Pgse/Maintenance/ThreatIntel/OpAudit/SarPayload/CyberPosture) = 호출자 없음, 0 카운트. mission-planner 작업으로 분리.

지도 타일 fetch 를 위해 `gcs-egress-internet` NP 추가됨 (443/80 외부만, 사설 대역 제외).

### 4-2. 정리/위생
- SP 시크릿 로테이션: `az ad app credential reset --id ba886feb-...` → k8s secret `soc/fluentbit-azure` 갱신.
- 미사용 자원: 워크로드ID `uav-fluentbit`(MI)는 이미 삭제됨. 고정 IP `uav-ingress-ip`는 ingress 결론에 따라.
- 비용: 안 쓸 때 `az aks stop -g dah-sim-rg -n dah-sim-aks` + `az vm deallocate -g dah-sim-rg -n uavsim-vm`.

## 5. 핵심 교훈 (디버깅 단축용)

- Fluent Bit `azure_logs_ingestion`(v3.2.2)은 **워크로드 ID 미지원 → 서비스 프린시플(client_secret) 필수**. 테넌트가 일반 사용자 앱 등록을 막아서 관리자가 SP 생성해줌.
- 같은 플러그인: 설정 키는 `stream_name`이 아니라 **`table_name`**, 그리고 **`Custom-` 자동 접두**(값은 접두어 없이).
- soc namespace는 default-deny → FB가 443(API서버+DCE) egress 하려면 NetworkPolicy 예외 필요(`fluentbit-egress`, 차트에 있음).
- ArgoCD ConfigMap 갱신 후 Fluent Bit는 **수동 재시작** 필요, 그리고 **DaemonSet 롤링업데이트가 Pending 파드(maxPods)에 막히면** 다른 파드도 안 바뀜 → 막힌 노드 파드 강제 삭제.
- AKS 노드 vCPU 쿼터 8 → D2s_v5×3(6vCPU). 편대/노드 증설 시 쿼터 증액 필요.
- **Azure LoadBalancer + ingress-nginx의 함정**: `externalTrafficPolicy=Cluster` 면 Azure cloud-provider 가 LB rule probe를 **HTTP path `/`** 로 자동 설정 → controller default backend 404 → unhealthy → 외부 traffic drop. `Local` 로 바꾸면 `healthCheckNodePort` + `/healthz` 가 자동 와이어링되어 해결. (그래서 같은 LB의 다른 svc 가 TCP probe 면 잘 동작해도 ingress 룰만 죽는 비대칭이 나옴.)
- **cert-manager HTTP-01 + default-deny NP**: solver pod label = `acme.cert-manager.io/http01-solver=true`, port `8089`. ingress-nginx ns 에서 그 selector 로의 인입을 명시적으로 열어야 challenge 통과. challenge 영구 `pending` 이면 거의 NP.
- **stub NDJSON 은 기본 emptyDir 파일에 쓰임**: `LOG_FILE_PATH=/var/log/uav-sim-env/{name}.ndjson` 가 default. Fluent Bit 가 kubelet `/var/log/containers/*.log` 만 tail 하므로 그대로 두면 일원화 못 함. `/dev/stdout` 으로 override 필수(H3a satcom 패턴). 또 uvicorn 평문 로그가 같이 섞이지만 grep filter (`marker .+`) 가 JSON-only 로 거름.
- **fluent-bit tail INPUT 동일 path 다중 등록 제한**: 같은 file glob 으로 INPUT 7개 박으면 첫 매칭조차 못 함. 2개는 운 좋게 됐을 뿐. 해결: container 1 → INPUT 1 + `rewrite_tag` filter 로 stream Tag 분기. emitter 가 새 tag 로 record 를 pipeline 재진입시켜 OUTPUT 의 정확한 tag 매칭.
- **rewrite_tag rule value 타입**: `Rule $KEY .+ NEW_TAG false` 의 `.+` regex 가 record value 가 **integer 면 매칭 실패**. (예: `"StreamTelemetry": 1` 안 됨, `"StreamTelemetry": "telemetry"` 됨.) marker 키를 코드에서 박을 때 항상 **string** 값으로.

## 6. 진단 스크립트

`scripts/fix-ingress-https.sh` — ingress LB 외부 경로를 자동 진단(컨트롤러/내부/외부/LB룰/프로브/NSG/IP attach)하고, auto-IP 재생성을 시도하며, 실패 시 동작 HTTP IP로 DNS 복구 안내를 출력한다. 읽고 실행한 뒤 출력 기반으로 다음 수를 판단할 것.
