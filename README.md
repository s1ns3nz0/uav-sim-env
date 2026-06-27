# uav-sim-env

LIG D&A Hackathon B 트랙 (UAV/드론/국방) — **UAS(무인항공기 체계) 시뮬레이션 환경**.
실기체 없이 SOC(보안관제) 시나리오를 검증하기 위한 풀스택 무인기 시뮬.

본 환경은 자매 프로젝트 `pollack-ai`(LangGraph 기반 UAV AI SOC 플랫폼)의 입력 텔레메트리 생성기 역할.

**현재 운영 상태 (2026-06-27)**: AKS 클러스터 + GitOps(Helm + ArgoCD) + Sentinel 17-stream 일원화 + **편대 3대 fixed-wing 비행** + HTTPS(`sim.pollak.store`). VM 폐기됨.

---

## 1. 무엇을 시뮬레이션 하는가

미 육군 교범 **FMI 3-04.155** 가 정의하는 UAS(Unmanned Aircraft System) 5대 구성요소를 컨테이너로 재현.

| 구성요소 | 실제 운용 | 컨테이너 | 사용 오픈소스 |
|---|---|---|---|
| **AV** (Air Vehicle) | 비행체 + 페이로드 + GPS/INS/IFF | `av-mpd` (MPD), `av-muav` (KUS-FS, StatefulSet N대) | ArduPilot SITL |
| **Data Link (LOS)** | LOS C-band 200km | `datalink-los` | mavlink-router + tc netem |
| **Data Link (BLOS)** | BLOS Ku/Ka SATCOM | `datalink-satcom` | Python NDJSON emitter |
| **GCS** (Ground Control Station) | UGCS, Mini-UGCS, 임무계획/조종/영상분석 | `gcs-qgc` | QGroundControl + Xvfb + noVNC |
| **PGSE** | 발사장비, 정비공구, 회수네트 | `pgse-stub` | FastAPI + cosign/SBOM |
| **C4I / 무기 / TI / Auth / Posture** | 외부 SOC 인터페이스 | `c4i-stub`, `weapon-stub`, `ti-stub`, `auth-stub`, `cyber-posture-stub` | FastAPI |
| **SOC 관측** | mavlink tap, FB 인제스트 | `telemetry-tap` (7 분기 NDJSON), `fluent-bit` DaemonSet | Logs Ingestion API → Sentinel |

---

## 2. 모델링 대상 기체

두 기체 동시 시뮬:

### MPD — LIG Nex1 다목적 드론
| 특성 | 값 | 시뮬 매핑 |
|---|---|---|
| 형상 | 틸트로터 4발 VTOL | ArduPilot `quadplane` |
| 운용 | 분대급 ~ 표적 탐지·정밀 타격 | `mpd_recon.plan` |
| 통신 | LOS RF only (Group 1-2) | `datalink-los` UDP/MAVLink |

### MUAV — ADD/KAI/대한항공 KUS-FS (MALE)
| 특성 | 값 | 시뮬 매핑 |
|---|---|---|
| 형상 | 고정익 단발 터보프롭 | ArduPilot `plane` |
| 운용 | 24h 장기체공, 13km 천장, ISR | `av-muav` StatefulSet (편대 N대) |
| 통신 | LOS + SATCOM 이중 링크 | `datalink-los` + `datalink-satcom` |
| 시험지 | **ADD 안흥 시험비행장 (36.71, 126.13)** | values 의 `avMuav.home` |
| 편대 | StatefulSet `replicas=N` + pod ordinal 기반 SysId/HOME 동적 분리 | F1 차트 wrapper |

---

## 3. 아키텍처 (3 트랙)

같은 helm chart `local-k8s/helm/uav-sim/` 가 **AKS + kind 단일 진실**. `docker-compose.yml` 은 옛 단일 VM 트랙(보존 only).

