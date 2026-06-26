# HANDOFF → Claude Code

이 문서는 진행 중인 작업을 Claude Code가 이어받기 위한 **컨텍스트 + 현재 블로커 + 잔여 로드맵**이다.
바로 다음 작업: **`sim.pollak.store` HTTPS가 안 되는 AKS LB 문제 해결** (아래 §3).

---

## 0. 한 줄 요약

LIG D&A 해커톤 UAV SOC 시뮬을 **단일 VM → AKS(GitOps/Helm/ArgoCD)** 로 이전 완료. 도메인·데이터패스·Sentinel 일원화 PoC까지 동작. **현재 막힌 것: AKS ingress-nginx LB의 외부 트래픽이 안 통해 HTTPS 미완성.**

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

## 3. 현재 블로커 — HTTPS / ingress LB ★ 최우선

**증상**: `https://sim.pollak.store` 미완성. cert-manager HTTP-01 challenge가 self-check timeout.
근본 원인: **외부에서 ingress LB IP `20.194.99.116:80` 으로 접속이 timeout** (cert는 부차적 — LB가 트래픽을 안 흘리니 HTTPS도 못 뜸).

**지금까지 확인 (전부 정상인데도 외부 timeout):**
- DNS `sim.pollak.store` → `20.194.99.116` ✅ (`dig @8.8.8.8`)
- `ingress-nginx-controller` Pod `1/1 Running` (sitl 노드), **내부에서 `404` 응답 = 컨트롤러 정상** (`kubectl -n ingress-nginx run t --rm -i --image=busybox -- wget -qO- http://ingress-nginx-controller.ingress-nginx.svc/`)
- svc EXTERNAL-IP `20.194.99.116`, `externalTrafficPolicy: Cluster`
- LB `kubernetes`(node RG)에 `TCP-80`/`TCP-443` 룰 존재, 프론트엔드 `a5501dda...` = `uav-ingress-ip` 가 attach됨 (`az network public-ip show ... ipConfiguration.id` 가 그 frontend 가리킴)
- NSG `aks-agentpool-30914346-nsg` 에 80/443 Allow 규칙 추가함(+ AKS 자동 룰)
- 그런데도 외부 `curl -m8 http://20.194.99.116/` → **Connection timed out**

**아직 안 본/의심 지점 (Claude Code가 여기부터):**
1. **LB health probe** — 80/443 룰의 프로브가 백엔드(노드)를 unhealthy로 보면 LB가 트래픽을 drop. `az network lb probe list -g dah-sim-rg-aks-nodes --lb-name kubernetes -o table` + 백엔드 풀 멤버/헬스 확인. (참고: 같은 LB의 `8080`(gcs-qgc-lb)은 외부 정상 동작 → LB 자체는 멀쩡, 80/443 룰 또는 그 프로브/프론트엔드만 문제일 가능성.)
2. **고정IP 강제(`loadBalancerIP`, deprecated) 부작용** — auto-IP로 재생성 시도: 어노테이션/`loadBalancerIP` 제거 → AKS가 새 IP로 재와이어링 → 그 IP로 외부 curl 테스트 → 되면 DNS 그 IP로.
3. **프론트엔드/룰 stale** — ingress svc 삭제 후 재생성(helm uninstall/install 또는 svc 재생성)으로 LB 재구성.

**대안(권장 검토)**: HTTP-01이 self-check 때문에 까다로우면 **cert-manager DNS-01 + Azure DNS**(zone `pollak.store` in `dah-shared-rg`)로 전환하면 발급은 깔끔. 단 **LB 외부 경로 문제는 그래도 별도로 고쳐야 HTTPS가 실제로 서빙됨**. 즉 LB 외부 timeout이 핵심.

**HTTPS 못 고치면 즉시 복구 (도메인 살리기)**: 지금 도메인이 깨진 IP를 가리켜 GCS가 접속 불가. HTTP 동작 IP로 되돌릴 것:
```bash
az network dns record-set a add-record    -g dah-shared-rg -z pollak.store -n sim -a 20.249.193.191
az network dns record-set a remove-record -g dah-shared-rg -z pollak.store -n sim -a 20.194.99.116
```
그리고 차트에서 ingress 끄기: `local-k8s/helm/uav-sim/values-aks.yaml` 의 `ingress: { enabled: true }` → `false`, commit/push (LE prod 재시도 rate-limit 방지).

성공 판정: `curl -sI https://sim.pollak.store/vnc.html` → `HTTP/2 200`, `kubectl -n ground get certificate gcs-qgc-tls` → `READY True`.

진단 자동화: `scripts/fix-ingress-https.sh` 참고(아래 §6).

## 4. 잔여 로드맵 (선택, 우선순위 낮음)

### 4-1. Sentinel 완전 일원화 (VM 폐기 목표) — `H3b`
`local-k8s/helm/uav-sim/values.yaml` 의 `fluentBit.streams` 리스트에 컴포넌트별로 한 줄씩 추가.
**중요**: 플러그인이 `table_name` 앞에 `Custom-` 를 자동으로 붙이므로 `stream` 값엔 접두어 없이 넣는다(예: `UAVSatcomLink`). `marker` = 그 컴포넌트 NDJSON에만 있는 필드(uvicorn 로그 거르기용).

단일파일 컴포넌트 (primary DCR `dcr-5c6adbef...`):
| container | stream(table_name) | marker |
|---|---|---|
| mps-stub | `UAVMissionPlan` | `PlanId` |
| c4i-stub | `UAVC4I` | `OrderId` 또는 `EventType` |
| cyber-posture-stub | `UAVCyberPosture` | `Level` |
| weapon-stub | `UAVWeapon` | `SafetyState` |
| pgse-stub | `UAVPgse` | `Found`/`Passed` (단 pgse는 maintenance.ndjson→`UAVMaintenance`로도 분기 = 2테이블, 내용 라우팅 필요) |

extras DCR(`dcr-3fcc15a7...`) 매핑은 `infra/sentinel/dcr-extras.bicep` 읽어서 확인 (ti→`UAVThreatIntel`, auth→`UAVOpAudit` 등).
**까다로운 부분**: `telemetry-tap`은 7파일→7테이블(telemetry/operator/mission/failsafe/config-audit/imagery/mavsec) 팬아웃 → 컨테이너 단일 라우팅 불가, 내용 기반 분기 필요. `sar-stub`은 **AKS 차트에 미배포**(추가 필요, `UAVSarPayload`, marker `FrameId`, DCR ext2).
**노드 정리**: `system` 노드 maxPods(30) 꽉 참 → ground 스텁/c4i 를 `sitl` 노드풀로 옮기면(values의 nodePool) FB가 sitl/satcom 2노드로 전부 커버, system FB Pending 무의미해짐.
일원화 검증 후 **VM 폐기**: `az vm deallocate -g dah-sim-rg -n uavsim-vm` (또는 삭제). **주의: `dah-sim-rg` 통째 삭제 금지(AKS도 거기 있음).**

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

## 6. 진단 스크립트

`scripts/fix-ingress-https.sh` — ingress LB 외부 경로를 자동 진단(컨트롤러/내부/외부/LB룰/프로브/NSG/IP attach)하고, auto-IP 재생성을 시도하며, 실패 시 동작 HTTP IP로 DNS 복구 안내를 출력한다. 읽고 실행한 뒤 출력 기반으로 다음 수를 판단할 것.
