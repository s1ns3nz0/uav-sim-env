# UAV SOC 시뮬레이션 — 컴포넌트 상세 문서

이 문서는 `uav-sim-env` 프로젝트에 들어있는 모든 컴포넌트가 **무엇을 모사하는지, 왜 필요한지, 어떻게 동작하는지, 어디에 데이터가 흘러가는지**를 정리한 것.

> **읽는 사람**: 프로젝트 합류자 / 발표 자료 작성자 / 시연 운영자
> **소스 코드**: `https://github.com/s1ns3nz0/uav-sim-env`
> **데모 접속**: `http://sim.pollak.store:8080/vnc.html`

---

## 0. 큰 그림 — UAS 5대 구성요소 + 보조 시스템

미 육군 교범 **FMI 3-04.155** 는 UAS(Unmanned Aircraft System)를 5개 구성요소의 집합으로 정의:

```
AV (Air Vehicle)
   비행체 + 페이로드 + GPS/INS/IFF
        │
        │ RF link
        ▼
Data Link  ──→  GDT  ──→  GCS  ──→  PGSE
LOS/BLOS       지상안테나   통제소     발사·정비·회수
```

우리는 위 5개 모두에 더해 **방산 작전 환경에서 실제로 필요한 보조 시스템** (임무계획·C4I·태세·정비·인증·무장·위협정보) 까지 모사한다.

| 영역 | FMI 정의 | 우리 컴포넌트 |
|---|---|---|
| AV | 비행체 + 페이로드 | `av-mpd` (ArduPilot SITL + Gazebo) |
| Data Link | LOS C-band / BLOS Ku-Ka | `datalink-los` (mavlink-router + tc netem) |
| GDT | 지상 RF 안테나 | `datalink-los`에 통합 (UDP 프록시 모사) |
| GCS | 임무계획·조종·영상분석 | `gcs-qgc` (QGroundControl + noVNC) |
| PGSE | 발사·정비·회수 장비 | `pgse-stub` (FastAPI) |
| **MPS** (보조) | 임무계획 시스템 | `mps-stub` (FastAPI) |
| **C4I** (보조) | ATCIS/MIMS | `c4i-stub` (FastAPI) |
| **Cyber Posture** (보조) | 사이버위협태세 | `cyber-posture-stub` (FastAPI) |
| **Weapon** (보조) | 무장 통제 | `weapon-stub` (FastAPI) |
| **Threat Intel** (보조) | TI 피드 | `ti-stub` (FastAPI) |
| **Auth** (보조) | 운영자 인증 | `auth-stub` (FastAPI) |
| 관측·로그 | (FMI 외 SOC용) | `telemetry-tap`, `datalink-stats`, `service-audit` |

이 모든 컴포넌트는 Docker Compose 한 묶음으로 한 호스트(Azure VM)에서 동작.

---

## 1. av-mpd — Air Vehicle

### 1.1 한 줄
ArduPilot SITL이 진짜 자율비행 펌웨어를 PC 안에서 그대로 돌리는 컨테이너. **LIG Nex1 MPD** (소형 정찰·타격 복합형 드론) 페르소나로 설정.

### 1.2 컴포넌트
- **ArduPilot SITL** — 실기체용 펌웨어 코드(`arduplane`)를 PC에서 시뮬용 빌드. **실기체와 동일한 자율비행 알고리즘**.
- **Gazebo Garden** — 물리 엔진 + 3D 시각화 (옵션, 무인 비행 시각화).
- **MPD persona** — `persona/mpd_quadplane.parm` 파일이 ArduPilot의 파라미터(MTOW, 추력, 배터리, EO/IR 짐벌 채널, 자폭탄 서보)를 MPD에 맞게 오버라이드.

### 1.3 왜
실기체 사면 비싸고 위험. SITL은 펌웨어 코드가 같으므로 **여기서 잡힌 취약점이 곧 실기체 취약점**. 시연 설득력 ↑.

### 1.4 동작 흐름
1. 컨테이너 시작 → `sim_vehicle.py --vehicle ArduPlane --frame quadplane --wipe-eeprom`
2. SITL이 가상 IMU/GPS/배럴미터/모터 신호 생성, TCP 5760에 MAVLink 서버 오픈
3. `bootstrap.py`가 35초 후 mavlink-router 통해 `ARMING_CHECK=0` + `MISSION_CURRENT=0` PARAM_SET (SITL 데모 편의)
4. MAVLink가 datalink-los → gcs-qgc로 흐름

