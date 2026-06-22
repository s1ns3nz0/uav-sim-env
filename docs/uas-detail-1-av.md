# UAS 상세 (1) — AV (Air Vehicle)

> **성격**: 소개·학습 문서. 실제 비행체에 어떤 요소(날개·센서·페이로드 등)가 있는지 → 그 요소를 `uav-sim-env`에서 어떤 오픈소스로 구현했는지 → 거기서 발생하는 애플리케이션 로그가 무엇인지를 정리한다.
> **대상 기체**: KUS-FS급 중고도 장기체공(MALE) 정찰기. 컨테이너 `av-muav` (2~4대 편대).
> **레포 참조**: `av-muav/Dockerfile`, `av-muav/entrypoint.sh`, `av-muav/persona/muav_male.parm`, `av-muav/bootstrap.py`, `telemetry-tap/tap.py`, `docs/sentinel-schemas.md`

---

## 0. AV란

AV(Air Vehicle, 비행체)는 UAS의 "날아다니는 부분"이다. 단순한 기체가 아니라 **에어프레임 + 추진 + 항법센서 + 비행제어컴퓨터(FCC) + 페이로드 + 통신단말 + 전원**이 한 덩어리로 묶인 시스템이다. 본 환경의 AV는 KUS-FS급 고정익 MALE기로, 고고도(최대 45,000ft)에서 24시간 체공하며 EO/IR·SAR로 광역 정찰한다. 이 문서는 그 구성 요소를 하나씩 따라가며 시뮬에서의 구현과 로그를 짚는다.

---

## 1. 실제 기체의 구성 요소 (KUS-FS급)

| 구분 | 실제 요소 | 하는 일 |
|---|---|---|
| **에어프레임** | 대형 고정익(주익 25.3m), 동체, 제어면(에일러론·엘리베이터·러더) | 양력·자세·기동 |
| **추진** | 1,200마력 터보프롭 1기, 가변피치 프로펠러 | 고고도 순항·장기체공 |
| **항법 센서** | 이중화 GPS/GNSS, IMU(가속도계·자이로), 기압계, 자력계, 대기속도계(피토) | 위치·자세·고도·속도 추정 |
| **비행제어컴퓨터(FCC)** | 오토파일럿(EKF 상태추정 + 제어 루프) | 자율비행, 센서융합, 활주로 이착륙 |
| **페이로드** | EO/IR 짐벌 + **SAR(합성개구레이더)** + GMTI | 주야·악천후 광역 정찰·표적 |
| **통신 단말** | **이중 데이터링크**: C-band LOS 모뎀 + Ku/Ka SATCOM 단말, IFF | GCS와 명령·텔레메트리·영상 교환 |
| **전원** | 연료(터보프롭) + 발전, 항전 버스 | 24시간 체공 지속 |
| **안전장치** | Failsafe(링크 상실·연료부족 시 RTL/착륙), LOS↔BLOS 자동 전환 | 사고 방지·링크 강건성 |

> 분대급 소형기(Group 1)와 비교하면 요소가 대형화·이중화되고 **SAR·SATCOM 단말이 추가**된다. 다만 구성 요소의 *종류*는 같아서, 시뮬은 frame/persona만 바꿔 동일 골격을 재사용한다.

---

## 2. 오픈소스 구현

AV는 **ArduPilot SITL + Gazebo Garden**으로 컨테이너 `av-muav`에 구현된다.

### 2.1 골격 — ArduPilot SITL
- **무엇**: 실기체용 오토파일럿 펌웨어(`ArduPlane`, 브랜치 `Plane-4.5`)를 PC에서 그대로 빌드한 SITL(Software-In-The-Loop) 빌드. (`av-muav/Dockerfile`: `./waf configure --board sitl && ./waf plane`)
- **핵심 의미**: FCC·EKF·제어 루프·센서 융합이 **실기체와 동일한 코드**로 돈다. 가상 IMU/GPS/기압계/대기속도계/모터 신호를 내부 생성하고 TCP **5760**에 MAVLink 서버를 연다.
- **실행**: `entrypoint.sh`가 `sim_vehicle.py -v ArduPlane -f plane -I {INSTANCE} --no-mavproxy --wipe-eeprom --custom-location ... --add-param-file <persona>` 로 기동. **고정익(`-f plane`)** 이며 `-I`로 편대(2~4대 다중 인스턴스)를 띄운다.

### 2.2 물리·시각화 — Gazebo Garden
- **무엇**: 물리 엔진 + 3D 월드(`av-muav/world/muav_recon.sdf`). 고고도·장거리 순항 거동을 시각화/물리 모사.