### 3-1. AKS GitOps (운영)
```
                Sentinel (dah-data-law, koreacentral)
                       ▲ Logs Ingestion API
                       │   (Fluent Bit SP 인증)
                       │
   ┌─────────────────  AKS dah-sim-aks ─────────────────────────────┐
   │                                                                │
   │  ┌─ ns: air ───┐ ┌─ ns: link ──┐ ┌─ ns: ground ─┐ ┌─ ns: c4i ─┐│
   │  │ av-muav-0/1/2│ │datalink-los │ │ gcs-qgc      │ │ c4i-stub  ││
   │  │ (StatefulSet)│ │datalink-satcom│ │ mps/cyber/...│ │           ││
   │  └──────────────┘ └─────────────┘ └──────────────┘ └───────────┘│
   │                                                                │
   │  ┌─ ns: soc ─────────────────────────────────────────────────┐ │
   │  │ telemetry-tap (7 분기) + fluentbit DaemonSet              │ │
   │  └───────────────────────────────────────────────────────────┘ │
   │                                                                │
   │  ArgoCD (uav-sim Application) → Helm chart 자동 sync           │
   └────────────────────────────────────────────────────────────────┘
                       │
                       ▼ ingress-nginx + cert-manager (LE prod)
                  sim.pollak.store (HTTPS, noVNC QGC)
```

- **노드풀**: `system` (kube-system + ingress), `sitl` (SITL 편대 + telemetry-tap + ground stubs), `satcom` (datalink-satcom + gcs-qgc, taint `dedicated=satcom`)
- **GitOps**: git push → ArgoCD 자동 sync (`syncPolicy.automated: prune+selfHeal`)
- **이미지 레지스트리**: `dahsimacr2kv7vfcrafu3o.azurecr.io` (ACR)

### 3-2. kind local (개발/팀원)
```
   kind cluster (3 worker = system/sitl/satcom 모사) + Calico CNI
       ↓
   docker build → kind load → helm install -f values-kind.yaml
       ↓
   같은 컴포넌트, fluentBit/ingress off, 이미지 로컬, UAVId 출처 분리(MUAV-KIND)
```

### 3-3. docker compose (옛 단일 VM, 보존 only)
KUS-FS 편대 / NetworkPolicy / Multi-node 검증 불가. 신규 작업 X.

---

## 4. 빠른 시작

### Option A — AKS 운영 (Sentinel + 도메인 + 편대)

전제: Azure 구독 + `az` CLI + ACR + AKS 클러스터 + DNS 존 `pollak.store` (또는 본인 도메인).

```bash
# 1. AKS context
az aks get-credentials -g dah-sim-rg -n dah-sim-aks

# 2. ArgoCD Application 적용 (gitops/ 안 manifests)
kubectl apply -f gitops/argocd-app.yaml

# 3. ArgoCD 자동 sync → 5분 후 다 Running
kubectl -n argocd get application uav-sim
kubectl get pods -A -o wide

# 4. QGC noVNC 접속
open https://sim.pollak.store/vnc.html   # VNC pw: uavsim
```

**일시 정지 (비용 0)**:
```bash
az aks stop -g dah-sim-rg -n dah-sim-aks
# 다시: az aks start -g dah-sim-rg -n dah-sim-aks
```

### Option B — kind local (팀원 노트북, AKS 동일 구조)

전제: Docker Desktop + kind + kubectl + helm.

```bash
cd local-k8s
bash up.sh          # kind + Calico + 노드풀 라벨 + 이미지 build+load + helm install
bash verify-netpol.sh   # 신뢰경계(NetworkPolicy) 검증
bash down.sh        # 전체 삭제
```

`up.sh` 가 `helm upgrade --install uav-sim ./helm/uav-sim -f values.yaml -f values-kind.yaml` 박음 = AKS 와 **같은 차트, 같은 컴포넌트**.

차이 (values-kind.yaml):
- 이미지 `uavsim/*:local` (로컬 docker build + kind load)
- `fluentBit/ingress` off (Sentinel DCR / LE cert 없음)
- 편대 3대 + SITL CPU req 50m (단일 sitl worker 부담 줄임)
- UAVId 출처 = `MUAV-KIND`

GCS 접속 (kind):
```bash
kubectl -n ground port-forward svc/gcs-qgc 8080:8080 5900:5900
open http://localhost:8080/vnc.html
```

### Option C — docker compose (옛 단일 VM, 신규 작업 X)
```bash
docker compose build && docker compose up -d
open http://localhost:8080/vnc.html
```

---

## 5. 비행 시뮬 (편대 3대 mission)

QGC noVNC 에서 사전 박힌 plan 파일 import + Upload + Takeoff.

### Mission 파일 (안흥 활주로 기준 1.1km × 1.1km patrol box + LAND)

