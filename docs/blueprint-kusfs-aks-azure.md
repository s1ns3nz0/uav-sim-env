# 청사진 — KUS-FS(Group 4, MUAV) 시뮬을 Azure AKS에 올리기

> **상태**: v0.1 (배포 청사진 / blueprint)
> **목적**: 현 `uav-sim-env`(MPD · Group 1 · LOS only · 단일 VM)을 **KUS-FS(Group 4, MALE, LOS+SATCOM 이중 링크)** 로 확장하여 **Azure AKS** 위에서 운용하는 최종 그림과 거기까지 가는 단계를 정의한다.
> **근거 문서**: `README.md`(§6 Group 확장, §7 Azure), `docs/muav-background.md`(KUS-FS 배경·통신), `docs/components.md`(현 컴포넌트·인프라), `docs/uas-detail-6-satcom.md`(OpenSAND/+1 위성요소), `docs/adr/0001-fleet-satcom-runtime-aks.md`(AKS 이전 결정), `docs/adr/0002-aks-target-architecture.md`(AKS 타깃 원칙), `infra/*.bicep`
> **범위**: Azure 인프라/배포 전반. 신규 컴포넌트 *내부* 구현(av-muav persona, OpenSAND 셋업)은 별도 설계서로 위임하고 여기서는 배치·런타임·데이터 회선 관점만 다룬다.

> **표기 주의**: 의뢰에서 "MUF-KS"로 언급되었으나, 레포 문서 기준 정식 명칭은 **KUS-FS**(중고도 무인기, MUAV)다. 본 문서는 KUS-FS로 통일한다.

---

## 0. 한 줄 요약

현 시뮬은 **단일 VM + docker-compose**라 MPD(Group 1, LOS)까지가 한계다. KUS-FS는 **편대(2~4대) + SATCOM(BLOS)** 이라는 두 무거운 변화를 요구하고(ADR-0001), 이는 D4s_v5로 불가능하다. 따라서 최종 그림은 **AKS**다 — AV 1대 = Pod 1개(StatefulSet), 노드풀을 SITL/OpenSAND/(GPU)로 분리, **Multus 이중 인터페이스(net-los / net-satcom)** 로 RF·위성 링크를 실제 망 계층에서 재현하고, NetworkPolicy(default-deny)로 공중→지상 경로를 datalink 게이트웨이로만 강제한다. 데이터 평면은 기존 3-RG(`dah-sim`/`dah-data`/`dah-soc`)를 유지하되 Sentinel에 **`UAVSatcomLink_CL`** 등 신규 테이블을 추가해 **S3(SATCOM MITM)** 위협면을 실재화한다.

> **구현 진행 상태 — B-트랙(컴포넌트 빌드, 로컬 compose) ✅ 2026-06-25.** AKS 이전(인프라)에 앞서 KUS-FS 신규 컴포넌트를 로컬 compose에서 먼저 빌드·검증(무료, OpenSAND 리스크 분리). 완료:
> - **`av-muav`** — 고정익 MALE SITL. av-mpd 이미지 재사용(persona/frame만 env 교체), `muav_male.parm` 페르소나. 부팅 검증 OK(`--model plane`).
> - **`sar-stub`** — SAR 페이로드 FastAPI(:8700) → `sar.ndjson` → `UAVSarPayload_CL`. 스키마 일치 검증 OK.
> - **`datalink-satcom`(태깅 계층)** — BLOS 링크 신호 + S3 메타(세션/시퀀스/서명/RTT/재밍) FastAPI(:8800) → `satcom.ndjson` → `UAVSatcomLink_CL`. 4종 S3 주입(integrity/replay/hijack/jam) 검증 OK. **OpenSAND 물리계층은 미포함(다음 단계).**
>
> **구현 진행 상태 — C-트랙(AKS 유사 로컬 환경, `local-k8s/`) ✅ 2026-06-25.** 팀원이 노트북에서 AKS 동형으로 검증하는 kind 환경(균형 충실도). compose로는 불가능한 MVP 코어를 실제 k8s에서 증명:
> - **kind 멀티노드 + Calico** + 노드풀 라벨/taint(`system`/`sitl`/`satcom`). av-muav→sitl, datalink-satcom→satcom(taint+toleration) 배치 확인.
> - **신뢰경계** — `air`/`link`/`ground`/`c4i`/`soc` namespace + NetworkPolicy default-deny + 체인 허용. `verify-netpol.sh`로 **air→link 허용 / air→ground·c4i 차단** 실측 ✅.
> - **`av-muav` StatefulSet**(안정 식별, `kubectl scale`로 편대). entrypoint `--no-rebuild`로 런타임 재컴파일 OOM 해소.
> - ADR-0002 MVP 코어(namespace+NetworkPolicy+StatefulSet+노드풀)가 로컬에서 선검증됨 → AKS 이전 리스크 감소. Multus/OpenSAND는 "최대 충실도" 단계.
>
> ⏳ 남은 것: ① OpenSAND DVB-S2/RCS2 물리계층 + av-muav MAVLink 위성 터널링(+ Multus 이중 인터페이스), ② `satcom.ndjson`/`sar.ndjson`을 VM AMA/DCR(ext2)에 ingest 연결 → 라이브 `UAVSatcomLink_CL` 채우기, ③ Phase 3 AKS(`dah-sim-aks`) 이전(C-트랙 매니페스트 재사용).