### 2.3 기체 요소 ↔ persona 파라미터 매핑
실제 요소는 **persona 파라미터 파일**(`persona/muav_male.parm`)에서 ArduPilot 파라미터로 표현된다. 즉 "이 기체가 어떤 기체인가"를 파라미터로 오버라이드한다.

| 실제 요소 | persona 파라미터(예) | 의미 |
|---|---|---|
| 에어프레임/고정익 | `-f plane` (frame) + `TRIM_ARSPD_CM`, `ARSPD_FBW_MIN/MAX` | 고정익 순항·실속속도(MALE급) |
| 이착륙 | `TKOFF_*`(활주로 이륙), `LAND_*` | VTOL 제거, 활주로/카타펄트 이착륙 |
| 추진/고고도 | `THR_*`, 고도 관련 기압 파라미터 | 45,000ft 고고도 순항 |
| 전원/체공 | `BATT_*` 또는 연료 모델(`SIM_*`) | 24시간 장기체공 가정 |
| 항법(이중 GPS) | `GPS_TYPE`, `GPS_TYPE2`, `GPS_AUTO_SWITCH 1` | 이중화 GNSS |
| 통신/텔레메트리율 | `SR0_*`(LOS), `SR1_*`(SATCOM 스트림) | 이중 링크별 메시지율 |
| 안전장치(Failsafe) | `FS_SHORT_ACTN`, `FS_LONG_ACTN`, `FS_GCS_ENABL` | 링크 상실 시 RTL, 링크 전환 |
| EO/IR 짐벌 | `MNT1_TYPE`, `MNT1_DEFLT_MODE` | 짐벌 마운트 stub |
| SAR 페이로드 | (서보/마운트 채널 + `sar-stub` 연계) | SAR 프레임 트리거 |
| 미션 | `WP_RADIUS` | 종심(100~300km) 정찰 웨이포인트 |

> 임무 파일은 `gcs-qgc`의 `missions/muav_recon.plan`(활주로 이륙 → 종심 순항 → ROI 정찰 → 복귀·착륙).

### 2.4 부팅 보정 — bootstrap.py
- SITL 부팅 + 라우터 접속 후(`~35s 대기`), 라우터의 TCP 5790으로 접속해 **`ARMING_CHECK=0`, `MISSION_CURRENT=0`** 을 PARAM_SET. persona 파일만으로는 ArduPlane이 런타임에 되돌리는 값을 강제하기 위한 데모 편의 보정. (`av-muav/bootstrap.py`, pymavlink 사용)

---

## 3. 발생하는 애플리케이션 로그

AV(ArduPilot SITL) 자신이 직접 내는 것은 **MAVLink 메시지 스트림**(+ ArduPilot 콘솔/dataflash)뿐이다. 아래 NDJSON·`UAV*_CL` 테이블은 관측 계층 **`telemetry-tap`이 그 스트림을 가공**한 결과다(메커니즘 상세는 `docs/uas-mapping-summary.md`의 telemetry-tap 절). 여기서는 AV 요소 → 최종 테이블까지 흐름을 끝까지 보여준다. 이중 링크라 경로가 둘이다.

```
av-muav (SITL, MAVLink)
   ├─5760─▶ datalink-los  (C-band LOS, mavlink-router)
   └──────▶ datalink-satcom (Ku/Ka BLOS, OpenSAND)
                    │
        ─14552─▶ telemetry-tap (pymavlink) ─▶ *.ndjson ─▶ Sentinel UAV*_CL
```

`telemetry-tap/tap.py`는 일부 메시지만 전달(`FORWARDED_MSG_TYPES`)하고, 용도별 NDJSON 분기로 떨군다. 기체 요소별로 어떤 메시지가 어떤 테이블로 가는지:

| 기체 요소 | MAVLink 메시지 | NDJSON / 테이블 | 비고 |
|---|---|---|---|
| 항법(GPS/IMU/EKF) | `GLOBAL_POSITION_INT`, `GPS_RAW_INT`, `GPS2_RAW`, `ATTITUDE`, `VFR_HUD`, `LOCAL_POSITION_NED`, `EKF_STATUS_REPORT`, `VIBRATION` | `telemetry.ndjson` → **`UAVTelemetry_CL`** | EKF 잔차가 핵심 |
| FCC 상태 | `HEARTBEAT`, `SYS_STATUS` | `UAVTelemetry_CL` | 모드·시스템 상태 |
| 전원 | `BATTERY_STATUS` | `UAVTelemetry_CL` | 전압·전류·잔량 |
| 운영자 명령 | `COMMAND_LONG`, `COMMAND_ACK`, `MISSION_CURRENT`, `MISSION_ITEM_REACHED` | `operator.ndjson` → **`UAVOperator_CL`** | A4 인젝션·인사이드 위협 |
| 미션 진행 | (파생: takeoff/waypoint/land/mode) | `mission.ndjson` → **`UAVMissionEvent_CL`** | 타임라인·사후검토 |
| 안전장치 | `STATUSTEXT`(severity≤4), RTL/LAND 모드 전이 | `failsafe.ndjson` → **`UAVFailsafe_CL`** | 링크상실·연료부족·링크전환 |
| 설정 변경 | `PARAM_VALUE`(이전값과 다를 때) | `config-audit.ndjson` → **`UAVConfigAudit_CL`** | 무단 파라미터 변조 |
| EO/IR·짐벌 | `CAMERA_TRIGGER`, `CAMERA_IMAGE_CAPTURED`, `VIDEO_STREAM_INFORMATION`, `MOUNT_ORIENTATION`, `CAMERA_INFORMATION` | `imagery.ndjson` → **`UAVImagery_CL`** | 촬영·짐벌 지향 |
| **SAR 페이로드** | (`sar-stub` 프레임 메타 + 합성 이미지) | `sar.ndjson` → **`UAVSarPayload_CL`** | 표적 좌표·해상도·프레임ID |
| **SATCOM 링크** | (`datalink-satcom` 링크/세션 메타) | `satcom.ndjson` → **`UAVSatcomLink_CL`** | 세션·시퀀스·무결성·RTT |
| 링크 보안 | (30초 윈도우 서명 카운트) | `mavsec.ndjson` → **`UAVMavsec_CL`** | MAVLink 서명 유무 |

### 3.1 `UAVTelemetry_CL` — AV 텔레메트리의 중심 (`docs/sentinel-schemas.md` 1절)
대표 컬럼: `UAVId`, `MsgType`, 위치(`Lat/Lon/AltMSL_m`), 속도(`Vx/Vy/Vz`), GPS(`FixType`, `SatellitesVisible`, `Eph_cm/Epv_cm`), 자세(`Roll/Pitch/Yaw_rad`), 대기/지면속도(`Airspeed_ms/Groundspeed_ms`), 전원(`BatteryVoltage_mV` 등), 진동(`VibrationX/Y/Z`).

**보안상 핵심 필드** — EKF 상태추정 잔차:
- `PosHorizVariance`, `VelocityVariance`, `PosVertVariance` → **S1(GNSS 스푸핑)** 탐지의 핵심. GPS가 조작되면 EKF의 융합 잔차가 튄다. 종심이 깊어 LOS 시각 백업이 없으므로 중요도↑.
- `Command`(COMMAND_LONG의 MAV_CMD) → **A4(MAVLink 인젝션)** 탐지.

### 3.2 어떻게 시나리오로 연결되나
- **S1 GNSS 스푸핑**: AV의 `SIM_GPS_*` 파라미터(또는 외부 인젝터) 변조 → `EKF_STATUS_REPORT`의 분산값 상승 → `UAVTelemetry_CL`.
- **S3 SATCOM MITM**: BLOS 경로의 세션·시퀀스·서명 위반 → `UAVSatcomLink_CL`. (이중 링크라 실재화됨)
- **SAR 표적 조작**: 임무 외 좌표 SAR 수집/프레임 폭증 → `UAVSarPayload_CL`.
- **편대 횡적확산**: 다수기(`MUAV-001..004`) 동시 항로 이탈/동일 명령 → `UAVTelemetry_CL`/`UAVOperator_CL` 편대 단위 분석.
- **A4 MAVLink 인젝션**: 외부에서 평문 MAVLink 채널로 `COMMAND_LONG` 주입 → `UAVOperator_CL`.

---

## 4. 요약

AV는 ArduPilot SITL이 실기체와 **동일한 펌웨어**로 항법·제어를 돌리고, 기체 정체성은 **persona 파라미터(`muav_male.parm`)** 로 표현되며, Gazebo가 물리/시각화를 맡는다. KUS-FS급이라 **고정익·이중 GPS·EO/IR+SAR·LOS+SATCOM 이중 링크·편대(2~4대)** 가 특징이다. AV가 내보내는 MAVLink는 `telemetry-tap`이 NDJSON으로 풀어 `UAVTelemetry_CL`을 비롯한 테이블로 적재되고, 그 중 **EKF 잔차(S1)·SATCOM 무결성(S3)·SAR 표적·COMMAND(A4)** 가 SOC 탐지의 핵심 신호다.

다음 상세 문서: (2) Data Link.