### 1.5 노출 포트
| 포트 | 프로토콜 | 용도 |
|---|---|---|
| 5760 | TCP | ArduPilot SITL primary MAVLink (mavlink-router가 클라이언트로 접속) |

### 1.6 어디에 데이터가 흘러감
- MAVLink 메시지 전체 → datalink-los → telemetry-tap → `UAVTelemetry_CL`
- 파생: `UAVOperator_CL`, `UAVMissionEvent_CL`, `UAVFailsafe_CL`, `UAVConfigAudit_CL`, `UAVMavsec_CL`, `UAVImagery_CL`

### 1.7 시연 시 사용자 입장
조종사가 GCS(QGC)에서 모드 변경 / Arm / 미션 시작하면 SITL이 가상 비행. 시각적으로는 QGC 지도 위 차량 아이콘 이동.

---

## 2. datalink-los — Data Link + GDT

### 2.1 한 줄
**mavlink-router**가 SITL과 GCS 사이의 MAVLink 패킷을 라우팅. **tc netem**으로 RF 링크의 지연·손실 시뮬.

### 2.2 컴포넌트
- **mavlink-router** (Solo.io / pulse) — TCP 5760 (SITL) ↔ UDP 14550 (GCS) ↔ UDP 14552 (tap) ↔ TCP 5790 (외부 접근) 라우팅.
- **tc netem** — Linux 트래픽 컨트롤로 지연 50ms ± 5ms + 패킷 손실 1% 인위적 주입 ("산악 LOS" 모사).

### 2.3 왜
실제 UAV는 무선 링크가 완벽하지 않음. RF는 노이즈, 거리에 따른 약화, 잠시 끊김이 일상. 그걸 안 모사하면 시뮬이 비현실적.

또 mavlink-router를 분리하면 **외부 도구**(red team의 MAVProxy, pymavlink)도 동일 포트(5790)로 접속 가능 → 공격 시연 가능.

### 2.4 동작 흐름
1. 컨테이너 시작 → tc netem 적용 (`eth0`에 지연 50ms 주입)
2. mavlink-router가 `mavlink-router.conf` 로 SITL(TCP 5760)에 TCP 클라이언트로 접속
3. UDP 14550으로 GCS 송출, UDP 14552로 tap 송출, TCP 5790으로 외부 노출
4. 30초마다 라우팅 통계 stdout에 출력

### 2.5 노출 포트
| 포트 | 프로토콜 | 용도 |
|---|---|---|
| 14550 | UDP | QGC autoconnect용 GCS 채널 |
| 14552 | UDP | telemetry-tap 채널 |
| 5790 | TCP | **외부(red team) MAVLink 접속점** (A4 공격면) |

### 2.6 어디에 데이터가 흘러감
- 라우터 자체 통계 → datalink-stats가 docker stats로 수집 → `UAVDatalink_CL`, `UAVResourceMetrics_CL`
- 라우터 TCP 5790 활성 연결 → `UAVDatalinkConn_CL`

### 2.7 공격면
- **A4 (MAVLink 평문 인젝션)** 의 진입점. 5790 TCP로 누구나 MAVLink 패킷 보낼 수 있음 (현재 인증 없음).

---

## 3. gcs-qgc — Ground Control Station

### 3.1 한 줄
**QGroundControl(QGC)** 을 헤드리스 Xvfb + 웹 noVNC로 띄워서 **브라우저만으로 조종사 콘솔에 접속** 가능.

### 3.2 컴포넌트
- **QGroundControl 4.4.4** AppImage (x86_64). squashfs 직접 추출해서 컨테이너에 박음.
- **Xvfb** — X 가상 디스플레이 (`:0`).
- **fluxbox** — 최소 윈도우 매니저.
- **x11vnc** — X 화면을 VNC로 노출.
- **websockify + noVNC** — VNC를 웹 브라우저용 WebSocket으로 변환.
- **supervisord** — 위 모두 한 컨테이너 안에서 동시 실행.