---

## 1. 출발점 — 현재 무엇이 있는가

| 항목 | 현 상태 (`uav-sim-env` main) |
|---|---|
| 모사 기체 | MPD (Group 1, LOS only, quadplane) |
| 런타임 | 단일 VM `Standard_D4s_v5`(4 vCPU/16GB), Korea Central, docker-compose 13~14 컨테이너 |
| 배포 자동화 | `infra/main.bicep` + `cloud-init.yaml` + systemd(`uav-sim-env.service`: git pull → compose build → up) |
| 데이터 평면 | `dah-data-rg`(Log Analytics `dah-data-law` + Sentinel), AMA/DCR로 19개 `UAV*_CL` 테이블 |
| SOC 평면 | `dah-soc-rg`(AKS `dah-soc-aks` + ACR + AOAI), kagent + LangGraph(pollack-ai) |
| 활성 위협면 | S1(GNSS 스푸핑)·S4(펌웨어 변조)·A4(MAVLink 인젝션) |
| 비활성 위협면 | **S3(SATCOM MITM)** — LOS only라 칠 대상이 없음 |

> 핵심: SOC/데이터 평면(`dah-soc-rg`, `dah-data-rg`)에는 **이미 AKS가 존재**한다. 이번 확장은 *시뮬(시작 평면)* 을 VM에서 AKS로 옮기는 작업이며, 처음부터 AKS를 새로 도입하는 게 아니다.

---

## 2. 무엇이 바뀌어야 하는가 (MPD → KUS-FS)

`docs/muav-background.md` §3을 배포 관점으로 추린 변경 델타:

| 항목 | 현재(MPD) | 대상(KUS-FS) | 배포에 주는 영향 |
|---|---|---|---|
| 기체 frame | quadplane VTOL | 고정익 MALE(`-f plane`) | `av-muav` 신규 이미지 + persona `muav_male.parm` |
| 운용 대수 | 단일기 | 2~4대 편대 | SITL 다중 인스턴스 → **CPU 폭증** |
| 통신 | LOS only | **LOS(C-band) + SATCOM(Ku/Ka)** | `datalink-satcom`(OpenSAND ST/SAT/GW) 신규, privileged/tun-tap |
| 신규 구성요소 | — | 위성(ANASIS-II 추상)·위성지상국(Teleport), **`sar-stub`**(SAR 페이로드) | OpenSAND가 "+1 위성요소" 모사, sar-stub은 `UAVSarPayload_CL` 출처 |
| 신규 로그/테이블 | 19개 | **24개**(+`UAVSatcomLink_CL`·`UAVSarPayload_CL`·`UAVGcsAccess_CL`·`UAVRouterStats_CL`·`UAVFleetState_CL`) | 3번째 DCR(ext2, 5스트림) **라이브 배포 확인(2026-06-25)**, ingest 재산정 |
| 활성 위협면 | S1/S4/A4 | **+ S3(SATCOM MITM)**, + 편대 횡적확산, + 공군→육군 핸드오프 | 신뢰 경계(망분리)를 1급 객체로 |