```
1. NAV_TAKEOFF (alt 80m)
2-5. NAV_WAYPOINT × 4 corner (한 바퀴 시계방향)
6. NAV_LAND (HOME 좌표, alt 0 = 활주로 자동 착륙)
```

**Vehicle 별 시작 corner 다름** (동시 patrol 시각화):
- V1: 시작 corner A (북) → B → C → D → LAND
- V2: 시작 corner B (북동) → C → D → A → LAND
- V3: 시작 corner C (동) → D → A → B → LAND

### Plan 파일 위치 (gcs-qgc pod 안)
- `/home/qgc/missions/v1.plan`
- `/home/qgc/missions/v2.plan`
- `/home/qgc/missions/v3.plan`

### QGC 절차
1. Vehicle selector → Vehicle 1 → Plan 탭
2. File icon → Open File → `/home/qgc/missions/v1.plan` → Upload
3. Fly 탭 → Takeoff slide
4. Vehicle 2, 3 반복 (v2.plan, v3.plan)

또는 multi-vehicle 패널 `Start Mission` 으로 3대 동시.

### 비행 종료
- mission 끝 = NAV_LAND 자동 → 활주로 착륙 + disarm
- 강제 종료: `kubectl -n air delete pod av-muav-0 av-muav-1 av-muav-2 --grace-period=0 --force`

---

## 6. SOC 일원화 (17 stream)

`telemetry-tap` 가 mavlink → NDJSON 7-way fan-out + ground stubs stdout 도 fluentbit 가 tail 해 **Sentinel 의 17개 Custom Table** 로 인제스트.

### Stream 매핑
| Stream | Custom Table | 소스 | Marker |
|---|---|---|---|
| satcom | `UAVSatcomLink_CL` | datalink-satcom | LinkId |
| telemetry | `UAVTelemetry_CL` | telemetry-tap (mavlink raw) | StreamTelemetry |
| operator | `UAVOperator_CL` | telemetry-tap (op derived) | StreamOperator |
| mission | `UAVMissionEvent_CL` | telemetry-tap (mission derived) | StreamMission |
| failsafe | `UAVFailsafe_CL` | telemetry-tap | StreamFailsafe |
| imagery | `UAVImagery_CL` | telemetry-tap (CAMERA_*) | StreamImagery |
| config-audit | `UAVConfigAudit_CL` | telemetry-tap (PARAM_VALUE) | StreamConfigAudit |
| mavsec | `UAVMavsec_CL` | telemetry-tap (30s 주기) | StreamMavsec |
| mps | `UAVMissionPlan_CL` | mps-stub | PlanId |
| c4i | `UAVC4I_CL` | c4i-stub | OrderId |
| weapon | `UAVWeapon_CL` | weapon-stub | SafetyState |
| cyber-posture | `UAVCyberPosture_CL` | cyber-posture-stub | Level |
| ti | `UAVThreatIntel_CL` | ti-stub | Indicator |
| auth | `UAVOpAudit_CL` | auth-stub | SessionId |
| pgse-firmware | `UAVPgse_CL` | pgse-stub (firmware ndjson) | ImageHashSubmitted |
| pgse-maint | `UAVMaintenance_CL` | pgse-stub (maintenance ndjson) | BatteryId |
| sar | `UAVSarPayload_CL` | sar-stub | FrameId |

### 핵심 함정 (디버깅용)
- **Fluent Bit tail INPUT 동일 path 다중 등록 제한** → container 별 INPUT 1 + `rewrite_tag` filter
- **rewrite_tag `$KEY .+` regex 가 integer value 매칭 실패** → marker 값은 항상 **string**
- **stub NDJSON default 가 emptyDir 파일** → `LOG_FILE_PATH=/dev/stdout` 필수
- **LB probe HTTP `/` → ingress-nginx default 404 → unhealthy** → `externalTrafficPolicy=Local` 로 `/healthz` healthCheckNodePort
- **ground default-deny NP** 가 cert-manager solver pod:8089 차단 → `allow-acme-solver` NP

### 검증 (KQL)
Azure Portal → Log Analytics `dah-data-law` (RG `dah-data-rg`) → Logs:
```kql
union UAVTelemetry_CL, UAVOperator_CL, UAVMissionEvent_CL, UAVSatcomLink_CL,
      UAVFailsafe_CL, UAVMavsec_CL, UAVConfigAudit_CL, UAVImagery_CL,
      UAVThreatIntel_CL, UAVOpAudit_CL, UAVPgse_CL, UAVMaintenance_CL,
      UAVCyberPosture_CL, UAVC4I_CL, UAVMissionPlan_CL, UAVWeapon_CL,
      UAVSarPayload_CL
| where TimeGenerated > ago(15m)
| summarize count() by Type
```