### 3.3 왜
KGCS(국군 표준 GCS)는 비공개 → 오픈소스 QGC가 사실상 동일 기능. QGC를 컨테이너로 띄우면 팀원 누구나 로컬에 설치 안 하고 브라우저로 접속.

### 3.4 동작 흐름
1. 컨테이너 시작 → supervisord가 Xvfb → fluxbox → x11vnc → noVNC → QGC 순서로 띄움
2. QGC가 UDP 14550 autoconnect로 mavlink-router에서 차량 정보 받음
3. 사용자가 `http://sim.pollak.store:8080/vnc.html` 접속 → noVNC → 데스크탑 화면 (QGC)
4. 미션 업로드 / 모드 변경 / Arm 등 사용자 액션 → MAVLink로 차량에 전달

### 3.5 노출 포트
| 포트 | 프로토콜 | 용도 |
|---|---|---|
| 8080 | HTTP/noVNC | **브라우저 접속** |
| 5900 | VNC | raw VNC (디버깅용) |

### 3.6 미션 파일
`/home/qgc/missions/mpd_recon.plan` — 정찰 미션:
1. VTOL 이륙 (30m)
2. 천이 비행 (waypoint 2, 3)
3. ROI 락온 (37.5410, 127.0310)
4. 30초 호버 관측
5. ROI 해제
6. 이탈 + 홈 복귀
7. VTOL 착륙

### 3.7 어디에 데이터가 흘러감
- 사용자 액션(Arm/모드/미션) → MAVLink → telemetry-tap → `UAVOperator_CL`, `UAVMissionEvent_CL`

### 3.8 자세한 사용법
→ [`qgc-novnc-guide.md`](./qgc-novnc-guide.md)

---

## 4. telemetry-tap — 관측 / 적재

### 4.1 한 줄
**pymavlink**가 MAVLink UDP 14552를 구독해서 모든 메시지를 JSON으로 풀어 NDJSON 파일로 떨굼. 6개 분기로 필터링.

### 4.2 왜
공격자가 MAVLink로 차량과 대화하는 모든 흔적을 SOC가 보려면, 라우터를 거쳐가는 모든 메시지를 누군가가 **구조화된 형태**로 잡아둬야 함. 그 역할.

### 4.3 6개 파일 (각각 다른 분기)
| 파일 | 무엇 |
|---|---|
| `telemetry.ndjson` | 모든 MAVLink 메시지 (raw, 67 필드) |
| `operator.ndjson` | 운영자 명령만 필터 (COMMAND_LONG 등) |
| `mission.ndjson` | 미션 라이프사이클 파생 (takeoff/waypoint/land) |
| `failsafe.ndjson` | STATUSTEXT severity ≤4 + RTL/Land 모드 전이 |
| `config-audit.ndjson` | PARAM_VALUE 변화 추적 (이전 값 vs 새 값) |
| `imagery.ndjson` | 카메라/짐벌 메시지 (CAMERA_TRIGGER 등) |
| `mavsec.ndjson` | 30초 윈도우 MAVLink 서명 카운트 |

### 4.4 어디에 데이터가 흘러감
6개 파일 각각 → Azure Monitor Agent → DCR → 대응 테이블:
- `UAVTelemetry_CL`, `UAVOperator_CL`, `UAVMissionEvent_CL`, `UAVFailsafe_CL`, `UAVConfigAudit_CL`, `UAVImagery_CL`, `UAVMavsec_CL`

### 4.5 핵심 입력 (SOC 룰)
- `MsgType == "EKF_STATUS_REPORT"`의 PosHorizVariance → **S1 GNSS 스푸핑**
- `MsgType == "COMMAND_LONG"`의 Command 패턴 → **A4 MAVLink 인젝션**

---

## 5. pgse-stub — Payload & Ground Support Equipment

### 5.1 한 줄
실제 PGSE(발사 카타펄트·정비공구·회수 그물)의 **디지털 결정 표면**을 FastAPI로 모사. 펌웨어 검증·발사 승인·정비 이력.

### 5.2 왜
공급망 변조(S4 시나리오)의 핵심은 **"승인된 펌웨어인지 확인하는 절차"**가 가짜 결정을 내리도록 만드는 것. 그 절차를 모사하려면 우리가 그 절차를 갖고 있어야 함.