**부하 추산(ADR-0001)**: 단일기 ~2.5–3.5 vCPU(D4s 적정) → 편대 2대+SATCOM ~5–7 vCPU → 편대 4대+Gazebo+SATCOM **~10–16+ vCPU**. → **D4s_v5로 확장 불가, AKS 필요.**

---

## 3. 최종 그림 — AKS 타깃 아키텍처

ADR-0002의 설계 원칙: 실제 UAS의 **① 신뢰 경계(망 분리) ② 기체별 독립 식별 ③ 이종 컴퓨팅 ④ 제약된 RF/위성 링크**를 쿠버네티스 1급 객체로 그대로 모사한다.

### 3.1 리소스 그룹 토폴로지 (3-RG 유지, 시뮬만 AKS로 이동)

```
dah-sim-rg   ← 변경: 현재 VM(MPD 시뮬) 가동 중 → 시뮬 전용 AKS(dah-sim-aks)로 이전
dah-data-rg  ← 유지: Log Analytics(dah-data-law) + Sentinel, 24개 테이블/3 DCR (라이브)
dah-soc-rg   ← 유지: dah-soc-aks(SOC AI 전용, kagent+LangGraph) + ACR + AOAI (라이브, Succeeded)
```

> **시뮬 클러스터 분리 — 결정됨 (2026-06-25, 별도 클러스터).** ADR-0002의 "SOC 평면을 시뮬 UAS 평면과 다른 네임스페이스/클러스터로 두어 out-of-band 관제 구조 모사" 원칙에 따라 **두 평면을 물리적으로 분리**한다.
> - **SOC 평면 = `dah-soc-aks`** (이미 라이브): UAV 방어용 AI SOC(kagent + LangGraph) 전용. **시뮬 워크로드를 여기 올리지 않는다.**
> - **시뮬 평면 = `dah-sim-aks`** (신규, `dah-sim-rg`): KUS-FS 편대/SATCOM 워크로드 전용. 현 VM 시뮬을 이 클러스터로 이전.
> 두 클러스터 경계가 곧 "관제↔피관제 / (확장 시)공군↔육군" 조직 경계 모사가 된다. 단일 클러스터 네임스페이스 합류안은 이 분리 결정으로 폐기.

### 3.2 네임스페이스 + NetworkPolicy (신뢰 경계 = default-deny)

```
namespace        포함 워크로드                         경계 규칙
─────────────────────────────────────────────────────────────────────────
air     av-muav(StatefulSet, MUAV-001..N)            air→ground 직접 불가.
                                                      datalink 서비스로만 egress
link    datalink-los, datalink-satcom(OpenSAND)      air↔ground 사이 유일 통로(게이트웨이)
ground  gcs-qgc, pgse/mps/weapon/auth/c4i-stub …     link 경유로만 air 도달
c4i     c4i-stub(ATCIS/MIMS) — 공군→육군 핸드오프      ground와 단일 게이트웨이로만 연결
soc     telemetry-tap(수집), (kagent/LangGraph)       out-of-band, 시뮬 평면과 분리
```

핵심 강제: **"공중→지상 경로는 RF 링크뿐"**. `air` Pod가 `ground`로 직행하지 못하고 `link`의 datalink Pod를 통해서만 통신하도록 default-deny + 화이트리스트. 공군→육군 핸드오프(`c4i`)도 단일 게이트웨이로 모델링 → **SOC가 감시할 조직 경계가 망 계층에 드러난다.**

### 3.3 기체별 식별 — AV = StatefulSet

- AV 1대 = Pod 1개. **StatefulSet**으로 안정 식별자 `MUAV-001..N` 부여(telemetry-tap이 `UAV_ID`로 일관 태깅).
- **편대 규모 = replica 수**(선언적 스케일). `kubectl scale statefulset av-muav --replicas=4`.
- liveness/readiness probe = 기체 건전성, PDB = 가용성.

### 3.4 이종 노드풀 (taint/toleration/nodeSelector)