---

## 7. 시나리오 매트릭스

본 환경은 **시나리오를 실행하는 것이 아니라 시나리오가 칠 수 있는 대상을 갖춰놓는** 것이 목적. 실제 공격 실행/탐지 룰 작성은 `pollack-ai` 트랙.

| 시나리오 | 출력 룰 (`pollack-ai`) | 공격 대상 | 텔레메트리 진입점 | 환경 준비 |
|---|---|---|---|---|
| **S1 GNSS 스푸핑** | `uav_gps_spoof_residual.yml` | `av-*` SITL `SIM_GPS_*` 파라미터 (MAVLink PARAM_SET) | `UAVTelemetry_CL` EKF_STATUS_REPORT PosHorizVariance/VelocityVariance | ✅ |
| **S3 SATCOM MITM** | `uav_satcom_integrity_fail.yml` | `datalink-satcom` Seq/IntegrityStatus 조작 | `UAVSatcomLink_CL` | ✅ |
| **S4 펌웨어·공급망 변조** | `uav_fw_signature_mismatch.yml` | `pgse-stub` `/preflight/check`, `/armory/firmware/{id}`, `/launch/authorize` | `UAVPgse_CL`, `UAVMaintenance_CL` | ✅ |
| **A4 MAVLink 평문 인젝션** | (TBD) | `datalink-los` TCP `:5790` MAVProxy/pymavlink 패킷 주입 | `UAVTelemetry_CL` COMMAND_LONG, `UAVOperator_CL` ActionName | ✅ |

---

## 8. 디렉터리 구조

```
uav-sim-env/
├── README.md
├── HANDOFF.md                       # Claude Code 핸드오프 (현 블로커 + 잔여 로드맵)
├── docker-compose.yml               # 옛 단일 VM 트랙 (보존 only)
│
├── av-mpd/                          # AV (Air Vehicle) — ArduPilot SITL (MPD + MUAV 공용 image)
│   ├── persona/{mpd_quadplane,muav_male}.parm
│   └── entrypoint.sh
├── datalink-los/                    # LOS RF + mavlink-router
│   └── entrypoint.sh                # AV_REPLICAS loop 으로 N TcpEndpoint 동적
├── datalink-satcom/                 # BLOS SATCOM emitter
├── telemetry-tap/                   # mavlink → 7 분기 NDJSON
│   └── tap.py                       # UAVId = MUAV-AKS-SYS{sysid:03d} 동적
├── gcs-qgc/                         # QGroundControl + noVNC
│
├── {mps,c4i,weapon,ti,auth,cyber-posture,pgse,sar}-stub/   # ground HTTP stub
├── service-audit/                   # docker 이벤트 audit (compose 트랙)
├── datalink-stats/                  # router stats (compose 트랙)
│
├── infra/                           # Azure Bicep (DCR, DCE, Workspace, Storage)
│   └── sentinel/{dcr,dcr-extras,dcr-ext2,tables}.bicep
│
├── local-k8s/                       # kind local (AKS 유사) + helm chart
│   ├── kind-config.yaml             # 3 worker (system/sitl/satcom)
│   ├── up.sh                        # kind 생성 + Calico + helm install
│   ├── down.sh
│   ├── verify-netpol.sh
│   ├── manifests.legacy/            # DEPRECATED standalone yaml
│   └── helm/uav-sim/
│       ├── Chart.yaml
│       ├── values.yaml              # chart default (kind 호환)
│       ├── values-aks.yaml          # AKS override (ACR registry, fluentBit on, ingress on)
│       ├── values-kind.yaml         # kind override (local registry, fluentBit off)
│       └── templates/               # Service, StatefulSet, Deployment, NetworkPolicy, Ingress 등
│
├── gitops/                          # ArgoCD Application
│   └── argocd-app.yaml
│
└── scripts/                         # 진단/배포 보조
    └── fix-ingress-https.sh         # 이전 ingress LB 진단 (해소됨)
```

---

## 9. 인프라 식별자 (운영 참조)

전부 `koreacentral`.

