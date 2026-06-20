# uav-sim-env

LIG D&A Hackathon B 트랙 (UAV/드론/국방) — **UAS(무인항공기 체계) 시뮬레이션 환경**.
실기체 없이 SOC(보안관제) 시나리오를 검증하기 위한 풀스택 무인기 시뮬.

본 환경은 자매 프로젝트 `pollack-ai`(LangGraph 기반 UAV AI SOC 플랫폼)의 입력 텔레메트리 생성기 역할.

---

## 1. 무엇을 시뮬레이션 하는가

미 육군 교범 **FMI 3-04.155** 가 정의하는 UAS(Unmanned Aircraft System) 5대 구성요소를 컨테이너로 재현.

| 구성요소 | 실제 운용 | 본 프로젝트 컨테이너 | 사용 오픈소스 |
|---|---|---|---|
| **AV** (Air Vehicle) | 비행체 + 페이로드 + GPS/INS/IFF | `av-mpd` | ArduPilot SITL + Gazebo Garden |
| **Data Link** | LOS C-band / BLOS Ku-Ka SATCOM | `datalink-los` | mavlink-router + tc netem |
| **GDT** (Ground Data Terminal) | 지상 RF 안테나 (LOS 200km) | `datalink-los` 내 (Phase 1 통합) | UDP 프록시 모사 |
| **GCS** (Ground Control Station) | UGCS, Mini-UGCS, 임무계획/조종/영상분석 | `gcs-qgc` | QGroundControl + Xvfb + noVNC |
| **PGSE** (Payload & Ground Support Equipment) | 발사장비, 정비공구, 회수네트 | (Phase 2 `pgse-stub`) | FastAPI + cosign/SBOM |

---

## 2. 모델링 대상 기체: MPD

**MPD — LIG Nex1 소형 정찰·타격 복합형 드론** (Multi-Purpose Drone).

| 특성 | 값 | 시뮬 매핑 |
|---|---|---|
| 형상 | 틸트로터 4발 VTOL | ArduPilot `ArduPlane` + `quadplane` 프레임 |
| 활주로 | 불필요 | Quadplane 수직이착륙 모드 |
| 휴대성 | 분해 후 백팩 휴대 (FRP) | — |
| 페이로드 | EO/IR + 레이저 거리 지시기 + 870g 고폭탄 자폭 | 짐벌 마운트 stub + 서보채널 9/10 (자폭 무장/해제) |
| 통신 | LOS RF 만 (Group 1-2) | `datalink-los` UDP/MAVLink, BLOS 없음 |
| 운용 | 분대급 → 표적 탐지 → 정밀 타격 | 정찰 미션 `mpd_recon.plan` (waypoint 5) |
| 검증 | 방위사업청 신속시범획득사업 / Army Tiger 4.0 | — |

**왜 MPD?** LOS only 라 인프라 단순. 기존 시나리오 S1(GNSS 스푸핑)·S4(펌웨어 변조)와 매핑 100%. SATCOM 시나리오(S3)는 Phase 2 (KCD-200/MPUH 추가) 이후.

---

## 3. 아키텍처 (Phase 1 MVP)

```
                      ┌──────────────────────────┐
                      │   gcs-qgc (10.50.0.30)   │
                      │   QGroundControl         │
                      │   noVNC :8080            │
                      │   VNC   :5900            │
                      └──────────▲───────────────┘
                                 │ MAVLink UDP :14551
                                 │
┌──────────────────┐   MAVLink UDP :14550   ┌──────────────────────────┐
│ av-mpd           │ ─────────────────────▶ │ datalink-los (10.50.0.20)│
│ 10.50.0.10       │                        │ mavlink-router           │
│ ArduPilot SITL   │                        │ tc netem (delay/loss)    │
│ Quadplane (MPD)  │ ◀───────────────────── │                          │
└──────────────────┘                        └──────────────────────────┘
                                                   │
                                                   │ MAVLink UDP :14552
                                                   ▼
                                            (Phase 2: telemetry-tap
                                             → Azure Sentinel)
```