| 노드풀 | 워크로드 | 사이징 가이드 | 특이사항 |
|---|---|---|---|
| `system` | AKS 시스템 + 스텁(FastAPI) | 2× D4s_v5 | 기존 soc.bicep 기본값과 동일 |
| `sitl` (CPU 최적화) | av-muav SITL(편대) | 기체당 ~1 vCPU(헤드리스) 기준, F-시리즈 또는 D8s_v5+ | 편대 4대면 4–8 vCPU 확보 |
| `satcom` (전용·privileged) | datalink-satcom(OpenSAND ST/SAT/GW) | 1~2+ vCPU/링크 | **privileged + tun/tap + Multus** — 최대 리스크, 격리 필수 |
| `gpu` (옵션) | Gazebo 시각화 | 시연 1대만 | D-시리즈는 소프트웨어 렌더 → 시연 시에만 |

### 3.5 이중 링크 — Multus CNI

현재 docker bridge 하나(`uas-los` 10.50.0.0/24)에 얹힌 구조를, AKS에서 AV Pod에 **두 개의 인터페이스**로 물리 분리:

```
                       ┌──────────────────────── air ns ────────────────────────┐
                       │  av-muav Pod (MUAV-001)                                 │
                       │   eth0 (default)                                        │
                       │   net-los   ──▶ datalink-los    (C-band, netem 저지연)   │
                       │   net-satcom ─▶ datalink-satcom (OpenSAND, ~600ms RTT)  │
                       └────────────────────────────────────────────────────────┘
   net-los   : 이착륙·근거리 통제 (기존 tc netem 50ms±5 / loss 1%)
   net-satcom: 종심 임무·영상 중계 (OpenSAND DVB-S2/RCS2 물리계층 에뮬, GEO 지연/대역/열화)
```

- 링크 열화·재밍은 **Cilium 대역폭/지연 정책 또는 netem 사이드카**로 인터페이스별 제어.
- 이렇게 해야 **S3(위성 경로 MITM)·LOS 재밍**이 *실제 망 계층*에서 재현된다(단순 파라미터 모사가 아님).

### 3.6 데이터/관측 평면 — 2차선 구조 (사이드카 vs DaemonSet)

> **라이브 검증 (2026-06-25, `dah-data-rg`/`dah-data-law`)**: 24개 `UAV*_CL` 테이블이 워크스페이스에 **실제 배포 확인**(IaC 정의만이 아님). DCR 3개 — `dah-data-uav-dcr`(10) / `dah-data-uav-dcr-extras`(9) / `dah-data-uav-dcr-ext2`(5) — 모두 존재, 스트림 수 일치. 신규 5개(`UAVSatcomLink_CL`·`UAVSarPayload_CL`·`UAVGcsAccess_CL`·`UAVRouterStats_CL`·`UAVFleetState_CL`) 포함. ⏳ *미검증*: 신규 테이블 실제 인입량(지난 24h), Sentinel 분석룰(S1/S3/S4/A4) 활성 여부 — 위 명령 §3·§4 미실행.

관측은 **성격이 다른 두 차선**을 분리해야 한다. 컨테이너 런타임 로그는 DaemonSet, 기체별 구조화 텔레메트리는 사이드카로 — 한 메커니즘으로 뭉뚱그리지 않는다.

| 차선 | 무엇을 | 수집기 | 도착 테이블 | 사이드카 |
|---|---|---|---|---|
| **(1) 런타임/인프라** | 모든 Pod의 stdout/stderr + k8s 인벤토리·리소스·이벤트 | **Container Insights DaemonSet**(`ama-logs`, 노드당 1개) | `ContainerLogV2`, `KubePodInventory`, `KubeEvents`, `ContainerInventory`, `InsightsMetrics` | ❌ |
| **(2) 기체별 텔레메트리** | 특정 AV의 MAVLink 스트림(구독·태깅) | **telemetry-tap 사이드카**(AV Pod당) | `UAVTelemetry_CL` 외 6분기 + 신규 `UAVSatcomLink_CL` | ✅ |

**(1) 왜 DaemonSet인가 — 사이드카 불필요.** Container Insights를 켜면(=`soc.bicep`의 `workspaceId` 전달, monitoring addon) `ama-logs`가 **노드당 1개**로 떠서 그 노드의 모든 컨테이너 stdout/stderr를 자동 수집한다. "컨테이너 런타임 로그"는 이 경로로 전부 들어오며 컨테이너마다 사이드카를 붙일 필요가 없다.

