# ADR 0001 — 편대 + SATCOM 확장 런타임: AKS 이전

- **상태**: Accepted
- **일자**: 2026-06-23
- **관련**: `docs/opensource-uas-mapping.md`, `docs/uas-detail-6-satcom.md`, `pollack-ai/docs/uav-sim-muav-migration.md`(Phase 3), `CLAUDE.md`(kagent/AKS)

---

## 배경 (Context)

현재 `uav-sim-env`는 **단일 Azure VM(`Standard_D4s_v5`, 4 vCPU / 16 GB)** 위에 docker-compose로 14개 컨테이너를 올린 구조다. 컨테이너별 리소스 제한은 없고, `NET_ADMIN`은 `datalink-los`(tc netem) 하나뿐이다. 이 구성은 **현재의 단일기·LOS 환경에는 적정**하다.

그러나 KUS-FS급 확장은 두 가지 무거운 변화를 가져온다:

1. **편대 비행(2~4대)** — av-muav SITL 다중 인스턴스. SITL은 인스턴스당 ~1 vCPU. Gazebo를 기체마다 붙이면(D-시리즈 GPU 없음, 소프트웨어 렌더) 인스턴스당 +1~2 vCPU로 폭증.
2. **SATCOM(`datalink-satcom`, OpenSAND)** — ST/SAT/GW 다중 프로세스 + 물리계층 에뮬(1~2+ vCPU). tun/tap·자체 IP 주소체계를 써서 docker bridge와 충돌 소지가 크고 `NET_ADMIN`/privileged 요구.

추가로 telemetry-tap/NDJSON 볼륨이 기체 수에 비례해 증가한다.

### 부하 추산
- 현재(단일기): ~2.5~3.5 vCPU → 4 vCPU에 적합.
- 편대 2대 + SATCOM(편대 헤드리스): ~5~7 vCPU.
- 편대 4대 + Gazebo 시연 + SATCOM: ~10~16+ vCPU.

→ **D4s_v5로는 확장 불가.**

---

## 검토한 대안 (Options)

| 옵션 | 적합 범위 | 장점 | 단점/리스크 |
|---|---|---|---|
| (a) VM 수직확장 (D8s_v5→D16s_v5) | 편대 2~4대 MVP | compose 그대로, 단순·빠름 | 단일 장애점·blast radius, OpenSAND 네트워킹 공유 호스트 부담 |
| (b) 역할별 다중 VM | 중간 규모 | OpenSAND 격리, 장애 분리 | VM간 네트워킹·ingest 설정↑, AKS 전 단계로는 과함 |
| **(c) AKS 이전** | **4대+/스웜(Phase 3)** | pod replica 편대 스케일, 노드풀 분리, resource limit·NetworkPolicy, 이미 스택에 kagent/AKS 존재 | 셋업 부담, OpenSAND를 k8s에 올리려면 privileged/Multus CNI 필요 |

---

## 결정 (Decision)

**본격 확장은 (c) AKS 이전으로 간다.**

- av-muav를 **pod replica**로 편대 스케일아웃, 각 기체에 `uav_id`(예: `MUAV-001..004`) 일관 태깅.
- **노드풀 분리**: SITL용 컴퓨트 최적화 노드풀 / OpenSAND 전용 노드풀.
- **resource requests·limits**로 SITL이 탭·스텁 리소스를 굶기지 않도록 보장(현재 무제한 문제 해소).
- **NetworkPolicy**로 편대·링크·관제 경계 격리, 편대별 식별.
- 이는 `CLAUDE.md`(kagent/AKS)와 마이그레이션 설계서 **Phase 3(AKS 이전)** 방향과 일치한다.

### 단기 가교 (본격 이전 전까지)
편대 2대 MVP가 AKS보다 먼저 필요하면 임시로 (a) **D8s_v5 수직확장**으로 버티되, ① 편대 SITL 헤드리스(Gazebo는 시연용 1대만), ② 컨테이너별 cpu/mem limit 도입, ③ OpenSAND 네트워킹은 전용 네임스페이스로 격리한다.

---

## 결과 (Consequences)

**긍정**
- 편대 규모 확장이 선언적(replica 수)으로 가능.
- 리소스 격리로 SITL 폭주가 관측/관제 계층을 굶기는 문제 해소.
- 노드풀 분리로 OpenSAND의 특수 네트워킹·권한을 다른 워크로드와 격리.

**부담/주의**
- **OpenSAND on k8s가 최대 리스크** — tun/tap·privileged·Multus CNI 필요. 편대 규모와 무관하게 **이 부분만 일찍 PoC로 검증**할 것.
- AMA/DCR 사이징과 Sentinel ingest 비용을 기체 수에 맞춰 재산정.
- compose→AKS 매니페스트 전환 작업, 이미지 레지스트리(ACR) 정비 필요.

---

## 후속 작업 (Follow-ups)
- OpenSAND k8s 네트워킹 PoC (privileged/Multus).
- 추가 테이블(`UAVSatcomLink_CL`, `UAVSarPayload_CL`) 배포 (`docs/sentinel-schemas.md` §20).
- av-muav 헤드리스 SITL 이미지 + persona `muav_male.parm`.
- 편대 telemetry 볼륨 기준 DCR/비용 재산정.