| 항목 | 값 |
|---|---|
| Subscription | `b7acdba2-f2d6-4ff5-a059-008b20432f79` |
| RG: 시뮬+AKS | `dah-sim-rg` |
| RG: Sentinel/LA | `dah-data-rg` |
| RG: SOC(kagent) | `dah-soc-rg` |
| RG: DNS 존 | `dah-shared-rg` (zone `pollak.store`) |
| AKS | `dah-sim-aks` (nodepools: system, sitl, satcom; Calico NetworkPolicy; workload identity on) |
| ACR | `dahsimacr2kv7vfcrafu3o` |
| Log Analytics | `dah-data-law` |
| DCE | `https://dah-data-dce-ttt8.koreacentral-1.ingest.monitor.azure.com` |
| DCR (primary) | `dcr-5c6adbefd9f449799791298a56d92189` |
| DCR (extras) | `dcr-3fcc15a7fb0d4c4ba69e96c90ffedaf5` |
| DCR (ext2) | `dcr-1aad0b1cd2f9416e9fb954b402abc58d` |
| Fluent Bit SP | `uav-fluentbit-sp` appId `ba886feb-dd39-45c4-89df-cc24d3567338` (secret in `soc/fluentbit-azure`) |
| 도메인 | `sim.pollak.store` |
| ingress 고정 IP | `20.194.99.116` (publicIp `uav-ingress-ip`) |
| GCS LB IP | `20.249.193.191` (svc `ground/gcs-qgc-lb`) |

---

## 10. UAS Group 1~5 확장성

ArduPilot + MAVLink 기반 시뮬은 **프레임/거동 측면에서 Group 1~5 전부 커버 가능**.

| Group | 예시 | 본 환경 매핑 | 비고 |
|---|---|---|---|
| 1-2 | MPD (LIG) | `av-mpd` (quadplane) | ✅ |
| 3 | RQ-7 Shadow, RQ-101 송골매 | LOS + 일부 BLOS | LOS 모델 동일 |
| 4 | MQ-1C Gray Eagle | + SATCOM stub | `datalink-satcom` ✅ |
| 5 | MQ-9 Reaper, RQ-4 Global Hawk, **KUS-FS MUAV** | + dual-link | **`av-muav` 편대 ✅** |

---

## 11. Phase 로드맵

| Phase | 범위 | 상태 |
|---|---|---|
| 0 | 단일 MPD MVP (compose) | ✅ |
| 1a | telemetry-tap (NDJSON) | ✅ |
| 1b | pgse-stub + 5790 노출 (A4) | ✅ |
| 1c | Azure Monitor Agent → Log Analytics | ✅ (Sentinel 인제스트) |
| 2 | KCD-200 + SATCOM stub (S3 BVLOS) | ✅ (datalink-satcom) |
| H3a | SOC 일원화 PoC (datalink-satcom → `UAVSatcomLink_CL`) | ✅ |
| H3b | 17 stream 인제스트 (rewrite_tag 패턴) | ✅ |
| I1 | HTTPS 도메인 (`sim.pollak.store`) | ✅ |
| **F1** | **편대 3대 (StatefulSet ordinal SysId/HOME, 안흥 활주로)** | ✅ |
| F2 | mission-planner 페이지 (팀원 자율 시나리오 트리거) | 보류 |
| F3 | 9 stub HTTP traffic 자동화 | F2 안 |
| F4 | follow-the-leader formation flying | — |

---

## 12. 참고 자료

- **FMI 3-04.155** US Army Unmanned Aircraft System Operations
- **ATP 3-04.64** US Army UAS
- **LIG 무인기 카탈로그** (사내, `pollack-ai/docs/`)
- **ArduPilot SITL**: https://ardupilot.org/dev/docs/sitl-simulator-software-in-the-loop.html
- **MAVLink common dialect**: https://mavlink.io/en/messages/common.html
- **Azure Logs Ingestion API**: https://learn.microsoft.com/en-us/azure/azure-monitor/logs/logs-ingestion-api-overview
- **Fluent Bit `azure_logs_ingestion`**: https://docs.fluentbit.io/manual/pipeline/outputs/azure_logs_ingestion
- **ArgoCD Application**: https://argo-cd.readthedocs.io/en/stable/operator-manual/argocd_application_yaml/

---

## 라이선스

(별도 명시 없음 — 내부 PoC)