> **docker.sock 스텁 대체**: 현 VM의 `service-audit`/`datalink-stats`는 `/var/run/docker.sock`을 폴링해 lifecycle·리소스·연결을 직접 긁는다. **AKS는 containerd라 docker.sock이 없다.** 그 가시성은 위 DaemonSet의 `KubePodInventory`/`KubeEvents`/`ContainerInventory`/`InsightsMetrics`가 네이티브로 대체하므로, 두 스텁은 AKS에서 **제거 또는 재작성**(k8s API watch 기반) 대상이다.

**(2) 왜 telemetry-tap만 사이드카인가 — 기능적 이유.** telemetry-tap은 단순 로그 수집기가 아니라 **특정 AV의 MAVLink UDP를 구독**하는 애플리케이션이다. "AV 1대 = Pod 1개" 모델에서 각 AV Pod에 사이드카로 붙이면 ① 그 기체 링크만 구독하고 ② Pod의 `UAV_ID=MUAV-00N`로 일관 태깅된다 → DaemonSet으로 대체 불가.

**(2)의 NDJSON → 커스텀 `UAV*_CL` 적재 경로(스키마 보존).** Sentinel 룰이 19개 `UAV*_CL` 스키마에 의존하므로:
- **(권장)** 사이드카가 **Logs Ingestion API → DCR → `UAV*_CL`**로 직접 송신, 또는 telemetry-tap 옆 Fluent Bit가 emptyDir 파일을 tail해 송신.
- **(대안·비권장)** stdout으로 뱉어 `ContainerLogV2`에 싣고 DCR transform/KQL로 파싱 — 테이블 스키마가 뭉개짐.

`datalink-satcom`의 `satcom.ndjson`(→ `UAVSatcomLink_CL`)과 스텁들의 `*.ndjson`도 (2)와 동일하게 Fluent Bit/Logs Ingestion 경로를 탄다.

```
[차선1 런타임] 모든 Pod stdout ─▶ ama-logs DaemonSet ─▶ ContainerLogV2 / Kube*
[차선2 텔레메트리]
  av-muav(air) ─MAVLink─▶ telemetry-tap 사이드카 ─┐
  datalink-satcom ── satcom.ndjson ───────────────┤ Fluent Bit / Logs Ingestion API
  스텁들(ground/c4i) ── *.ndjson ──────────────────┤        → DCR
                                                   ▼
                          dah-data-law (Log Analytics + Sentinel)  ✅ 24개 테이블 라이브 확인 2026-06-25
                            총 24개 UAV*_CL = 기존 19 + 신규 5
                            ├ dah-data-uav-dcr       (10 스트림) ✅
                            ├ dah-data-uav-dcr-extras (9 스트림) ✅
                            └ dah-data-uav-dcr-ext2   (5 스트림, KUS-FS 확장) ✅
                                                   ▼
                          Sentinel 룰 (S1/S3/S4/A4 …) → pollack-ai LangGraph(kagent)
```

**신규 5개 테이블(KUS-FS 확장, `docs/sentinel-schemas.md §20` — `tables.bicep`+`dcr-ext2.bicep`+`vm-monitoring.bicep`에 정의 완료):**

| 테이블 | 출처 | 위협면/의의 | AKS 수집 차선 |
|---|---|---|---|
| `UAVSatcomLink_CL` | `datalink-satcom`(OpenSAND) `satcom.ndjson` | **S3** SATCOM MITM·세션 하이재킹·재밍(seq/session/integrity/rtt/jam) | (2) 사이드카/Fluent Bit |
| `UAVSarPayload_CL` | `sar-stub` NDJSON | SAR 표적조작·영상유출·비정상 수집 | (2) Fluent Bit |
| `UAVGcsAccess_CL` | `gcs-qgc` noVNC/VNC 접속 로그 | 조종 콘솔 원격접속 감사(현행 사각지대) | (2) Fluent Bit |
| `UAVRouterStats_CL` | `datalink-los` mavlink-router 내부 통계 | malformed MAVLink·드롭·라우팅 실패(인젝션 정황) | (2) Fluent Bit |
| `UAVFleetState_CL` | (선택) 편대 요약 | 편대 횡적확산 — KQL 분석룰 우선, 부하 시만 신설 | (2) 또는 분석룰 |