**네트워크**: `uas-los` bridge, 10.50.0.0/24
**LOS 시뮬**: `tc netem`으로 지연 50ms ±5ms + 패킷손실 1% 주입 (산악 LOS 가정)

---

## 4. 빠른 시작

### 사전 요구
- Docker Desktop / Engine (Compose v2)
- 빌드용 디스크 ~8GB (ArduPilot 소스 + QGC AppImage + Gazebo)
- RAM 8GB 이상

### 실행

```bash
git clone https://github.com/s1ns3nz0/uav-sim-env.git
cd uav-sim-env

# 빌드 (최초 1회 ~15-30분, ArduPilot/QGC 소스 빌드)
docker compose build

# 실행
docker compose up -d

# 로그 확인
docker compose logs -f av-mpd
```

### GCS 접속
브라우저에서 `http://localhost:8080/vnc.html` → Connect → MAVLink 자동 인식 → MPD 임무 로드 (`/root/missions/mpd_recon.plan`)

### MAVLink 직접 모니터링
```bash
# 호스트에서 14551 포트 패킷 dump
nc -ul 14551 | xxd | head
```

---

## 5. 시나리오 환경 준비 매트릭스

본 환경은 **시나리오를 실행하는 것이 아니라 시나리오가 칠 수 있는 대상을 갖춰놓는** 것이 목적. 실제 공격 실행/탐지 룰 작성은 별도 트랙.

| 시나리오 | 출력 룰 (`pollack-ai`) | 공격 대상 (이 repo) | 텔레메트리 진입점 | 환경 준비 |
|---|---|---|---|---|
| **S1 GNSS 스푸핑** | `uav_gps_spoof_residual.yml` | `av-mpd` SITL `SIM_GPS_*` 파라미터 (MAVLink `PARAM_SET` 통해 변조) | `telemetry-tap` `EKF_STATUS_REPORT.PosHorizVariance` / `VelocityVariance` | ✅ |
| **S3 SATCOM MITM** | `uav_satcom_integrity_fail.yml` | BVLOS 링크 (Phase 2 — MPD는 LOS only) | — | ❌ Phase 2 |
| **S4 펌웨어·공급망 변조** | `uav_fw_signature_mismatch.yml` | `pgse-stub` `/preflight/check`, `/armory/firmware/{id}`, `/launch/authorize` | pgse-stub 로그 + (Phase 2) NDJSON 통합 | ✅ |
| **A4 MAVLink 평문 인젝션** | (TBD) | `datalink-los` TCP `:5790` (호스트 노출) → MAVProxy/pymavlink로 임의 패킷 주입 | `telemetry-tap` `COMMAND_LONG` / `STATUSTEXT` | ✅ |

### 공격면 엔드포인트 표 (호스트에서 바로 접근)

| 포트 | 프로토콜 | 서비스 | 용도 |
|---|---|---|---|
| `14550/udp` | MAVLink | datalink-los | QGC 자동 인식 채널 (관측/제어) |
| `14552/udp` | MAVLink | telemetry-tap → datalink-los | tap 출력 (참고) |
| `5790/tcp` | MAVLink | datalink-los | **A4 공격용 평문 MAVLink 채널** (mavlink-router server) |
| `5760/tcp` | MAVLink | av-mpd | ArduPilot SITL 직접 접근 (디버깅용) |
| `8000/tcp` | HTTP/REST | pgse-stub | **S4 공격용 PGSE REST API** (Swagger UI: `/docs`) |
| `8080/tcp` | HTTP/noVNC | gcs-qgc | QGroundControl 브라우저 뷰 |
| `5900/tcp` | VNC | gcs-qgc | QGC raw VNC |

---

## 6. UAS Group 1~5 확장성

ArduPilot + MAVLink 기반 시뮬은 **프레임/거동 측면에서 Group 1~5 전부 커버 가능**.