### 5.3 엔드포인트
| 메소드 + 경로 | 동작 |
|---|---|
| `GET /armory/firmware/{uav_id}` | 승인된 펌웨어 해시 조회 |
| `POST /preflight/check` | 제출된 펌웨어 해시 + SBOM 검증 |
| `POST /launch/authorize` | preflight 통과 시 단기 발사 토큰 발급 |
| `GET /launch/token/{token}` | 토큰 유효성 검증 |
| `POST /maintenance/battery/cycle` | 배터리 사이클 기록 |
| `POST /maintenance/calibration` | 센서 캘리브레이션 |
| `POST /maintenance/inspection/sign` | 점검표 서명 |
| `GET /docs` | Swagger UI |

### 5.4 노출 포트
- 8000 TCP

### 5.5 어디에 데이터가 흘러감
- `/preflight`, `/launch`, `/armory` → `pgse.ndjson` → `UAVPgse_CL`
- `/maintenance/*` → `maintenance.ndjson` → `UAVMaintenance_CL`

### 5.6 공격면
- **S4**: 제출 펌웨어 해시 변조 → `Passed=false` 이벤트 발생
- **S4**: SBOM에 `unsigned/*` 컴포넌트 포함 → `SbomForbiddenCount > 0`

---

## 6. mps-stub — Mission Planning System

### 6.1 한 줄
임무계획(DRAFT → APPROVED → RELEASED) 워크플로우 + **2-person 룰 강제**.

### 6.2 왜
방산 작전에서 무인기 임무는 한 사람이 마음대로 못 띄움. 계획자 ≠ 승인자 ≠ 릴리스자. 이 절차를 모사 + 위반 시도를 SOC가 탐지.

### 6.3 엔드포인트
| 메소드 + 경로 | 동작 |
|---|---|
| `POST /plans` | 임무계획 생성 (DRAFT) |
| `GET /plans/{id}` | 계획 조회 |
| `POST /plans/{id}/approve` | 승인 (계획자 != 승인자 강제) |
| `POST /plans/{id}/release` | APPROVED만 RELEASE 가능 |

### 6.4 노출 포트
- 8100 TCP

### 6.5 어디에 데이터가 흘러감
- `mps.ndjson` → `UAVMissionPlan_CL`

### 6.6 시연 시나리오
- **2-person 위반**: 같은 사람이 plan + approve → 403 + `FailReason=planner_equals_approver`
- **미승인 발사**: DRAFT 상태 plan을 release → 403 + `FailReason=not_approved`
- **정상 사이클**: lt.kim plan → capt.park approve → capt.park release → RELEASED

---

## 7. c4i-stub — ATCIS / MIMS

### 7.1 한 줄
한국군 C4I(지상전술C4I = ATCIS, 군사정보종합관리체계 = MIMS)의 **운용 그림(Operational Picture)**을 모사. 작전명령·표적·우군 위치.

### 7.2 왜
1차 미팅 결정사항: **METT+TC** (Mission/Enemy/Terrain/Troops/Time/Civil) 입력. 작전 환경 인지가 SOC 룰 감도를 좌우. ATCIS/MIMS 모사 = "방산 SOC가 작전 환경을 안다" 시연.

### 7.3 엔드포인트
| 메소드 + 경로 | 동작 |
|---|---|
| `POST /atcis/orders` | 작전명령 (작전명, ROE, 영역, 타겟 우선순위) |
| `POST /mims/targets` | 표적 정보 업데이트 (분류, 신뢰도, 출처) |
| `POST /atcis/friendly-positions` | 우군 위치 (fratricide 버퍼용) |
| `GET /current-operation` | 현재 운용 그림 |

### 7.4 노출 포트
- 8200 TCP

### 7.5 어디에 데이터가 흘러감
- `c4i.ndjson` → `UAVC4I_CL`

### 7.6 시연 활용
- ROE `engage-confirmed-hostile` 명령 + HOSTILE 표적 도착 → SOC가 무장 활성 정당성 판단
- 우군 위치 + UAV 좌표 join → 동조사격(fratricide) 룰

---

## 8. cyber-posture-stub — 사이버위협태세

### 8.1 한 줄
국정원/사이버사가 발령하는 **CT-3 / CT-2 / CT-1** 태세를 모사. 룰 감도 동적 조절 + OSCAL 증거 원천.