> DCR당 **10-logFiles 한계** 때문에 primary(10)/extras(9)/ext2(5)로 3분할. ext2가 KUS-FS 확장분을 묶는다. 라이브 반영은 `scripts/full-ingest.sh`(az 인증 환경).
>
> AKS 이전 시 주의: 기존 19개 중 `UAVServiceAudit_CL`·`UAVResourceMetrics_CL`·`UAVDatalinkConn_CL`·`UAVDatalink_CL`은 docker.sock 기반(`service-audit`/`datalink-stats`) → **차선1(Container Insights)으로 흡수**되어 수집 경로가 바뀐다. 반면 신규 `UAVRouterStats_CL`은 라우터 자체 로그파일 기반이라 차선2로 유지된다.

> ingest 비용: 현재 일일 캡 1GB. 편대 + SATCOM이면 **두 차선 모두** 기체 수에 비례 증가(특히 `ContainerLogV2`가 의외로 큼) → **DCR 사이징·일일 캡·보존기간 재산정 필수**(ADR-0001 후속). 비용 민감 시 `ContainerLogV2`는 네임스페이스/`Basic Logs` 티어로 분리 검토.

### 3.7 운용 — GitOps + (고급) Fleet 오퍼레이터

- 컴포넌트별 **Helm 차트** + **ArgoCD/Flux** 선언적 배포("편대 구성 변경 = Git PR", 감사 가능).
- **고급**: `kind: UAV` CRD(기체 ID·persona·페이로드·링크 구성 선언) + Fleet 오퍼레이터가 SITL Pod·persona·링크 인터페이스를 자동 정합화. kagent와 결합.
- 공급망/인증: Pod Security(restricted) + 이미지 서명(cosign) + 승인제어(Kyverno/Ratify) + Key Vault CSI → S4·인사이드 위협면과 연결.

---

## 4. 단계별 배포 계획 (Bridge → AKS)

ADR-0001의 "단기 가교 → 본격 AKS" 노선을 배포 순서로 구체화. 각 단계는 독립 검증 가능한 산출물을 남긴다.

### Phase 2a — 데이터 평면 선확장 (위험 낮음, 먼저) ✅ 라이브 배포 확인 (2026-06-25)

목표: SATCOM/편대 스키마를 미리 깔아두어 컴퓨트 작업과 병렬화. **상태: 신규 5개 테이블 + 3번째 DCR(ext2)이 라이브 워크스페이스에 배포 확인됨** (24개 `UAV*_CL` 존재, DCR 10/9/5 일치).

1. **(완료·확인)** `tables.bicep` + `dcr-ext2.bicep` + `vm-monitoring.bicep` → 총 24개 `UAV*_CL` 라이브 배포(`docs/sentinel-schemas.md §20`).
2. ⏳ **(미검증)** 신규 테이블 실제 인입량(지난 24h) + Sentinel 분석룰(S1/S3/S4/A4) 활성 여부 — 데이터가 흐르는지 확인 필요.
3. 일일 ingest 캡·보존기간을 편대 규모로 재산정(차선1 `ContainerLogV2` 포함).

### Phase 2b — 단일 VM 가교 (D8s_v5 수직확장) — *선택적, 빠른 검증용*

목표: AKS 셋업 전에 편대 2대 + SATCOM을 compose 그대로 굴려 컴포넌트 자체를 검증.

1. `main.bicep` VM SKU `D4s_v5 → D8s_v5`(8 vCPU/32GB).
2. compose에 `av-muav`(헤드리스, Gazebo는 시연 1대만) + `datalink-satcom`(OpenSAND, 전용 네트워크 네임스페이스) 추가.
3. 컨테이너별 **cpu/mem limit 도입**(현재 무제한 → SITL 폭주 방지).
4. 한계: 단일 장애점, OpenSAND 네트워킹이 호스트 공유. **MVP 검증 후 폐기 전제.**

> 편대 2대 MVP가 AKS보다 급하면 여기서 멈춰도 데모는 가능. 본 청사진의 최종 타깃은 어디까지나 Phase 3.

### Phase 3 — AKS 이전 (본격, 최종 그림)