| Group | 예시 | 본 환경 매핑 | 비고 |
|---|---|---|---|
| 1 | MPD (LIG) | `av-mpd` (Phase 1) | ✅ |
| 2 | ScanEagle | 프레임 변경 | — |
| 3 | RQ-7 Shadow, RQ-101 송골매 | LOS + 일부 BLOS | LOS 통신 동일 모델 |
| 4 | MQ-1C Gray Eagle | + SATCOM stub 필요 | Phase 2 |
| 5 | MQ-9 Reaper, RQ-4 Global Hawk, KUS-FS | + dual-link (C-band LOS + Ku BLOS) | Phase 3 |

**프레임/링크는 흉내 가능. FCC 내부 코드는 벤더 비공개(General Atomics, KAI 등)이므로 흉내 불가**. 우리 SOC 위협면은 **프로토콜/링크 층** 이므로 Group 1 시뮬에서 잡은 룰이 Group 5에도 적용됨.

---

## 7. Azure 배포 (Phase 0+ 옵션)

권장 구성:
- **VM**: `Standard_D4s_v5` (4 vCPU, 16GB RAM) — Korea Central
- **OS**: Ubuntu 22.04 LTS
- **NSG**: 22(SSH), 8080(noVNC) 본인 IP 화이트리스트
- **자동화**: Bicep + cloud-init (Phase 1 이후 추가)

AKS 이전은 멀티 UAV/스웜 (Phase 3) 단계에서.

---

## 8. 디렉터리 구조

```
uav-sim-env/
├── README.md
├── docker-compose.yml
├── av-mpd/                      # AV (Air Vehicle)
│   ├── Dockerfile               # ArduPilot SITL + Gazebo Garden
│   ├── entrypoint.sh
│   ├── persona/
│   │   └── mpd_quadplane.parm   # MPD 페르소나 ArduPilot 파라미터
│   └── world/
│       └── mpd_recon.sdf        # Gazebo 정찰 임무 월드
├── datalink-los/                # Data Link + GDT
│   ├── Dockerfile               # mavlink-router from source
│   ├── mavlink-router.conf
│   └── entrypoint.sh            # tc netem + mavlink-routerd
├── gcs-qgc/                     # GCS (Ground Control Station)
│   ├── Dockerfile               # QGC AppImage + Xvfb + noVNC
│   ├── supervisord.conf
│   ├── entrypoint.sh
│   └── missions/
│       └── mpd_recon.plan       # 정찰 임무 (VTOL 이착륙 + ROI 락온 + loiter)
├── telemetry-tap/               # 관측층 (Phase 1a)
│   ├── Dockerfile               # Python 3.11 + pymavlink
│   ├── requirements.txt
│   └── tap.py                   # MAVLink → NDJSON to stdout
└── pgse-stub/                   # PGSE 디지털 면 (Phase 1b)
    ├── Dockerfile               # FastAPI on uvicorn
    ├── requirements.txt
    ├── app.py                   # /armory/firmware, /preflight/check, /launch/authorize
    └── data/
        └── approved_firmware.json
```

---

## 9. 참고 자료

- **FMI 3-04.155** US Army Unmanned Aircraft System Operations
- **ATP 3-04.64** US Army UAS
- **LIG 무인기 카탈로그** (사내 자료, `pollack-ai/docs/`)
- **ArduPilot SITL 공식 문서** https://ardupilot.org/dev/docs/sitl-simulator-software-in-the-loop.html
- **MAVLink common dialect** https://mavlink.io/en/messages/common.html

---

## 10. Phase 로드맵

| Phase | 범위 | 상태 |
|---|---|---|
| 0 | 단일 MPD MVP (av-mpd + datalink-los + gcs-qgc) | ✅ 완료 |
| 1a | telemetry-tap (MAVLink → NDJSON, Sentinel ingest 준비) | ✅ 완료 |
| 1b | pgse-stub (S4 attack surface) + 5790 노출 (A4) | ✅ 완료 |
| 1c | Azure Monitor Agent + Log Analytics 워크스페이스 ingest | — |
| 2 | KCD-200 추가 + SATCOM stub (S3 BVLOS) | — |
| 3 | MPUH MUM-T + 군집자폭 inter-drone mesh + AKS 이전 | — |

---

## 라이선스

연구·해커톤용. LIG 카탈로그 파생 자료는 LIG Nex1 공식 자료 / 보도자료 출처를 따름.
