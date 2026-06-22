# UAS 5+1 ↔ 오픈소스 매핑 요약

> 한 장 요약. 자세한 설명은 `docs/opensource-uas-mapping.md`, 컨테이너별 상세는 `docs/components.md`.

## 매핑표

| 5+1 요소 | 실제 역할 | 오픈소스 | 컨테이너 |
|---|---|---|---|
| **AV** | 비행체 + 페이로드 + GPS/INS/IFF | ArduPilot SITL + Gazebo Garden | `av-muav` |
| **Data Link (LOS)** | C-band 가시선 링크 | mavlink-router + tc netem | `datalink-los` |
| **Data Link (BLOS)** | SATCOM 위성 링크 | OpenSAND (DVB-S2/RCS2) | `datalink-satcom` |
| **GDT** | 지상 RF 안테나(LOS 종단) | mavlink-router UDP 라우팅 | `datalink-los` 통합 |
| **GCS/MCE** | 임무계획·조종·영상분석 | QGroundControl + noVNC 스택 | `gcs-qgc` |
| **PGSE** | 발사·정비·회수 | FastAPI/uvicorn | `pgse-stub` |
| **+1 위성/지상국** | GEO 트랜스폰더 + Teleport | OpenSAND (SAT·GW) | `datalink-satcom` |
| 페이로드: SAR | 합성개구레이더 영상 | FastAPI + 합성 SAR 이미지 | `sar-stub` |
| C4I 핸드오프 | 공군→육군 영상/표적 전달 | (기존 c4i-stub에 흡수) | `c4i-stub` |

## 관측·보조 계층

| 역할 | 오픈소스 | 컨테이너 |
|---|---|---|
| MAVLink → NDJSON 수집 | pymavlink | `telemetry-tap` |
| 링크/리소스 통계 | docker stats + `ss` | `datalink-stats` |
| 컨테이너 이벤트 감사 | docker events | `service-audit` |
| 임무계획·C4I·태세·무장·TI·인증 | FastAPI | `mps/c4i/cyber-posture/weapon/ti/auth-stub` |

## telemetry-tap — 관측 계층 (로그 가공의 중심)

> 각 요소별 상세 문서에서 "이 요소의 출력이 어느 테이블로 가나"를 끝까지 따라갈 때, 그 **가공을 실제로 수행하는 주체**가 telemetry-tap이다. 요소 문서들은 흐름을 보여주되, NDJSON/테이블 생성 메커니즘의 출처는 이 절이다.

**왜 필요한가.** AV(ArduPilot SITL)나 데이터링크는 `UAV*_CL` 테이블을 **직접 만들지 않는다**. 그들이 내보내는 것은 **MAVLink 메시지 스트림**뿐이다(+ ArduPilot 콘솔/dataflash). 그 스트림을 사람이 볼 수 있는 구조화 로그(NDJSON)로 바꾸는 별도 컨테이너가 `telemetry-tap`(pymavlink)이다.

**동작.** MAVLink UDP `14552`를 구독 → 전달 대상 메시지(`FORWARDED_MSG_TYPES`)만 골라 JSON 한 줄씩 → 용도별 NDJSON 파일로 분기(환경변수 sink 경로로 제어) → Azure Monitor Agent가 tail 하여 `UAV*_CL` 테이블로 적재.

**분기(sink) ↔ 테이블.**

| NDJSON 파일 | 내용 | 테이블 |
|---|---|---|
| `telemetry.ndjson` | 전체 텔레메트리(위치·자세·GPS·EKF·전원…) | `UAVTelemetry_CL` |
| `operator.ndjson` | 운영자 명령(COMMAND_LONG/ACK, MISSION_CURRENT…) | `UAVOperator_CL` |
| `mission.ndjson` | 미션 라이프사이클(takeoff/waypoint/land/mode) | `UAVMissionEvent_CL` |
| `failsafe.ndjson` | STATUSTEXT(sev≤4) + RTL/LAND 전이 | `UAVFailsafe_CL` |
| `config-audit.ndjson` | PARAM_VALUE 변화(이전값 대비) | `UAVConfigAudit_CL` |
| `imagery.ndjson` | 카메라/짐벌(CAMERA_*, MOUNT_ORIENTATION…) | `UAVImagery_CL` |
| `mavsec.ndjson` | 30초 윈도우 MAVLink 서명 카운트 | `UAVMavsec_CL` |

(SATCOM/SAR 등 비-MAVLink 출력은 각 stub이 자체 NDJSON을 떨궈 `UAVSatcomLink_CL`·`UAVSarPayload_CL`로 적재 — telemetry-tap 경로가 아님.)

**핵심 입력(SOC 룰).** `EKF_STATUS_REPORT`의 PosHorizVariance/VelocityVariance → **S1(GNSS 스푸핑)**, `COMMAND_LONG`의 Command → **A4(MAVLink 인젝션)**.

> 레포: `telemetry-tap/tap.py`. 테이블 스키마: `docs/sentinel-schemas.md`.

---

## 핵심 한 줄

- 5요소(AV·Data Link·GDT·GCS·PGSE) + 위성/지상국(+1)을 전부 오픈소스로 컨테이너화.
- LOS는 mavlink-router+netem, **BLOS는 OpenSAND**로 위성 물리계층까지 모사.
- AV·링크는 MAVLink 스트림만 내고, **`telemetry-tap`이 그것을 NDJSON으로 가공**해 Sentinel `UAV*_CL` 테이블로 적재(보조 stub은 자체 NDJSON).