선행 PoC(가장 먼저, 규모와 무관하게): **OpenSAND on k8s 네트워킹** — privileged·tun/tap·Multus CNI 동작 검증. 여기가 전체에서 최대 리스크다.

1. **클러스터**: `dah-sim-aks` 신설(또는 `dah-soc-aks` 네임스페이스 합류). `soc.bicep` 패턴 재사용(ACR `AcrPull` 자동, Container Insights → dah-data-law).
2. **노드풀**: `system` / `sitl`(CPU) / `satcom`(privileged 전용) / `gpu`(옵션) 생성, taint·label 부여.
3. **네트워킹**: Multus 설치 → NetworkAttachmentDefinition `net-los`·`net-satcom`. Cilium/netem로 링크 품질.
4. **네임스페이스 + NetworkPolicy**: `air/link/ground/c4i/soc` default-deny + 화이트리스트.
5. **워크로드 전환**: compose 서비스 → Helm 차트.
   - `av-muav`: StatefulSet(replica=편대), `sitl` 노드풀, 이중 인터페이스, `UAV_ID=MUAV-00N`.
   - `datalink-los` / `datalink-satcom`: `link` ns, satcom은 `satcom` 노드풀(privileged).
   - 스텁들: `ground`/`c4i` ns. **telemetry-tap: 각 av-muav Pod의 사이드카**(기체별 MAVLink 구독·태깅). `service-audit`/`datalink-stats`는 제거 — Container Insights DaemonSet으로 흡수.
   - **관측 2차선**(§3.6): 런타임 로그 = Container Insights DaemonSet(addon, `workspaceId`), 기체별 텔레메트리 = 사이드카 → Fluent Bit/Logs Ingestion → `UAV*_CL`.
6. **이미지**: ACR에 사전 빌드·푸시(`docker compose build`를 VM에서 도는 30분 문제 해소) → `imagePullPolicy`로 당김.
7. **GitOps**: ArgoCD/Flux 연결. (고급) `kind: UAV` CRD + Fleet 오퍼레이터.
8. **카오스/실패 주입 검증**: datalink Pod kill 또는 netem 100% loss → 기체 failsafe(RTL) 유발로 비상거동 확인.

### Phase 3+ — 고급 (필요 시)

멀티클러스터 조직 분리(공군 자산 망 vs 육군 소비), UAV CRD/Fleet 오퍼레이터 완성, 이미지 서명·승인제어 전면화.

---

## 5. 배포 시퀀스 (명령 레벨 스케치)

기존 `infra/README.md`의 3-RG 순서를 따르되 시뮬 레이어를 AKS로 대체:

```bash
# 1) 데이터 레이어 (SATCOM 테이블 포함, 먼저)
az group create -n dah-data-rg -l koreacentral
az deployment group create -g dah-data-rg -f data.bicep -n data-mvp \
  -p retentionInDays=90        # ingest 캡/보존 재산정

# 2) SOC 레이어 (기존 유지, 데이터 출력 의존)
WORKSPACE_ID=$(az deployment group show -g dah-data-rg -n data-mvp \
  --query properties.outputs.workspaceId.value -o tsv)
az group create -n dah-soc-rg -l koreacentral
az deployment group create -g dah-soc-rg -f soc.bicep -n soc-mvp \
  -p workspaceId="$WORKSPACE_ID"

# 3) 시뮬 레이어 — AKS (신규 sim.bicep, soc.bicep 패턴 확장)
#    노드풀 분리(system/sitl/satcom[/gpu]) + workspaceId 전달
az group create -n dah-sim-rg -l koreacentral
az deployment group create -g dah-sim-rg -f sim.bicep -n sim-aks \
  -p workspaceId="$WORKSPACE_ID"

# 4) 클러스터 진입 + 플랫폼 설치
az aks get-credentials -g dah-sim-rg -n dah-sim-aks --overwrite-existing
kubectl apply -f https://raw.githubusercontent.com/k8snetworkplumbingwg/multus-cni/master/deployments/multus-daemonset.yml   # Multus
# NetworkAttachmentDefinition(net-los/net-satcom), NetworkPolicy, StatefulSet, Helm 차트 적용
```