### 8.2 왜
방산 SOC는 평시 vs 주의 vs 경계 상태에서 룰 임계가 달라져야 함. "지금 CT-1이니까 모든 의심 행위는 알람" 같은 동적 룰.

### 8.3 엔드포인트
| 메소드 + 경로 | 동작 |
|---|---|
| `GET /posture` | 현재 태세 + since/changed_by |
| `POST /posture` | 태세 전이 (감사 로그 발생) |
| `GET /history` | 최근 전이 이력 |

### 8.4 노출 포트
- 8300 TCP

### 8.5 어디에 데이터가 흘러감
- `cyber-posture.ndjson` → `UAVCyberPosture_CL`

### 8.6 활용 KQL 패턴
```kql
let posture = toscalar(UAVCyberPosture_CL | top 1 by TimeGenerated desc | project Level);
let threshold = iff(posture == "CT-1", 0.3, 0.5);
UAVTelemetry_CL | where PosHorizVariance > threshold
```

### 8.7 OSCAL 어필
"control strength elevated at 09:12 by capt.park because of CT-2 declaration" → 자동 증거.

---

## 9. weapon-stub — 무장 통제

### 9.1 한 줄
**Safety(ARMED/SAFE) → Lock(타겟 락온) → Fire(2-person 룰)** 3단계 무장 통제. MPD의 870g 고폭탄 발사 절차 모사.

### 9.2 왜
방산 = 무장 운용 감사가 핵심. "누가 언제 누구한테 발사 명령을 내렸나" + "안전핀 해제 없이 발사 시도" 같은 패턴 탐지.

### 9.3 엔드포인트
| 메소드 + 경로 | 동작 |
|---|---|
| `GET /weapon/state` | 현재 상태 |
| `POST /weapon/safety` | ARMED ↔ SAFE 전이 |
| `POST /weapon/lock` | 타겟 락온 (SAFE면 거부) |
| `POST /weapon/unlock` | 락 해제 |
| `POST /weapon/fire` | 발사 요청 (2-person 룰) |

### 9.4 노출 포트
- 8400 TCP

### 9.5 어디에 데이터가 흘러감
- `weapon.ndjson` → `UAVWeapon_CL`

### 9.6 시연 사이클
1. `safety_set ARMED by sgt.yang`
2. `lock target=T-001 by capt.park`
3. `fire authorized by capt.park` ✅ (다른 사람)
4. **위반 시도**: `fire by sgt.yang` → 403 + `FailReason=two_person_rule_violation`

---

## 10. ti-stub — Threat Intelligence

### 10.1 한 줄
외부 TI 피드 (CISA KEV, NVD, 내부 SIGINT) 를 모사. 인디케이터·피드 일괄·태세 권고.

### 10.2 왜
방산 SOC는 외부 정보에 따라 룰 감도 / 차단 IP를 갱신해야 함. "신규 CRITICAL CVE 알람" + "ArduPilot 영향 → 태세 상향 권고" 시연.

### 10.3 엔드포인트
| 메소드 + 경로 | 동작 |
|---|---|
| `POST /ti/indicators` | 단일 인디케이터 (cve/ip/hash/domain/url) |
| `POST /ti/feeds` | 피드 일괄 업데이트 |
| `POST /ti/posture-recommendation` | 태세 권고 (CT-2 등) |
| `GET /ti/recent-indicators` | 최근 인디케이터 |

### 10.4 노출 포트
- 8500 TCP

### 10.5 어디에 데이터가 흘러감
- `ti.ndjson` → `UAVThreatIntel_CL`

---

## 11. auth-stub — 운영자 인증 감사

### 11.1 한 줄
조종사·계획자·승인자의 **로그인/세션 토큰 발급/로그아웃**을 모사. 인사이드 위협 + brute force 탐지 입력.

### 11.2 왜
1차 미팅: "조종사 세션 IP 변경 = 도용 가능성". Sentinel 룰의 인증 컨텍스트가 필요.

### 11.3 엔드포인트
| 메소드 + 경로 | 동작 |
|---|---|
| `POST /auth/login` | 로그인 (성공/실패 모두 감사) |
| `POST /auth/validate` | 세션 검증 |
| `POST /auth/logout` | 로그아웃 |
| `GET /auth/sessions` | 현재 세션 목록 |