> `sim.bicep`은 신규 산출물(현 `main.bicep`/`cloud-init.yaml`를 대체). `soc.bicep`이 이미 AKS+ACR+Container Insights 패턴을 갖고 있으므로 이를 확장해 노드풀만 추가하는 것이 가장 빠르다.

---

## 6. 비용·운영 고려

| 항목 | 현재(VM) | AKS 타깃 | 메모 |
|---|---|---|---|
| 컴퓨트 | D4s_v5 단일 ≈ 월 ₩200k | system 2×D4s + sitl + satcom 노드풀 | 편대 규모로 가변. 미사용 노드풀 0 스케일/Spot로 절감 |
| 데이터 | 일 1GB 캡 | 기체 수 비례 ↑ | DCR 사이징·캡 재산정 필수 |
| 첫 부팅 | VM 안 build ~30분 | ACR 사전 푸시 → pull | build 병목 제거 |
| 가용성 | SLA 없음(단일 VM) | replica/PDB/probe | 편대·관제 복원력 확보 |

비용 안전선: `sitl`/`satcom` 노드풀에 **cluster-autoscaler + Spot**, 데모 외 시간은 `az aks nodepool scale --node-count 0`.

---

## 7. 리스크 & 선결 과제

| 리스크 | 영향 | 대응 |
|---|---|---|
| **OpenSAND on k8s**(privileged·tun/tap·Multus CNI) | 전체 일정 최대 난점 | **규모와 무관하게 가장 먼저 단독 PoC**(ADR-0001/0002 공통 지시) |
| SITL 편대 CPU 폭증 | 관측/관제 계층 자원 고갈 | 노드풀 분리 + resource requests/limits(현 무제한 해소) |
| ingest 비용 폭증 | Log Analytics 과금 | DCR/캡/보존 기체 수 기준 재산정 |
| compose→Helm 전환 공수 | 일정 | soc.bicep/ACR 재사용, 컴포넌트별 차트 점진 전환 |
| 멀티클러스터 복잡도 | 운영 부담 | MVP는 네임스페이스 분리, 멀티클러스터는 고급 단계 보류 |

**선결(Follow-ups, ADR 종합)**: ① OpenSAND+Multus 노드풀 PoC, ② `UAVSatcomLink_CL`/`UAVSarPayload_CL` 배포, ③ `muav_male.parm` persona + 헤드리스 av-muav 이미지, ④ namespace/NetworkPolicy 토폴로지(air/link/ground/c4i/soc) 정의, ⑤ `kind: UAV` CRD 초안.

---

## 8. 완료 정의 (Definition of Done)

KUS-FS 시뮬이 AKS에서 "최종 그림"으로 동작한다고 말할 수 있는 기준:

1. `kubectl scale`로 편대 2~4대를 선언적으로 띄우고 각 기체가 `MUAV-00N`으로 식별·태깅된다.
2. AV Pod가 `net-los`·`net-satcom` 두 인터페이스를 갖고, 위성 경로에서 ~600ms RTT가 관측된다.
3. NetworkPolicy로 `air`→`ground` 직행이 차단되고 datalink 게이트웨이로만 통신한다.
4. `datalink-satcom`이 `UAVSatcomLink_CL`(seq/session_id/integrity_status/rtt_ms/jam_indicator)을 Sentinel에 적재한다.
5. **S3(SATCOM MITM)** 시나리오(무결성 위반·세션 하이재킹·재밍)가 실제로 트리거되고 Sentinel 룰이 탐지한다.
6. datalink Pod kill → 기체 failsafe(RTL) 카오스 실험이 통과한다.

---

## 9. 관련 문서

- 배경·통신: `docs/muav-background.md`
- +1 위성요소/OpenSAND: `docs/uas-detail-6-satcom.md`
- 컴포넌트 상세·현 인프라: `docs/components.md`
- AKS 이전 결정: `docs/adr/0001-fleet-satcom-runtime-aks.md`
- AKS 타깃 원칙: `docs/adr/0002-aks-target-architecture.md`
- 배포 자동화(현행): `infra/README.md`, `infra/*.bicep`, `infra/cloud-init.yaml`
- (위임) 신규 컴포넌트 내부 설계: `pollack-ai/docs/uav-sim-muav-migration.md`