### 11.4 노출 포트
- 8600 TCP

### 11.5 모의 자격증명
`sgt.yang`, `lt.kim`, `capt.park`, `maj.cho`, `col.lee` — 각자 `uav-pw-N`.

### 11.6 어디에 데이터가 흘러감
- `auth.ndjson` → `UAVOpAudit_CL`

### 11.7 탐지 패턴
- 1분 5회 이상 `login_failure` 같은 ClientIp → brute force
- 같은 `SessionId`가 다른 ClientIp에서 사용 → 세션 도용

---

## 12. datalink-stats — 컨테이너 / 링크 통계

### 12.1 한 줄
**Docker stats API 폴링** + **`ss -tn` 실행**으로 datalink-los 통계, 전체 컨테이너 리소스, TCP 연결 스냅샷 emit.

### 12.2 왜
링크 헬스(드롭율 급증 = 재밍 의심), 컨테이너 리소스(공격자가 cryptominer 박았나), 비인가 5790 접속(A4 공격면) 모두 시각화.

### 12.3 동작
30초마다:
1. `uav-datalink-los` 컨테이너의 docker stats → 네트워크 카운터 → `datalink-stats.ndjson`
2. compose project 전 컨테이너 stats → CPU/MEM/IO → `resource-metrics.ndjson`
3. datalink-los 안에서 `ss -tn -H` → 5760/5790/14550 관련 TCP 연결 → `datalink-conn.ndjson`

### 12.4 어디에 데이터가 흘러감
- `datalink-stats.ndjson` → `UAVDatalink_CL`
- `resource-metrics.ndjson` → `UAVResourceMetrics_CL`
- `datalink-conn.ndjson` → `UAVDatalinkConn_CL`

### 12.5 의존
- `/var/run/docker.sock` read-only 마운트

---

## 13. service-audit — Docker 이벤트 감사

### 13.1 한 줄
`/var/run/docker.sock`의 이벤트 스트림 구독 → 컨테이너 lifecycle 이벤트를 NDJSON으로 emit.

### 13.2 왜
"비행 중 SITL 컨테이너가 갑자기 죽음" 같은 인프라 이상은 차량 자체엔 안 보임. SOC는 그것까지 봐야 완전한 가시성.

### 13.3 이벤트 종류
`start`, `die`, `kill`, `restart`, `destroy`, `oom`, `pull`, `exec_create` 등.

### 13.4 어디에 데이터가 흘러감
- `service-audit.ndjson` → `UAVServiceAudit_CL`

### 13.5 시연 룰
- 비인가 이미지 pull
- av-mpd 비정상 종료 (ExitCode != 0)
- exec 명령 빈도 급증 (디버그용? 공격용?)

---

## 14. 인프라 — Azure 측

이 컴포넌트들이 도는 **인프라 그림**:

```
dah-sim-rg (한국 중부)
  └── uavsim-vm (D4s_v5, Ubuntu 22.04)
       └── Docker Compose 묶음 (13개 컨테이너)
             └── /var/log/uav-sim-env/*.ndjson (19개 파일)
                   ↓
                Azure Monitor Agent
                   ↓
dah-data-rg
  └── dah-data-law (Log Analytics)
       ├── DCR primary (10 streams)
       ├── DCR extras  (9 streams)
       └── Sentinel solution
              └── 19 UAV* tables (스키마: docs/sentinel-schemas.md)

dah-soc-rg
  ├── dah-soc-aks (kagent + LangGraph 에이전트)
  ├── ACR (image registry)
  └── AOAI (gpt-4o-mini, deployment gpt-4o-soc)
```

배포 자동화: `infra/*.bicep` + `scripts/full-ingest.sh`.

---

## 15. 컴포넌트 간 데이터 흐름 (요약)

```
[av-mpd] MAVLink TCP 5760
   │
[datalink-los] tc netem + mavlink-router
   ├── UDP 14550 → [gcs-qgc] QGC
   ├── UDP 14552 → [telemetry-tap]
   │                 ├── telemetry.ndjson
   │                 ├── operator.ndjson
   │                 ├── mission.ndjson
   │                 ├── failsafe.ndjson
   │                 ├── config-audit.ndjson
   │                 ├── imagery.ndjson
   │                 └── mavsec.ndjson
   └── TCP 5790 → 외부 (red team)

[pgse-stub]  HTTP 8000 → pgse.ndjson + maintenance.ndjson
[mps-stub]   HTTP 8100 → mps.ndjson
[c4i-stub]   HTTP 8200 → c4i.ndjson
[cyber-pos]  HTTP 8300 → cyber-posture.ndjson
[weapon]     HTTP 8400 → weapon.ndjson
[ti-stub]    HTTP 8500 → ti.ndjson
[auth-stub]  HTTP 8600 → auth.ndjson

[datalink-stats]  docker.sock 폴링 → 3개 ndjson
[service-audit]   docker.sock 이벤트 → service-audit.ndjson

         ↓ 19개 ndjson
   /var/log/uav-sim-env/
         ↓
   Azure Monitor Agent (fluent-bit tail)
         ↓
   DCE / 2개 DCR
         ↓
   19개 UAV* 테이블 in dah-data-law
         ↓
   Sentinel 룰 (김수지 작성)
         ↓
   pollack-ai LangGraph (황준식, AKS+kagent에서)
```

---

## 16. 시나리오 ↔ 컴포넌트

| 시나리오 | 트리거 컴포넌트 | 핵심 테이블 |
|---|---|---|
| **S1 GNSS 스푸핑** | av-mpd `SIM_GPS_*` 파라미터 변조 (또는 외부 GPS 인젝터) | UAVTelemetry_CL EKF_STATUS_REPORT |
| **S3 SATCOM MITM** | (Phase 2: BVLOS 추가) | (없음) |
| **S4 펌웨어 변조** | pgse-stub `/preflight/check` 가짜 해시 | UAVPgse_CL |
| **A4 MAVLink 인젝션** | datalink-los TCP 5790 직접 접속 | UAVOperator_CL, UAVDatalinkConn_CL |
| **인사이드 위협** | mps-stub 2-person 위반, weapon-stub | UAVMissionPlan_CL, UAVWeapon_CL, UAVOpAudit_CL |
| **재밍** | (외부 자극 — Phase 2) | UAVDatalink_CL RxErrors 급증 |
| **OSCAL 증거** | cyber-posture-stub, mps-stub, pgse-stub | UAVCyberPosture_CL, UAVMissionPlan_CL, UAVMaintenance_CL |

---

## 17. 관련 문서

- 본 문서 (컴포넌트 상세): `docs/components.md`
- 브라우저 접속 가이드: [`docs/qgc-novnc-guide.md`](./qgc-novnc-guide.md)
- Sentinel 테이블 스키마 (김수지용): [`docs/sentinel-schemas.md`](./sentinel-schemas.md)
- 인프라 배포 (Bicep): `infra/`
- 자동화 스크립트: `scripts/`

---

## 18. FAQ

**Q. 왜 ArduPilot이고 PX4가 아닌가?**
A. LIG 카탈로그의 일부 기체(MPD 등)가 ArduPilot 호환. SITL 안정성 + 한국 커뮤니티도 큼. Phase 2에서 PX4 추가 검토 가능.

**Q. 왜 Gazebo Garden인가 Classic이 아닌가?**
A. ArduPilot 최신은 Gazebo Garden 플러그인 공식 지원. Classic은 EOL.

**Q. 컨테이너 13개 한 VM에 다 띄워도 되나?**
A. D4s_v5 (4 vCPU 16 GB)면 충분. SITL이 가장 무거움 (CPU 70%). 나머지 FastAPI는 거의 무부하.

**Q. 왜 KGCS (국군) 아니고 QGroundControl인가?**
A. KGCS 비공개. QGC가 사실상 군용 기능 동등 (MAVLink 표준 GCS).

**Q. 왜 LIG MPD가 단일 UAV인가?**
A. Phase 1 단순화. LOS only (BVLOS·SATCOM 없음). KCD-200/MPUH는 Phase 2.

**Q. AOAI gpt-4o-mini가 충분히 똑똑한가?**
A. SOC triage 정도엔 충분. Investigation 같은 복잡 단계는 gpt-4o로 업그레이드 가능 (ModelConfig 추가).
