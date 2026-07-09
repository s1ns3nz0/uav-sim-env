# UAV SOC — Sentinel Table Schemas

UAV 시뮬레이션 환경(`uav-sim-env`)이 Microsoft Sentinel(워크스페이스 `dah-data-law`, RG `dah-data-rg`)에 적재하는 **Custom Log 테이블 19종**의 스키마, 출처, 보존 정책, 샘플 쿼리, 활용 시나리오 정리.

> **읽는 사람**: Sentinel 분석 룰 작성자 (김수지)
> **출처 코드**: `infra/sentinel/tables.bicep`, `infra/sentinel/dcr.bicep`, `infra/sentinel/dcr-extras.bicep`
> **인제스트 지연**: 1\~10분 (저트래픽 테이블은 fluent-bit 배치 임계까지 대기)
> **워크스페이스 customerId**: `71a8f26e-2f37-4dc7-a172-dfb0df11d74a`

---

## 0. 운영 컨벤션

- 모든 Custom Log 테이블은 `_CL` 접미사 (Azure 강제).
- DCR 변환은 `source` 패스스루 → NDJSON 키 = 컬럼 이름.
- 모든 행은 `TimeGenerated` (UTC ISO 8601) 필수.
- 빈 값은 `""` 또는 `null` (DCR이 자동 매핑).
- 1차 DCR (`dah-data-uav-dcr`) 10 스트림 + 2차 DCR (`dah-data-uav-dcr-extras`) 9 스트림 = 총 19.

### 보존 정책 요약

| 구분 | 핫(Analytics) | 토탈 |
|---|---|---|
| 컴플라이언스/감사 (Plan, Maint, Posture, OpAudit, Weapon, MissionPlan) | 90~365d | 180~730d |
| 운영 (Telemetry, Operator, Mission, C4I, Pgse, TI) | 30~180d | 90~365d |
| 인프라 (ServiceAudit, Datalink, Resource, DatalinkConn, Mavsec, Imagery, ConfigAudit, Failsafe) | 30~90d | 90~180d |

---

## 1. UAVTelemetry_CL

**출처**: `telemetry-tap` (pymavlink → NDJSON). MAVLink 전체 메시지 스트림.
**볼륨**: 매우 높음 (초당 수십 행).
**보존**: 30d / 90d.

### 스키마

> **이 테이블이 담는 실제 UAV 데이터**: 비행체(AV)의 비행제어컴퓨터(FCC)가 1차 센서(GPS·IMU·기압계·자력계·대기속도계)와 EKF 상태추정기에서 산출해 MAVLink로 내려보내는 **항법·자세·동력·건전성 텔레메트리 일체**. 한 행 = 한 MAVLink 메시지이며, `MsgType`에 따라 채워지는 컬럼이 다르다(희소 행렬).

| 컬럼 | 타입 | 설명 (실제 UAV 데이터) |
|---|---|---|
| TimeGenerated | datetime | 이벤트 시각 (UTC) |
| UAVId | string | 차량 식별자. 편대 운용 시 기체별 구분 (예: `MPD-001`, `MUAV-001`) |
| MsgType | string | 어떤 MAVLink 메시지인지 (예: `EKF_STATUS_REPORT`) — 이 값이 나머지 컬럼의 의미를 결정 |
| SystemId | int | 메시지를 보낸 MAVLink 시스템 ID. 정상은 비행체(=1). **1이 아니면 차량 외 출처(인젝션 의심)** |
| ComponentId | int | 발신 컴포넌트 ID (오토파일럿/짐벌/페이로드 등 기체 내 모듈 구분) |
| Lat, Lon | real | GPS+EKF가 융합한 **현재 위경도**(deg). `GLOBAL_POSITION_INT`에서만 유효 |
| AltMSL_m, AltRel_m | real | 해수면 기준 고도 / 이륙지점(홈) 기준 상대 고도(m). 고도 이탈·강하 탐지 |
| VxNorth_cms, VyEast_cms, VzDown_cms | int | 지구 NED 좌표계 대지속도 성분(cm/s). 항로·강하 추세 |
| Heading_cdeg | int | 기수 방위(centi-deg, 0~36000 = 0~360°) |
| X_m, Y_m, Z_m | real | 홈 기준 로컬 NED 위치(m) — `LOCAL_POSITION_NED` |
| Vx_ms, Vy_ms, Vz_ms | real | 로컬 NED 속도(m/s) |
| FixType | int | **GPS 측위 품질**: 0=무신호, 2=2D, 3=3D, 4=DGPS, 5=RTK. 스푸핑/재밍 시 급락 |
| SatellitesVisible | int | 수신 위성 수. 정상 비행 보통 10+; 급감은 재밍/스푸핑 정황 |
| Eph_cm, Epv_cm | int | GPS 보고 **수평/수직 측위 오차 추정**(cm). 신뢰도 지표 |
| VelGround_cms | int | GPS 대지속도(cm/s) |
| CourseOverGround_cdeg | int | GPS 진행 방위(centi-deg) — 기수(Heading)와 어긋나면 측풍/이상 |
| **GpsInputInjected** | boolean | `MsgType=="GPS_INPUT"`일 때만 `true`. **`GPS_INPUT`은 외부 주입 API 메시지 — 실 GPS 수신기는 스스로 만들지 않음. 존재 자체가 스푸핑/주입 신호**(S1/S61 센서주입 사각지대 대응) |
| Hdop, Vdop | real | `GPS_INPUT` 주입 프레임이 자칭하는 수평/수직 정밀도 저하율 — 공격자가 조작한 "가짜 신뢰도" 값 |
| IgnoreFlags | int | `GPS_INPUT`의 필드 무시 비트마스크 — 어떤 필드를 실제로 주입했는지 |
| Roll_rad, Pitch_rad, Yaw_rad | real | IMU+EKF 산출 **자세각**(롤/피치/요, rad) |
| RollSpeed_rads, PitchSpeed_rads, YawSpeed_rads | real | 자이로 **각속도**(rad/s) |
| Airspeed_ms, Groundspeed_ms | real | 피토관 **대기속도** / GPS **대지속도**(m/s). 둘의 차이로 실속·측풍 판단 |
| Heading_deg | int | 기수 방위(deg) |
| Throttle_pct | int | 엔진/모터 스로틀 출력(%) |
| ClimbRate_ms | real | 수직 상승/강하율(m/s) |
| EkfFlags | int | EKF 상태 비트마스크(각 센서 융합 정상 여부 플래그) |
| **VelocityVariance** | real | **EKF 속도 잔차** — 추정 속도와 센서 관측의 불일치도. GPS 스푸핑 시 급등 → **S1 핵심** |
| **PosHorizVariance** | real | **EKF 수평 위치 잔차** — GPS 위치가 관성항법과 어긋날수록 상승 → **S1 핵심** |
| **PosVertVariance** | real | **EKF 수직 위치 잔차** (고도 스푸핑) |
| CompassVariance | real | EKF 자력계(나침반) 잔차 — 자기교란·스푸핑 |
| TerrainAltVariance | real | EKF 지형고도 잔차 |
| BatteryVoltage_mV | int | 배터리/항전 버스 전압(mV) — 전원 건전성 |
| BatteryCurrent_cA | int | 소모 전류(centi-A) — 부하 |
| BatteryRemaining_pct | int | 잔여 용량(%) — 체공 가능시간·RTL 트리거 근거 |
| OnboardCpuLoad_pct | real | FCC 온보드 CPU 부하(%) — 과부하/이상 연산 |
| ErrorsComm | int | 링크 통신 오류 누적 카운트 |
| DropRateComm_pct | real | 링크 패킷 드롭률(%) — 재밍/링크 열화 |
| VibrationX/Y/Z | real | 기체 진동(m/s²) — 기계적 이상·프롭 손상 |
| Clipping0/1/2 | int | 가속도계 포화(클리핑) 횟수 — 과도 진동 |
| **Command** | int | `COMMAND_LONG`에 담긴 MAV_CMD 번호 — 운영자/외부가 차량에 내린 명령. **A4 인젝션 핵심** |
| Confirmation | int | 명령 재전송 확인 카운터 |
| Param1~Param4 | real | 명령 파라미터(명령별 의미 상이, 예: 모드·좌표·ARM 여부) |
| TargetSystem, TargetComponent | int | 명령이 향하는 대상 시스템/컴포넌트 |
| Result | int | `COMMAND_ACK` 결과 (0=수락, 4=실패 등) — 명령 수용 여부 |
| Seq | int | 미션 웨이포인트 시퀀스 번호 |
| SystemStatus | int | `HEARTBEAT` 시스템 상태 (3=STANDBY 대기, 4=ACTIVE 비행중) |
| BaseMode | int | `HEARTBEAT` 기본 모드 플래그(무장·HIL·수동/자동 비트) |
| CustomMode | int | ArduPlane 비행 모드 (10=AUTO, 11=RTL, 5=FBWA, 0=MANUAL…) |
| MavlinkVersion | int | MAVLink 프로토콜 버전 |
| Severity | int | `STATUSTEXT` 심각도 (0=EMERG ~ 7=DEBUG) |
| Text | string | `STATUSTEXT` 본문 — FCC가 올리는 경고/상태 문자열 |

### 예시 값과 의미
- `MsgType="GLOBAL_POSITION_INT", AltRel_m=80.2, Groundspeed_ms=17.5, Lat=37.5412, Lon=127.031` → 홈 기준 고도 80m, 대지속도 17.5m/s로 순항 중인 정상 위치 보고.
- `MsgType="EKF_STATUS_REPORT", PosHorizVariance=0.12, VelocityVariance=0.08` → EKF 잔차가 0.1 안팎. 값이 0에 가까울수록 GPS·관성항법 융합이 잘 맞는다는 뜻(=항법 신뢰 높음).
- `FixType=3, SatellitesVisible=12, Eph_cm=80` → 3D 측위, 위성 12개 수신, 수평 측위오차 약 0.8m. 정상 측위 품질.
- `MsgType="HEARTBEAT", CustomMode=10, SystemStatus=4` → AUTO(자동 임무) 모드로 ACTIVE(비행 중). `CustomMode=11`이면 RTL(자동 복귀)로 비행 중이라는 뜻.
- `BatteryVoltage_mV=22100, BatteryRemaining_pct=46` → 6셀 기준 셀당 약 3.68V, 잔량 46%.
- `MsgType="GPS_INPUT", GpsInputInjected=true, SystemId=254` → 외부(주입기, SystemId 254=지상국 성격)에서 GPS_INPUT 프레임이 직접 주입됨 — 실 GPS 수신기 경로가 아닌 API 경로로 위치가 들어왔다는 확정적 증거.

### 시나리오 매핑

- **S1 GNSS 스푸핑** — `MsgType == "EKF_STATUS_REPORT" and PosHorizVariance > X`
- **S1/S61 GNSS 주입 원인 확정** — `MsgType == "GPS_INPUT" and GpsInputInjected == true` (재밍·스푸핑의 "시작"을 하류 EKF 잔차 없이 직접 포착)
- **A4 MAVLink 인젝션** — `MsgType == "COMMAND_LONG" and Command in (...)`
- **이상 경로 이탈** — `MsgType == "GLOBAL_POSITION_INT"` 좌표 vs 미션 plan join

### KQL 샘플

```kql
// S1 GNSS 스푸핑 1차 후보 (10분 윈도우, 잔차 임계 0.5)
UAVTelemetry_CL
| where TimeGenerated > ago(10m)
| where MsgType == "EKF_STATUS_REPORT"
| where PosHorizVariance > 0.5 or VelocityVariance > 0.5
| summarize MaxPosVar = max(PosHorizVariance), MaxVelVar = max(VelocityVariance) by UAVId, bin(TimeGenerated, 1m)
| where MaxPosVar > 0.5
```

```kql
// S1/S61 GNSS 주입 원인 → 하류 EKF 이상 인과 상관 (C8/C10 "재밍은 사각, 하류가 잡힘" 갭을
// GPS_INPUT 직접 관측으로 메움 — 재밍/주입 시작점 자체를 탐지)
UAVTelemetry_CL
| where TimeGenerated > ago(10m)
| where MsgType == "GPS_INPUT" and GpsInputInjected == true
| project TimeGenerated, UAVId, SystemId, Lat, Lon, Hdop, Vdop, IgnoreFlags
```

---

## 2. UAVOperator_CL

**출처**: `telemetry-tap` operator 필터 (COMMAND_LONG / COMMAND_ACK / MISSION_*).
**볼륨**: 중간.
**보존**: 90d / 180d.

> **이 테이블이 담는 실제 UAV 데이터**: 운영자(또는 외부 침입자)가 차량에 내린 **제어 명령**만 골라낸 것. 누가(SourceSystemId) 무엇을(ActionName) 언제 시켰는지의 감사 추적 — 인사이드 위협·명령 인젝션 조사의 1차 근거.

| 컬럼 | 타입 | 설명 (실제 UAV 데이터) |
|---|---|---|
| TimeGenerated | datetime | 명령 발생 시각 |
| UAVId | string | 명령을 받은 차량 |
| ActionName | string | 정규화된 조종 동작 — `arm_disarm`(무장/해제), `mode_change`(비행모드), `takeoff`/`vtol_takeoff`(이륙), `land`/`vtol_land`(착륙), `rtl`(복귀), `set_roi_location`/`set_roi_none`(관심지역 락온/해제), `mission_*`, `command_<id>` |
| MsgType | string | 원본 MAVLink 메시지 타입(`COMMAND_LONG` 등) |
| SourceSystemId, SourceComponentId | int | **명령을 보낸 주체** — 1=차량 자신, 254=tap, **255=GCS(정상 조종)**. 그 외 값이면 비인가 출처 |
| TargetSystemId, TargetComponentId | int | 명령이 향한 대상 차량/모듈 |
| Command | int | MAV_CMD 번호(아래 표 참조) |
| Confirmation | int | 명령 재전송 확인 카운터 |
| Param1~Param4 | real | 명령 파라미터(예: ARM=1/0, 모드 번호, ROI 좌표) |
| Result | int | `COMMAND_ACK` 수용 결과(0=수락) |
| Seq | int | 관련 미션 시퀀스 |

### 예시 값과 의미
- `ActionName="arm_disarm", Command=400, Param1=1, SourceSystemId=255, Result=0` → GCS(255)가 시동(ARM, Param1=1) 명령을 내렸고 차량이 수락(Result=0). Param1=0이면 시동 해제(DISARM).
- `ActionName="mode_change", Command=176, Param2=4, SourceSystemId=255` → 비행모드를 변경(예: GUIDED). 발신이 255=GCS이므로 정상 조종.
- `ActionName="set_roi_location", Command=195, Param5=37.541, Param6=127.031` → 짐벌을 지정 좌표(ROI)로 락온하라는 명령.
- `SourceSystemId=1` → 차량 자신이 보고한 ACK/상태(외부 명령이 아님).

### MAV_CMD 주요 번호
- 20 RTL, 21 LAND, 22 TAKEOFF, 84 VTOL_TAKEOFF, 85 VTOL_LAND
- 176 DO_SET_MODE, 195 DO_SET_ROI_LOCATION, 197 DO_SET_ROI_NONE
- 400 COMPONENT_ARM_DISARM

### 시나리오 매핑

- **A4 MAVLink 인젝션** — `SourceSystemId != 1 and ActionName == "arm_disarm"` (차량 아닌 곳에서 ARM 명령)
- **모드 변경 빈도** — `ActionName == "mode_change"` 1분당 카운트 (정상 1\~2회)

### KQL 샘플

```kql
// 비인가 ARM 명령 (vehicle source 가 아닌)
UAVOperator_CL
| where TimeGenerated > ago(15m)
| where ActionName == "arm_disarm"
| where SourceSystemId != 1
| project TimeGenerated, UAVId, ActionName, SourceSystemId, SourceComponentId, Param1
```

---

## 3. UAVMissionEvent_CL

**출처**: `telemetry-tap` 미션 라이프사이클 파생 (mode_change, mission_seq_advanced, waypoint_reached, takeoff/land/rtl 등).
**볼륨**: 낮음.
**보존**: 90d / 180d.

> **이 테이블이 담는 실제 UAV 데이터**: 비행 임무의 **상태 전이 타임라인** — 이륙·웨이포인트 도달·모드 전환·복귀 등 "임무가 지금 어느 단계인가"를 압축한 파생 이벤트. 사후검토(AAR)와 항로 이탈 상관분석용.

| 컬럼 | 타입 | 설명 (실제 UAV 데이터) |
|---|---|---|
| TimeGenerated | datetime | 이벤트 시각 |
| UAVId | string | 해당 차량 |
| EventName | string | 임무 단계 이벤트 — `takeoff`/`vtol_takeoff`(이륙), `waypoint_reached`(경유지 도달), `mission_seq_advanced`(시퀀스 진행), `mode_change`(모드 전환), `rtl`(복귀), `land`/`vtol_land`(착륙), `set_roi_*`, `arm_disarm` |
| MsgType | string | 파생 근거가 된 원본 MAVLink |
| Command | int | 관련 MAV_CMD |
| Seq | int | 미션 웨이포인트 시퀀스 번호 |
| Lat, Lon, AltMSL_m | real | 이벤트 발생 시점 차량의 마지막 알려진 위치/고도 |
| CustomModeBefore, CustomModeAfter | int | 모드 전환 시 이전→이후 ArduPlane 비행모드 번호 |

### 예시 값과 의미
- `EventName="vtol_takeoff", Seq=1, AltMSL_m=30` → 1번 시퀀스에서 수직이륙해 고도 30m 도달.
- `EventName="waypoint_reached", Seq=3, Lat=37.541, Lon=127.031` → 임무 3번 경유지에 도달.
- `EventName="mode_change", CustomModeBefore=10, CustomModeAfter=11` → AUTO(10)에서 RTL(11)로 전환 = 임무 중 자동 복귀 시작.
- `EventName="land", Seq=7` → 마지막 시퀀스에서 착륙(임무 종료).

### KQL 샘플

```kql
// 임무 타임라인 (한 비행 세션)
UAVMissionEvent_CL
| where TimeGenerated > ago(1h)
| where UAVId == "MPD-001"
| project TimeGenerated, EventName, Seq, Lat, Lon, AltMSL_m
| order by TimeGenerated asc
```

---

## 4. UAVPgse_CL

**출처**: `pgse-stub` REST API 결정 (preflight, firmware query, launch authorize).
**볼륨**: 낮음.
**보존**: 90d / 365d.

> **이 테이블이 담는 실제 UAV 데이터**: 출격 전 지상지원장비(PGSE)가 수행하는 **무결성 게이트 결정** — 탑재 펌웨어가 승인본과 같은지, 공급망(SBOM)이 깨끗한지, 발사를 인가할지. 실제 무인기 운용에서 "이 기체를 띄워도 되는가"를 판정하는 절차의 디지털 기록.

| 컬럼 | 타입 | 설명 (실제 UAV 데이터) |
|---|---|---|
| TimeGenerated | datetime | 결정 시각 |
| EventType | string | `preflight_check`(출격 전 검증), `firmware_query`(승인 펌웨어 조회), `launch_authorize`(발사 인가, 거부 포함) |
| UAVId | string | 대상 차량 |
| Operator | string | 절차를 호출한 운영자(정비/발사 담당) |
| Serial | string | 기체 일련번호(하드웨어 식별) |
| ImageHashSubmitted | string | 기체에 실제 탑재된 펌웨어 해시(`sha256:…`) |
| ImageHashExpected | string | 무기고에 등록된 **승인 펌웨어** 해시 |
| HashMatch | bool | 탑재본 = 승인본 여부. false = **펌웨어 변조 의심** |
| SbomForbidden | string | SBOM에서 발견된 금지 컴포넌트(예: `unsigned/x`) — 공급망 오염 |
| SbomForbiddenCount | int | 금지 컴포넌트 개수 |
| Passed | bool | 출격 전 검증 최종 통과 여부 |
| Found | bool | 조회한 기체가 무기고에 등록돼 있는지 |
| StatusCode | int | 처리 결과 HTTP 코드(200 정상 / 403·409 거부 / 404 없음) |
| FailReason | string | 실패 사유 — `no_preflight_on_record`(검증 없이 발사 시도), `preflight_failed`(검증 실패) 등 |
| TokenExpiresAt | datetime | 발사 인가 시 발급된 단기 토큰 만료 시각 |
| **Reason** | string | `firmware_update_mode_entered` 전용 — 진입 사유(예: `scheduled_ota`, `field_recovery`) |
| **Authorized** | boolean | `firmware_update_mode_entered` 전용 — 정비 절차 내 정상 진입이면 `true`. **T0800 핵심** — `false`면 정비 절차 밖에서 강제 진입시켜 FCC 제어루프를 중단시킨 비인가 시도 |

### 예시 값과 의미
- `EventType="firmware_query", Found=true, ImageHashExpected="sha256:00..01"` → 무기고에 등록된 승인 펌웨어 해시 조회 성공.
- `EventType="preflight_check", HashMatch=true, SbomForbiddenCount=0, Passed=true, StatusCode=200` → 탑재 펌웨어가 승인본과 일치하고 SBOM에 금지 컴포넌트 없음 → 출격 전 검증 통과.
- `EventType="launch_authorize", Passed=true, TokenExpiresAt="2026-06-23T07:15:00Z"` → 검증 통과 후 만료시각이 찍힌 단기 발사 토큰 발급.
- `HashMatch=false` 또는 `SbomForbiddenCount=2` → 탑재 펌웨어가 승인본과 다르거나 금지 컴포넌트 2개 포함(=`Passed=false`).
- `EventType="firmware_update_mode_entered", Authorized=false, Reason=""` → **T0800** — 정비 절차 밖에서 FCC가 펌웨어 업데이트 모드로 강제 진입, 비행 제어 중단 유발 시도.

### 시나리오 매핑

- **S4 펌웨어/공급망 변조** — `EventType == "preflight_check" and Passed == false`
- **인사이드 위협** — `EventType == "launch_authorize"`인데 `FailReason == "no_preflight_on_record"`
- **T0800 FW 업데이트 모드 강제 진입** — `EventType == "firmware_update_mode_entered" and Authorized == false`

### KQL 샘플

```kql
// 5분 내 preflight 실패 3회 이상 (반복 시도)
UAVPgse_CL
| where TimeGenerated > ago(30m)
| where EventType == "preflight_check" and Passed == false
| summarize FailCount = count() by Operator, UAVId, bin(TimeGenerated, 5m)
| where FailCount >= 3
```

---

## 5. UAVMissionPlan_CL

**출처**: `mps-stub` REST. 임무계획 생성/승인/릴리즈 + 2-person 위반.
**볼륨**: 매우 낮음.
**보존**: 180d / 730d (OSCAL 증거 — 가장 길게).

> **이 테이블이 담는 실제 UAV 데이터**: 무인기 **임무계획의 생애주기와 승인 통제**. 군 작전에서 무인기 임무는 한 사람이 임의로 못 띄우고 계획자≠승인자≠릴리즈(2인 통제)를 거치는데, 그 결재 흐름과 위반을 기록. OSCAL 증거로 가장 길게 보존.

| 컬럼 | 타입 | 설명 (실제 UAV 데이터) |
|---|---|---|
| TimeGenerated | datetime | 이벤트 시각 |
| EventType | string | 결재 단계 — `plan_created`(작성), `plan_approved`/`plan_approve_rejected`(승인/거부), `plan_released`/`plan_release_rejected`(출격 릴리즈/거부) |
| PlanId | string | 임무계획 식별 ID |
| UAVId | string | 임무 대상 차량 |
| Planner | string | 임무를 작성한 계획자 |
| Approver | string | 승인자(2인 통제 비교 대상; 미승인이면 빈값) |
| ReleasedBy | string | 최종 출격 릴리즈한 사람 |
| Callsign | string | 임무 콜사인 (예: `FALCON-1`) |
| Roe | string | **교전규칙** — `recon-only`(정찰 전용), `engage-confirmed-hostile`(확인된 적 교전) |
| PayloadConfig | string | 탑재 구성 — `EO_IR`(주야 카메라), `SAR`(레이더), `STRIKE_870G`(타격탄) |
| WaypointCount | int | 계획된 경유지 수 |
| Status | string | 계획 상태 — `DRAFT`→`APPROVED`→`RELEASED` |
| Comment | string | 승인 코멘트 |
| FailReason | string | 거부 사유 — `planner_equals_approver`(2인 통제 위반), `not_approved`(미승인 발사), `not_in_draft` |
| StatusCode | int | 처리 HTTP 코드 |

### 예시 값과 의미
- `EventType="plan_created", Planner="lt.kim", Status="DRAFT", Roe="recon-only", PayloadConfig="EO_IR", WaypointCount=5` → 김중위가 EO/IR 정찰 전용 임무 초안을 작성(경유지 5개), 아직 DRAFT.
- `EventType="plan_approved", Planner="lt.kim", Approver="capt.park", Status="APPROVED"` → 작성자(김중위)와 다른 박대위가 승인 = 2인 통제 충족.
- `EventType="plan_released", ReleasedBy="capt.park", Status="RELEASED"` → 승인된 계획이 출격 릴리즈됨.

### 시나리오 매핑

- **2-person 위반** — `EventType == "plan_approve_rejected" and FailReason == "planner_equals_approver"`
- **미승인 발사** — `EventType == "plan_release_rejected" and FailReason == "not_approved"`
- **OSCAL 증거** — `EventType in ("plan_approved","plan_released")` 시간순

### KQL 샘플

```kql
// 24시간 내 2-person 룰 위반
UAVMissionPlan_CL
| where TimeGenerated > ago(24h)
| where EventType == "plan_approve_rejected" and FailReason == "planner_equals_approver"
| project TimeGenerated, PlanId, Planner, UAVId, Callsign, Roe, PayloadConfig
```

---

## 6. UAVServiceAudit_CL

**출처**: `service-audit` (Kubernetes core/v1 Event watch, 클러스터 전역). AKS는 containerd 전용이라 `/var/run/docker.sock`이 없음 — Docker 데몬 이벤트 대신 `get/list/watch on events` ClusterRole만으로 파드 생애주기를 관측.
**볼륨**: 낮음~중간.
**보존**: 30d / 90d.

> **이 테이블이 담는 실제 UAV 데이터**: 비행체 데이터가 아니라 **시뮬 인프라(컨테이너) 자체의 생애 이벤트**. 실기체에 비유하면 "탑재 컴퓨터·서브시스템이 갑자기 꺼지거나 재시작됐다" 같은 *플랫폼 건전성* 신호 — 차량 텔레메트리엔 안 보이는 인프라 이상을 SOC가 보게 한다.

| 컬럼 | 타입 | 설명 (실제 의미) |
|---|---|---|
| TimeGenerated | datetime | 이벤트 시각 |
| EventType | string | K8s `involvedObject.kind` — 대부분 `Pod` |
| Action | string | K8s Event `reason` — `Pulled`/`Created`/`Started`/`Killing`(종료 지시)/`BackOff`/`Failed`/`FailedScheduling`/`Unhealthy`/`Preempted`/`Evicted`/`SuccessfulDelete`/`OOMKilling` |
| ActorId | string | 대상 파드 UID |
| ContainerName | string | 파드/컨테이너명 = 어떤 UAS 구성요소인지 (예: `telemetry-tap-xxxxx`) |
| ImageName | string | (미구현) core/v1 Event엔 이미지명이 없어 공란 — 필요시 파드 spec 조회로 보강 가능 |
| ExitCode | string | 이벤트 메시지에서 `exit code N` 패턴이 있을 때만 추출 — Docker 시절보다 커버리지 낮음(K8s Event는 종료코드를 항상 담지 않음) |
| Signal | string | (미구현, core/v1 Event에 없음) |
| ServiceLabel | string | 파드가 속한 네임스페이스(`soc`/`ground`/`link`/`air`/`c4i`) |
| ProjectLabel | string | 프로젝트 = `uav-sim-env` |
| Scope | string | 이벤트를 낸 컴포넌트(`kubelet`/`replicaset-controller` 등) |
| **IsDestructiveAction** | boolean | `Action in (Killing, Preempted, Evicted, SuccessfulDelete, OOMKilling)`일 때 `true`. 기존 K8s Event에서 파생 — 신규 producer 없이 **S66 데이터파괴류 행위를 기존 신호로 재해석** |
| **LogBearingTargetSuspected** | boolean | 대상 파드명이 로그 생산 구성요소(telemetry-tap·datalink-satcom·counter-uas 등) 또는 log/ndjson 패턴에 해당하면 `true`. **S47 anti-forensics(로그삭제) 핵심** — 파괴 대상이 "증거(로그) 그 자체"인지 구분 |

### 예시 값과 의미
- `EventType="Pod", Action="Started", ContainerName="av-muav-0"` → 비행체 파드가 정상 기동.
- `Action="Pulled", ImageName=""` → 새 이미지를 받아옴(파드명으로 어떤 구성요소인지 확인).
- `Action="OOMKilling", ContainerName="gcs-qgc-xxxxx"` → GCS 파드가 메모리 초과로 강제 종료(자원 부족 신호).
- `Action="Killing", ContainerName="telemetry-tap-xxxxx", IsDestructiveAction=true, LogBearingTargetSuspected=true` → **증거인멸 의심** — 텔레메트리 로그를 만들어내는 파드 자체가 강제 종료됨(S47 anti-forensics/S66 데이터파괴 패턴). 임무 실패·재밍 등과 시간 인접하면 은폐 목적 가능성.
- `Action="SuccessfulDelete", ContainerName="ti-stub-xxxxx", LogBearingTargetSuspected=false` → 로그와 무관한 파드 정리(정상 운영/스케일다운 가능성 높음).

### 시나리오 매핑

- **비행 중 SITL 죽음** — `Action == "Killing" and ContainerName startswith "av-muav"`
- **비인가 이미지 풀** — `Action == "Pulled"` + 파드 spec 조인으로 이미지 해시 검증
- **S47 anti-forensics / S66 데이터 파괴** — `IsDestructiveAction == true and LogBearingTargetSuspected == true`, 특히 다른 공격 시나리오(S1/S30 등) 탐지 직후 인접 시간대에 발생하면 우선순위 상향

### KQL 샘플 (S47/S66)

```kql
// 로그 생산 컴포넌트에 대한 파괴적 행위 — 다른 탐지 직후 은폐 시도 상관
UAVServiceAudit_CL
| where TimeGenerated > ago(30m)
| where IsDestructiveAction == true and LogBearingTargetSuspected == true
| project TimeGenerated, ContainerName, Action, ServiceLabel
```

---

## 7. UAVDatalink_CL

**출처**: `datalink-stats` 사이드카. 30초마다 `uav-datalink-los` 컨테이너의 네트워크 카운터.
**볼륨**: 일정 (2/분).
**보존**: 30d / 90d.

> **이 테이블이 담는 실제 UAV 데이터**: 데이터 링크(지상↔기체 통신 경로)의 **링크 건전성 지표**. 실기체로 치면 RF 단말의 수신/오류/드롭 통계 — 재밍이나 링크 열화가 일어나면 여기 드롭·오류가 먼저 튄다.

| 컬럼 | 타입 | 설명 (실제 UAV 데이터) |
|---|---|---|
| TimeGenerated | datetime | 폴링 시각(30초 주기) |
| ContainerName | string | 데이터링크 컨테이너(`uav-datalink-los`) |
| InterfaceName | string | 통신 인터페이스(`eth0` = RF 링크 모사) |
| RxBytes, RxPackets | long | 누적 수신량(기체→지상 텔레메트리 유입) |
| RxErrors, RxDropped | long | 누적 수신 오류/드롭 — **재밍·열화 시 급증** |
| TxBytes, TxPackets, TxErrors, TxDropped | long | 송신 측(지상→기체 명령) 통계 |
| CpuUsagePct | real | 링크 처리 부하(직전 폴 대비 %) |
| MemoryUsageBytes, MemoryLimitBytes | long | 메모리 사용/한도 |

### 예시 값과 의미
- `RxPackets=152340, RxErrors=0, RxDropped=12` → 누적 수신 15만여 패킷 중 드롭 12개(미미) = 링크 양호.
- 직전 폴 대비 `RxDropped`가 +500 → 30초 사이 500개 드롭 = 급격한 링크 열화(거리·간섭·재밍 정황).
- `RxBytes`/`TxBytes` 비율 → 하향(텔레메트리) 대비 상향(명령) 트래픽 균형. 명령 트래픽 급증은 비정상 제어 정황.

### 시나리오 매핑

- **재밍/링크 열화** — `RxDropped` 윈도우 델타 급증
- **이상 트래픽 (A4 인젝션)** — `RxBytes` 1분 델타 급증 + `UAVOperator_CL` Command 패턴 조인

### KQL 샘플

```kql
// 5분 윈도우 RxDropped 변화량
UAVDatalink_CL
| where TimeGenerated > ago(30m)
| order by TimeGenerated asc
| extend PrevDropped = prev(RxDropped)
| extend DroppedDelta = RxDropped - PrevDropped
| where isnotnull(DroppedDelta) and DroppedDelta > 100
```

---

## 8. UAVC4I_CL

**출처**: `c4i-stub` (ATCIS 명령 / MIMS 표적 / 우군 위치).
**볼륨**: 낮음.
**보존**: 180d / 365d.

> **이 테이블이 담는 실제 UAV 데이터**: 무인기 운용을 둘러싼 **작전 환경 그림(Operational Picture)** — 상급 C4I(지상전술 ATCIS·정보종합 MIMS)에서 내려오는 작전명령·표적정보·우군위치. UAV 텔레메트리와 결합해 "지금 이 비행이 명령·ROE에 부합하는가", "우군에 너무 가깝지 않은가"를 판단하는 맥락. (KUS-FS 확장 시 공군→육군 영상/표적 핸드오프도 EventType으로 추가)

| 컬럼 | 타입 | 설명 (실제 데이터) |
|---|---|---|
| TimeGenerated | datetime | 이벤트 시각 |
| EventType | string | `atcis_order_issued`(작전명령), `mims_target_update`(표적 갱신), `atcis_friendly_position`(우군 위치) |
| OrderId | string | ATCIS 작전명령 ID |
| Callsign | string | 명령 대상 UAV 콜사인 |
| OperationName | string | 작전명 (예: `WHITE_TIGER`) |
| Objective | string | 임무 목표 |
| Roe | string | 교전규칙(정찰/교전) |
| AreaLat, AreaLon, AreaRadiusM | real | 작전 책임 지역(중심 좌표+반경) |
| TargetPriority | string | 표적 우선순위 `LOW/MEDIUM/HIGH/CRITICAL` |
| IssuedBy | string | 명령 발행 지휘관 |
| TargetId | string | MIMS 표적 식별 ID |
| Lat, Lon, AltM | real | 표적 또는 우군의 위치/고도 |
| Classification | string | 표적 식별 — `FRIENDLY/HOSTILE/SUSPECT/NEUTRAL/UNKNOWN` |
| ConfidencePct | int | 표적 식별 신뢰도(%) |
| Source | string | 정보 출처 — `sigint`(신호)/`humint`(인간)/`uav-eoir`(무인기 영상) |
| ReportedBy | string | 표적 보고 주체 |
| UnitCallsign | string | 우군 부대 콜사인(동조사격 버퍼용) |
| StatusCode | int | 처리 코드 |
| **ClientIp** | string | `current_operation_read` 전용 — 작전 스냅샷을 조회한 클라이언트 IP |
| **ResponseBytes** | long | `current_operation_read` 전용 — 응답 페이로드 크기(byte). **T1567(Exfiltration Over Web Service) 핵심** — 정상 폴링(작음) 대비 반복적으로 크거나 비정상 IP에서의 조회는 합법 채널을 가장한 반출 정황 |

### 예시 값과 의미
- `EventType="atcis_order_issued", OperationName="WHITE_TIGER", Roe="recon-only", TargetPriority="HIGH"` → 정찰 전용 ROE의 고우선 작전명령 하달.
- `EventType="mims_target_update", Classification="HOSTILE", ConfidencePct=85, Source="uav-eoir"` → 무인기 영상으로 식별한 적성 표적, 신뢰도 85%.
- `EventType="atcis_friendly_position", UnitCallsign="EAGLE-2", Lat=..., Lon=...` → 우군 부대 위치 갱신(무인기 좌표와 근접 비교용).
- `EventType="current_operation_read", ClientIp="203.0.113.9", ResponseBytes=48210` → 작전 전체 스냅샷(명령·표적·우군위치)을 한 번에 읽어감. 정상 폴링 대비 비정상적으로 크거나 잦으면 T1567 정황.

### 시나리오 매핑

- **METT+TC 상관분석** — `EventType == "atcis_order_issued"` + `UAVTelemetry_CL` 경로 조인
- **fratricide 버퍼 위반** — `EventType == "atcis_friendly_position"` + `UAVTelemetry_CL` 위치 근접 join
- **T1567 REST 반출** — `EventType == "current_operation_read"` 빈도·`ResponseBytes` 급증 상관

---

## 9. UAVCyberPosture_CL

**출처**: `cyber-posture-stub`. CT-3 / CT-2 / CT-1 전이.
**볼륨**: 매우 낮음.
**보존**: 365d / 730d (가장 길게 — OSCAL 증거).

> **이 테이블이 담는 실제 UAV 데이터**: 작전을 둘러싼 **사이버 위협 태세(CT 단계)**. 무인기 자체 데이터는 아니지만, 평시(CT-3)냐 경계(CT-1)냐에 따라 SOC 탐지 룰의 임계를 동적으로 조절하는 근거가 된다.

| 컬럼 | 타입 | 설명 (실제 데이터) |
|---|---|---|
| TimeGenerated | datetime | 태세 이벤트 시각 |
| EventType | string | `posture_baseline`(기준 설정), `posture_changed`(전이) |
| PreviousLevel | string | 이전 태세 (`CT-3`/`CT-2`/`CT-1`) |
| Level | string | 현재 태세 (숫자 작을수록 고경계) |
| ChangedBy | string | 태세 변경 권한자 |
| Reason | string | 상향/하향 사유 |
| Source | string | 발령 출처 — `국정원`/`사이버사`/`internal` |
| StatusCode | int | 처리 코드 |

### 예시 값과 의미
- `EventType="posture_baseline", Level="CT-3"` → 평시 기준 태세(CT-3)로 설정됨.
- `EventType="posture_changed", PreviousLevel="CT-3", Level="CT-2", ChangedBy="capt.park", Source="사이버사"` → 사이버사 발령에 따라 평시(CT-3)→주의(CT-2)로 상향. 숫자가 작을수록 고경계.

### 사용 패턴

```kql
// 룰 감도 동적 조절 — 현재 태세 조회
UAVCyberPosture_CL
| top 1 by TimeGenerated desc
| project Level
```

다른 룰에서 위 결과를 `let posture =` 로 받아 임계값 조정.

---

## 10. UAVWeapon_CL

**출처**: `weapon-stub` (:8400). safety/lock/fire + 2-person 위반.
**볼륨**: 매우 낮음.
**보존**: 180d / 730d.

> **이 테이블이 담는 실제 UAV 데이터**: 무장 탑재기의 **무장 통제 3단계(안전 → 락온 → 발사)** 감사. 누가 언제 안전핀을 풀고, 어느 표적을 락온하고, 발사를 인가했는지 — 그리고 2인 통제 위반 같은 비정상 시도. 방산 운용의 핵심 통제선.

| 컬럼 | 타입 | 설명 (실제 UAV 데이터) |
|---|---|---|
| TimeGenerated | datetime | 무장 이벤트 시각 |
| EventType | string | `safety_set`(안전/무장 전환), `lock`/`lock_rejected`(표적 락온), `unlock`, `fire_authorized`/`fire_rejected`(발사 인가/거부) |
| WeaponId | string | 무장 페이로드 식별 (예: `MPD-001-PAYLOAD`) |
| Operator | string | 명령을 내린 운영자 |
| TargetId | string | 락온한 표적 ID |
| SafetyState | string | 현재 안전 상태 — `ARMED`(무장) / `SAFE`(안전) |
| SafetyStateBefore | string | 변경 전 안전 상태 |
| ArmedBy | string | 무장을 건 운영자(발사자와 다른지 2인 통제 비교) |
| Status | string | 결과 — `OK/LOCKED/UNLOCKED/AUTHORIZED/REJECTED` |
| FailReason | string | 거부 사유 — `safety_not_armed`(안전 미해제), `target_mismatch_or_unlocked`(락 없이 발사), `two_person_rule_violation`(동일인 무장+발사) |
| StatusCode | int | 처리 코드 |

### 예시 값과 의미
- `EventType="safety_set", SafetyStateBefore="SAFE", SafetyState="ARMED", ArmedBy="sgt.yang"` → 양상사가 안전→무장으로 전환.
- `EventType="lock", TargetId="T-001", Operator="capt.park", Status="LOCKED"` → 박대위가 표적 T-001 락온.
- `EventType="fire_authorized", Operator="capt.park", ArmedBy="sgt.yang", TargetId="T-001"` → 무장한 사람(양상사)과 발사 인가한 사람(박대위)이 달라 2인 통제 충족된 발사.

### 시나리오 매핑

- **2-person 위반** — `EventType == "fire_rejected" and FailReason == "two_person_rule_violation"`
- **언락 없이 발사 시도** — `EventType == "fire_rejected" and FailReason == "target_mismatch_or_unlocked"`

---

## 11. UAVThreatIntel_CL

**출처**: `ti-stub` (:8500). 인디케이터 / 피드 / 태세 권고.
**볼륨**: 낮음 (이벤트 기반).
**보존**: 180d / 365d.

> **이 테이블이 담는 실제 UAV 데이터**: 외부/내부 **위협 인텔리전스 피드** — 신규 취약점(CVE)·악성 IP·해시 등. 무인기 운용 환경(ArduPilot·링크·지상망)에 영향 줄 인디케이터가 들어오면 탐지 룰·차단 목록·태세를 갱신하는 입력.

| 컬럼 | 타입 | 설명 (실제 데이터) |
|---|---|---|
| TimeGenerated | datetime | 인텔 수신 시각 |
| EventType | string | `indicator_added`(단건), `feed_update`(일괄), `posture_recommendation`(태세 권고) |
| IndicatorType | string | 인디케이터 종류 — `cve`/`ip`/`hash`/`domain`/`url` |
| Indicator | string | 실제 값(CVE 번호·IP·파일 해시 등) |
| Severity | string | 심각도 `LOW/MEDIUM/HIGH/CRITICAL` |
| ConfidencePct | int | 인텔 신뢰도(%) |
| Source | string | 출처 — `NVD/CISA/AbuseIPDB/internal` |
| Description | string | 인디케이터 설명 |
| FeedName | string | 피드 이름(예: `CISA-KEV-2026-06`) |
| IndicatorCount | int | 일괄 피드의 인디케이터 수 |
| Recommendation | string | 권고 태세(예: CT-2 상향) |
| StatusCode | int | 처리 코드 |

### 예시 값과 의미
- `EventType="indicator_added", IndicatorType="cve", Indicator="CVE-2026-1234", Severity="CRITICAL", Source="CISA"` → CISA가 보고한 치명 CVE 1건 등록.
- `EventType="feed_update", FeedName="CISA-KEV-2026-06", IndicatorCount=37` → KEV 피드 37건 일괄 갱신.
- `EventType="posture_recommendation", Recommendation="CT-2"` → 인텔 기반으로 태세 CT-2 상향 권고(실제 변경은 별도).

### 시나리오 매핑

- **신규 CRITICAL CVE 도착** — `EventType == "indicator_added" and Severity == "CRITICAL"`
- **태세 상향 권고 vs 실제 변경 시차** — `UAVThreatIntel_CL`의 `posture_recommendation` + `UAVCyberPosture_CL` join

---

## 12. UAVOpAudit_CL

**출처**: `auth-stub` (:8600). 로그인 / 로그아웃 / 토큰 검증.
**볼륨**: 낮음.
**보존**: 90d / 365d.

> **이 테이블이 담는 실제 UAV 데이터**: 무인기를 운용하는 **운영자의 인증 활동**(로그인·세션·로그아웃). 조종사·계획자·승인자가 실제로 로그인했는지, 세션이 도용됐는지 — 인사이드 위협·계정 탈취 탐지의 기반.

| 컬럼 | 타입 | 설명 (실제 데이터) |
|---|---|---|
| TimeGenerated | datetime | 인증 이벤트 시각 |
| EventType | string | `login_success`/`login_failure`(로그인 성공/실패), `token_validated`/`token_validation_failed`(세션 검증), `logout`/`logout_unknown` |
| Operator | string | 운영자 계정명 |
| ClientIp | string | 접속 출발지 IP — 세션 중 바뀌면 도용 의심 |
| UserAgent | string | 접속 클라이언트(예: `qgc-desktop`) |
| SessionId | string | 발급된 세션 토큰 |
| FailReason | string | 실패 사유 — `invalid_credentials`/`wrong_password`/`unknown_session` |
| StatusCode | int | 처리 코드 |

### 예시 값과 의미
- `EventType="login_success", Operator="capt.park", ClientIp="10.50.0.30", SessionId="sess-9f3a", UserAgent="qgc-desktop"` → 박대위가 GCS에서 정상 로그인, 세션 발급.
- `EventType="login_failure", Operator="capt.park", FailReason="wrong_password"` → 비밀번호 오류로 로그인 실패.
- `EventType="token_validated", SessionId="sess-9f3a", ClientIp="10.50.0.55"` → 같은 세션이 다른 IP에서 검증됨(로그인 때 IP와 다르면 세션 이동/도용 가능성).

### 시나리오 매핑

- **brute force** — `EventType == "login_failure"` 단일 IP 1분 내 5회+
- **세션 IP 변경** — 같은 SessionId가 다른 ClientIp에서 사용

---

## 13. UAVFailsafe_CL

**출처**: `telemetry-tap` failsafe 필터 (STATUSTEXT severity ≤4 또는 모드 RTL/QRTL/QLand 전이).
**볼륨**: 매우 낮음 (이벤트 기반).
**보존**: 90d / 180d.

> **이 테이블이 담는 실제 UAV 데이터**: 비행체의 **안전장치(Failsafe) 발동**. 데이터링크 상실·저전압·GPS 이상 등으로 FCC가 경고를 올리거나 자동으로 복귀(RTL)·착륙 모드로 전환한 사건 — "기체가 스스로 위험을 감지하고 비상행동을 했다"는 신호.

| 컬럼 | 타입 | 설명 (실제 UAV 데이터) |
|---|---|---|
| TimeGenerated | datetime | 발동 시각 |
| UAVId | string | 해당 차량 |
| EventType | string | `statustext_warning`(경고 메시지), `mode_failsafe_transition`(자동 비상모드 전환), `heartbeat_gap_suspected`(HEARTBEAT 주기 이상 공백) |
| Severity | int | MAVLink 심각도 (0=EMERG, 1=ALERT, 2=CRIT, 3=ERR, 4=WARN) |
| Text | string | FCC 경고 본문(예: 링크 상실·배터리 부족) |
| ModeBefore | int | 비상 전환 직전 비행모드 |
| ModeAfter | int | 전환 후 모드 (11=RTL 복귀, 25=QRTL, 21=QLand) |
| **GapSec** | real | `heartbeat_gap_suspected` 전용 — 직전 HEARTBEAT 이후 경과 초(5초 초과 시 발동). **T0878(Alarm Suppression) 대리 신호** — 경보 메시지를 링크 상에서 가로채/드롭하는 억제는 그 행위 자체를 직접 기록할 방법이 없어(수신 못한 메시지는 로그 불가), 활성 비행 중(SystemStatus=4) HEARTBEAT 주기(~1Hz) 공백으로 대신 포착 |

### 예시 값과 의미
- `EventType="mode_failsafe_transition", ModeBefore=10, ModeAfter=11` → AUTO(10)에서 RTL(11)로 자동 전환 = 링크 상실/저전압 등으로 기체가 스스로 복귀 시작.
- `EventType="statustext_warning", Severity=2, Text="Battery critical"` → CRIT(2)급 배터리 위급 경고.
- `Severity=4, Text="GPS glitch"` → WARN(4)급 GPS 일시 이상 경고(즉시 비상행동은 아님).
- `EventType="heartbeat_gap_suspected", GapSec=12.4` → 활성 비행 중인데 12.4초간 HEARTBEAT가 끊김 — 링크상 경보/보고 메시지가 억제·차단됐을 가능성(T0878).

### KQL 샘플

```kql
// 15분 내 강제 failsafe 모드 전이
UAVFailsafe_CL
| where TimeGenerated > ago(15m)
| where EventType == "mode_failsafe_transition"
| project TimeGenerated, UAVId, ModeBefore, ModeAfter
```

```kql
// T0878 — HEARTBEAT 공백(경보 억제 의심) 반복 여부
UAVFailsafe_CL
| where TimeGenerated > ago(15m)
| where EventType == "heartbeat_gap_suspected"
| project TimeGenerated, UAVId, GapSec
```

---

## 14. UAVMavsec_CL

**출처**: `telemetry-tap` 30초 윈도우 MAVLink 서명 요약.
**볼륨**: 일정 (분당 2).
**보존**: 30d / 90d.

> **이 테이블이 담는 실제 UAV 데이터**: 링크 위 **MAVLink 메시지 서명(MAVSec) 상태**를 30초 윈도우로 집계한 것. 명령·텔레메트리가 서명돼 있는지(위·변조 방지) — 비서명 비율이 높으면 평문 인젝션에 취약한 상태.

| 컬럼 | 타입 | 설명 (실제 데이터) |
|---|---|---|
| TimeGenerated | datetime | 윈도우 종료 시각 |
| UAVId | string | 해당 차량 |
| EventType | string | `signing_check_summary` |
| SignedCount | long | 윈도우 내 **서명된** 메시지 수 |
| UnsignedCount | long | **비서명** 메시지 수 — 높으면 인젝션 노출 |
| FailedCount | long | 서명 검증 실패 수(MAVLink 2.0 서명 적용 후 위·변조 탐지) |
| WindowSec | int | 집계 윈도우 크기(초, =30) |

### 예시 값과 의미
- `SignedCount=0, UnsignedCount=600, FailedCount=0, WindowSec=30` → 30초간 600개 메시지가 전부 비서명. 현재 SITL이 MAVLink 서명을 안 쓰는 정상 상태(=평문 링크).
- (서명 적용 후) `SignedCount=590, UnsignedCount=10, FailedCount=0` → 대부분 서명됨. `FailedCount>0`이면 서명 검증 실패 = 위·변조 정황.

> 현재 SITL은 MAVLink 2.0 서명 미적용 → `UnsignedCount`만 카운트. Phase 2 (MAVSec 적용 후) `FailedCount > 0` 트리거 룰 가능.

---

## 15. UAVMaintenance_CL

**출처**: `pgse-stub` 정비 엔드포인트 (`/maintenance/battery/cycle`, `/calibration`, `/inspection/sign`).
**볼륨**: 매우 낮음.
**보존**: 365d / 730d.

> **이 테이블이 담는 실제 UAV 데이터**: 기체의 **정비·점검 이력** — 배터리 사이클, 센서 캘리브레이션, 점검표 서명. "이 기체가 출격 가능한 정비 상태인가"의 증거이며, 미점검 기체 발사 시도 같은 절차 위반 탐지에 쓰인다.

| 컬럼 | 타입 | 설명 (실제 UAV 데이터) |
|---|---|---|
| TimeGenerated | datetime | 정비 기록 시각 |
| EventType | string | `battery_cycle_logged`(배터리 사이클), `calibration_completed`(센서 보정), `inspection_signed`(점검 서명) |
| UAVId | string | 대상 차량 |
| Operator | string | 정비 담당자 |
| BatteryId | string | 배터리 식별자 |
| CycleCount | int | 누적 충방전 사이클 — 수명·열화 지표 |
| VoltageMin, VoltageMax | real | 사이클 중 전압 범위(V) — 셀 건전성 |
| ComponentName | string | 보정 대상 센서 — `compass`/`accel`/`gyro`/`esc` |
| ChecklistId | string | 점검표 ID |
| ItemsPassed, ItemsTotal | int | 점검 통과/전체 항목 수 |
| Notes | string | 정비 메모 |
| StatusCode | int | 처리 코드 |

### 예시 값과 의미
- `EventType="battery_cycle_logged", BatteryId="BAT-07", CycleCount=126, VoltageMin=3.5, VoltageMax=4.18` → 7번 배터리 누적 126사이클, 셀 전압이 정상 범위(3.5~4.18V).
- `EventType="calibration_completed", ComponentName="compass"` → 나침반 보정 완료.
- `EventType="inspection_signed", Operator="sgt.yang", ItemsPassed=18, ItemsTotal=18` → 점검 18/18 전 항목 통과, 양상사 서명.

### 시나리오 매핑

- **점검 미수행 차량 발사 시도** — `UAVPgse_CL` launch_authorize + 동일 UAVId의 `UAVMaintenance_CL` 최근 inspection_signed 부재 → 룰 alert

---

## 16. UAVImagery_CL

**출처**: `telemetry-tap` 카메라/짐벌 메시지 필터 (CAMERA_TRIGGER, CAMERA_IMAGE_CAPTURED, VIDEO_STREAM_INFORMATION, MOUNT_ORIENTATION, CAMERA_INFORMATION).
**볼륨**: 변동 (SITL 자동 발생 안 함, 외부 트리거 필요).
**보존**: 90d / 180d.

> **이 테이블이 담는 실제 UAV 데이터**: EO/IR 짐벌·카메라 페이로드의 **촬영/짐벌 활동** — 셔터 트리거, 이미지 캡처, 영상 스트림 정보, 짐벌 지향. "기체가 언제 어디를 찍었나"의 흔적(메타데이터). 영상 원본이 아니라 이벤트만 적재.

| 컬럼 | 타입 | 설명 (실제 UAV 데이터) |
|---|---|---|
| TimeGenerated | datetime | 페이로드 이벤트 시각 |
| UAVId | string | 해당 차량 |
| EventType | string | 소문자 메시지 타입 — `camera_trigger`(촬영), `camera_image_captured`, `video_stream_information`, `mount_orientation`(짐벌 지향) 등 |
| MsgType | string | 원본 MAVLink 메시지 타입 |

### 예시 값과 의미
- `EventType="camera_trigger", MsgType="CAMERA_TRIGGER"` → 카메라 셔터가 1회 작동(한 장 촬영).
- `EventType="mount_orientation", MsgType="MOUNT_ORIENTATION"` → 짐벌이 특정 방향으로 지향(어디를 보고 있나).
- `EventType="video_stream_information"` → 영상 스트림 메타(해상도·코덱 등) 보고.

> 현재 SITL 미션에서 카메라 트리거 메시지 안 발생. **시연용으로는 직접 MAVLink 인젝션 또는 ArduPilot DO_DIGICAM_CONTROL 명령 필요**.

---

## 17. UAVConfigAudit_CL

**출처**: `telemetry-tap` PARAM_VALUE 변화 추적.
**볼륨**: 부팅 시 다량 (persona_loaded) + 이후 변경 시.
**보존**: 180d / 730d.

> **이 테이블이 담는 실제 UAV 데이터**: 비행체 **파라미터(설정값) 변경 추적**. ArduPilot의 수백 개 파라미터(안전검사·failsafe·GPS·자폭 채널 등) 중 무엇이 언제 어떤 값으로 바뀌었는지 — 공격자가 안전장치를 무력화하거나 거동을 변조하는 시도를 잡는다.

| 컬럼 | 타입 | 설명 (실제 UAV 데이터) |
|---|---|---|
| TimeGenerated | datetime | 변경 시각 |
| UAVId | string | 해당 차량 |
| EventType | string | `persona_loaded`(부팅 시 초기값 적재) / `param_changed`(런타임 변경) |
| ParamId | string | 파라미터 이름 — 예: `ARMING_CHECK`(시동 안전검사), `FS_GCS_ENABL`(링크상실 failsafe) |
| ParamValueBefore | real | 변경 전 값(`persona_loaded`는 null) |
| ParamValueAfter | real | 변경 후 값 |
| Source | string | 변경 출처(현재 `sitl`) |

### 예시 값과 의미
- `EventType="persona_loaded", ParamId="ARMING_CHECK", ParamValueBefore=null, ParamValueAfter=0` → 부팅 시 시동 안전검사가 0(비활성)으로 적재됨(SITL 데모 기본값).
- `EventType="param_changed", ParamId="FS_GCS_ENABL", ParamValueBefore=1, ParamValueAfter=0` → 링크상실 failsafe를 1(켜짐)→0(꺼짐)으로 변경 = 안전장치 비활성화.
- `EventType="param_changed", ParamId="WPNAV_SPEED", ParamValueBefore=1500, ParamValueAfter=2500` → 항법 속도 파라미터 상향 변경.

### 시나리오 매핑

- **공격자 ARMING_CHECK 무력화** — `ParamId == "ARMING_CHECK" and ParamValueBefore == 1 and ParamValueAfter == 0`
- **failsafe 비활성화 시도** — `ParamId startswith "FS_"` and `ParamValueAfter == 0`

---

## 18. UAVResourceMetrics_CL

**출처**: `datalink-stats` 사이드카가 전 compose 컨테이너 폴링.
**볼륨**: 30초마다 컨테이너 수 × 행.
**보존**: 30d / 90d.

> **이 테이블이 담는 실제 UAV 데이터**: 시뮬을 구성하는 **모든 컨테이너(=UAS 구성요소)의 자원 사용량**. 실기체로 치면 각 서브시스템의 연산·메모리·IO 부하. 비정상 컨테이너 출현(크립토마이너 등)·OOM 임박 같은 인프라 이상 탐지용.

| 컬럼 | 타입 | 설명 (실제 의미) |
|---|---|---|
| TimeGenerated | datetime | 폴링 시각(30초 주기) |
| ContainerName | string | 컨테이너명 = 구성요소(예: `uav-av-mpd`=비행체) |
| CpuUsagePct | real | CPU 사용률(%) — 비정상 부하 |
| MemoryUsageBytes, MemoryLimitBytes | long | 메모리 사용/한도 — 비율 높으면 OOM 임박 |
| NetworkRxBytes, NetworkTxBytes | long | 누적 네트워크 수신/송신 |
| BlockReadBytes, BlockWriteBytes | long | 디스크 읽기/쓰기 IO |

### 예시 값과 의미
- `ContainerName="uav-av-mpd", CpuUsagePct=68, MemoryUsageBytes/MemoryLimitBytes≈0.42` → 비행체 SITL이 CPU 68%(가장 무거운 컨테이너, 정상), 메모리 42% 사용.
- `ContainerName="uav-pgse-stub", CpuUsagePct=0.4` → FastAPI 스텁은 거의 무부하.
- 알려지지 않은 `ContainerName` + 높은 `CpuUsagePct` → 예상 외 컨테이너가 자원을 점유(확인 대상).

### 시나리오 매핑

- **공격자 컨테이너 추가 (cryptominer 등)** — 새 ContainerName 등장 + CpuUsagePct 비정상
- **OOM 직전 예측** — MemoryUsageBytes / MemoryLimitBytes > 0.9

---

## 19. UAVDatalinkConn_CL

**출처**: `datalink-stats` 가 `uav-datalink-los` 안에서 `ss -tn -H` 실행 → 5760/5790/14550-2 포트 관련 TCP 연결 스냅샷.
**볼륨**: 30초마다 연결 수 × 행.
**보존**: 30d / 90d.

> **이 테이블이 담는 실제 UAV 데이터**: 데이터링크 지상 종단에 **누가 TCP로 붙어 있는지의 연결 스냅샷**. 정상 피어(GCS·tap) 외에 예상치 못한 원격 IP가 명령 포트(5790)에 연결됐는지 — MAVLink 평문 인젝션(A4)의 진입 흔적.

| 컬럼 | 타입 | 설명 (실제 의미) |
|---|---|---|
| TimeGenerated | datetime | 스냅샷 시각(30초 주기) |
| State | string | TCP 연결 상태 — `ESTAB`(연결됨)/`LISTEN`(대기) |
| LocalIp, LocalPort | string/int | 데이터링크 측 IP/포트 — 5760(SITL)/5790(외부 접속점)/14550-2 |
| PeerIp, PeerPort | string/int | 접속한 원격 측 — **알려지지 않은 PeerIp면 비인가 접속** |

### 예시 값과 의미
- `State="ESTAB", LocalPort=14550, PeerIp="10.50.0.30"` → GCS(정상 피어)가 텔레메트리 채널에 연결됨.
- `State="LISTEN", LocalPort=5790` → 외부 접속점이 연결 대기 중.
- `State="ESTAB", LocalPort=5790, PeerIp="10.50.0.99"` → 정상 피어 목록(GCS·tap)에 없는 IP가 명령 포트(5790)에 연결됨.

### 시나리오 매핑

- **A4 인젝션 — 비인가 클라이언트 5790 접속** — `LocalPort == 5790 and PeerIp not in known_ips`
- **연결 수 급증** — 분당 PeerIp distinct count > 임계

---

## 부록 A — 자주 쓰는 룰 패턴 모음

### 다중 테이블 join 예시

```kql
// S1 GNSS 스푸핑 + 임무 단계 상관
UAVTelemetry_CL
| where TimeGenerated > ago(15m)
| where MsgType == "EKF_STATUS_REPORT" and PosHorizVariance > 0.5
| join kind=inner (
    UAVMissionEvent_CL
    | where TimeGenerated > ago(15m)
    | project MissionTime = TimeGenerated, UAVId, EventName, Seq
) on UAVId
| where abs(datetime_diff('second', TimeGenerated, MissionTime)) < 60
| project TimeGenerated, UAVId, PosHorizVariance, EventName, Seq
```

```kql
// 사이버 태세 기반 동적 임계값
let posture = toscalar(
    UAVCyberPosture_CL
    | top 1 by TimeGenerated desc
    | project Level
);
let threshold = case(posture == "CT-1", 0.3, posture == "CT-2", 0.4, 0.5);
UAVTelemetry_CL
| where TimeGenerated > ago(15m)
| where MsgType == "EKF_STATUS_REPORT"
| where PosHorizVariance > threshold
```

### Watchlist 기반 룰 (예시 — 추후 정의)

```kql
// 승인된 운영자 명단 외 호출
let approved_operators = dynamic(["sgt.yang", "lt.kim", "capt.park", "maj.cho", "col.lee"]);
UAVWeapon_CL
| where TimeGenerated > ago(1h)
| where EventType == "lock"
| where Operator !in (approved_operators)
```

---

## 20. 확장 신규 테이블 (✅ 라이브 배포 확인 — 2026-06-25)

> 아래 5개는 KUS-FS급 확장(편대 + SATCOM)용 신규 테이블이다. **`infra/sentinel/tables.bicep` + 신규 `dcr-ext2.bicep` + `vm-monitoring.bicep`(3번째 DCRA)에 정의 완료**되었고, **2026-06-25 라이브 워크스페이스(`dah-data-law`)에 배포 확인됨** — 총 24개 `UAV*_CL` 존재, 세 번째 DCR `dah-data-uav-dcr-ext2`(5 스트림) 가동. DCR당 10-logFiles 한계로 primary(10)/extras(9)와 분리했다. 우선순위 순. (⏳ 미검증: 신규 테이블 실제 인입량·Sentinel 분석룰 활성 여부.)

### 20.1 `UAVSatcomLink_CL` (A순위 — 확장 핵심)
- **출처**: `datalink-satcom`(OpenSAND) 자체 NDJSON (`satcom.ndjson`). MAVLink 경로 아님.
- **위협면**: **S3**(SATCOM MITM·무결성·세션 하이재킹·재밍) + **S65 C2 은닉**(터널링/암호화/난독화/인코딩 — `/satcom/inject {type:"covert"}`로 시뮬).

| 컬럼 | 타입 | 설명 |
|---|---|---|
| TimeGenerated | datetime | |
| UAVId | string | 편대 식별 (예: `MUAV-001`) |
| LinkId | string | 위성 링크 식별 |
| SessionId | string | 위성 세션 ID (하이재킹 탐지) |
| Seq | long | 시퀀스 번호 (점프 탐지) |
| IntegrityStatus | string | `ok`/`signature_mismatch`/`replay` 등 |
| RttMs | real | 왕복 지연 (GEO ~600ms 기준 이상 탐지) |
| JamIndicator | real | 재밍 정황 지표 |
| SrcAddr, DstAddr | string | 링크 양단 |
| Mode | string | 현재 주입 모드: `normal`/`integrity`/`replay`/`jam`/`covert` |
| **Encoding** | string | `none`(평문)/`base64_tunnel`/`xor_obfuscated`/`dns_like_encode` — **S65 핵심**. 링크 무결성·재밍은 정상인데 인코딩만 바뀌는 것이 은닉 C2 특징 |
| **PayloadEntropy** | real | 페이로드 Shannon 엔트로피(0~8) 근사. 평문 MAVLink~3.5\~5, **은닉 C2 페이로드는 7.5+**(암호화/인코딩 특유의 고엔트로피) |
| **BeaconJitterSec** | real | 전송 간격의 불규칙성(초). 정상 트래픽은 지터 큼(0.5\~4s), **은닉 C2 비콘은 저지터(≤0.15s, 규칙적)** — TI에서 흔한 C2 비콘 탐지 지표를 링크 계층에 이식 |
| **PayloadBytes** | long | 링크 상태 틱당 페이로드 바이트량. 정상 하트비트 2\~8KB, **`exfil` 모드는 200KB\~2MB급 급증**. **T1011(Exfiltration Over Other Network Medium) 핵심** — 종전엔 SATCOM 링크에 용량 컬럼이 아예 없어 이 기법이 미포착이었음 |

**예시 값과 의미**
- `SessionId="S-1001", Seq=4521, IntegrityStatus="ok", RttMs=595, JamIndicator=0.02, Mode="normal", Encoding="none", PayloadEntropy=4.2` → 세션 정상 진행, RTT 595ms(GEO 위성의 정상 왕복 지연 범위), 무결성 ok, 재밍 정황 거의 없음, 평문 트래픽.
- `IntegrityStatus="signature_mismatch"` 또는 `Seq`가 비연속 점프 → 위성 링크 무결성 이상.
- `Mode="covert", IntegrityStatus="ok", JamIndicator=0.02, Encoding="dns_like_encode", PayloadEntropy=7.83, BeaconJitterSec=0.06` → **무결성·재밍 지표는 전부 정상인데 엔트로피 급등 + 규칙적 저지터 비콘** = 링크 자체는 멀쩡해 보이지만 은닉 C2가 흐르고 있다는 신호(킬체인 C9급 "완전 은밀" 패턴을 링크 계층에서 재현).
- `Mode="exfil", PayloadBytes=1450000, IntegrityStatus="ok"` → 링크 무결성은 정상인데 페이로드가 정상 하트비트 대비 200배 이상 급증 = SATCOM을 통한 대량 유출(T1011) 정황.

**KQL 샘플 (S65 은닉 C2 후보)**
```kql
UAVSatcomLink_CL
| where TimeGenerated > ago(15m)
| where PayloadEntropy > 7.0 and BeaconJitterSec < 0.3
| summarize CovertSamples = count(), AvgEntropy = avg(PayloadEntropy) by UAVId, LinkId, bin(TimeGenerated, 5m)
| where CovertSamples >= 3
```

### 20.2 `UAVSarPayload_CL` (A순위 — 확장 핵심)
- **출처**: `sar-stub` 자체 NDJSON. SAR 프레임 메타(+더미 이미지 메타).
- **위협면**: SAR 표적조작·영상유출·비정상 수집.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| TimeGenerated | datetime | |
| UAVId | string | |
| FrameId | string | SAR 프레임 식별 |
| TargetLat, TargetLon | real | 수집 표적 좌표 (임무 외 좌표 탐지) |
| Resolution | string | 해상도/모드 |
| SensorMode | string | `spot`/`strip`/`gmti` 등 |
| SizeBytes | long | 프레임 용량 (폭증 탐지) |

**예시 값과 의미**
- `FrameId="F-220", TargetLat=38.01, TargetLon=127.20, Resolution="0.3m", SensorMode="spot", SizeBytes=2400000` → 스폿 모드 0.3m 해상도 SAR 프레임 1장(~2.4MB)을 좌표 (38.01,127.20)에서 수집.
- `SensorMode="gmti"` → 지상이동표적표시 모드(이동 물체 탐지). `TargetLat/Lon`이 임무 영역 밖이면 비정상 수집.

### 20.3 `UAVGcsAccess_CL` (B순위 — 현행 갭)
- **출처**: `gcs-qgc`의 noVNC(`:8080`)/VNC(`:5900`) 접속 로그(websockify/x11vnc). 현재 **미수집 사각지대**.
- **의의**: 조종 콘솔 원격접속 자체 감사 — `UAVOpAudit_CL`(로그인)·`UAVOperator_CL`(명령)으로도 안 잡히는 "콘솔에 붙은 행위" 탐지.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| TimeGenerated | datetime | |
| ClientIp | string | 접속 IP |
| Transport | string | `novnc`/`vnc` |
| SessionStart, SessionEnd | datetime | 세션 구간 |
| UserAgent | string | 브라우저/클라이언트 |
| BytesTransferred | long | 전송량 |

**예시 값과 의미**
- `ClientIp="10.0.0.5", Transport="novnc", UserAgent="Mozilla/5.0...", SessionStart=...` → 브라우저로 noVNC 조종 콘솔에 접속한 세션 시작.
- `Transport="vnc", ClientIp="<사내망 외 IP>"` → 예상 밖 출발지에서 raw VNC로 직접 접속(확인 대상).

### 20.4 `UAVRouterStats_CL` (B순위 — 라우터 내부 가시성)
- **출처**: `datalink-los`의 mavlink-router 통계(`ReportStats=true`, `/tmp/mavlink-router.log`). `UAVDatalink_CL`(docker 네트워크 카운터)과 달리 **라우터 내부 지표**.
- **의의**: 라우팅 메시지 수·드롭·malformed MAVLink·라우팅 실패 탐지.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| TimeGenerated | datetime | |
| EndpointName | string | `av_in`/`gcs_out`/`tap_out`/`tcp_5790` |
| MsgRx, MsgTx | long | 라우팅 메시지 수 |
| MsgDropped | long | 드롭 |
| CrcErrors | long | malformed/CRC 오류 (인젝션 정황) |

**예시 값과 의미**
- `EndpointName="gcs_out", MsgRx=0, MsgTx=18230, MsgDropped=0, CrcErrors=0` → GCS 방향으로 18,230개 메시지 송출, 드롭·오류 없음(정상 라우팅).
- `CrcErrors>0` → 깨진/형식 불량 MAVLink 수신 = 평문 인젝션·손상 패킷 정황.

### 20.5 `UAVFleetState_CL` (C순위 — 선택; 분석룰 우선)
- 편대(2~4대) 동시 항로이탈·일괄 명령 등 횡적확산은 **기존 `UAVTelemetry_CL`/`UAVOperator_CL` 위 KQL 분석으로 우선 처리** 권장. 부하·재사용성이 문제될 때만 요약 테이블로 신설.
- (신설 시 안) `WindowStart`, `FleetId`, `ActiveUAVCount`, `DivergingCount`, `CommonCommand`, `AnomalyScore`.

**예시 값과 의미**
- `FleetId="MUAV-FLT-1", ActiveUAVCount=4, DivergingCount=0, AnomalyScore=0.05` → 편대 4대 전원 활성, 항로 이탈기 0대 = 정상 편대 비행.
- `ActiveUAVCount=4, DivergingCount=3, CommonCommand="mode_change"` → 4대 중 3대가 동시에 같은 모드변경 명령을 받고 항로 이탈 = 편대 단위 이상행위.

### 20.6 `UAVCounterUas_CL` (A순위 — S30/S31/S62 RF 시작단계 사각지대 정면 대응)
- **출처**: `counter-uas`(카운터-UAS 시뮬, 송신 없음) — 방어 자산 주변 RF emitter 수동 탐지 + 근접시 자동 재밍(J/S) 교전. `EventType`으로 두 레코드 종류가 한 스트림에 섞임: `rf_detection`(탐지) / `jam_engagement`(교전).
- **의의**: 킬체인 상세(C8/C10)에서 "GNSS/C2 재밍은 시작 단계가 사각지대(⚪), 하류 물리결과에서만 탐지"라고 명시된 갭을 메운다 — RF 재밍 그 자체를 최초로 직접 로깅. `UAVDatalink_CL`/`UAVTelemetry_CL`의 하류(AOI 이탈·EKF 분산) 상관 없이도 **재밍 원인을 즉시 식별** 가능.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| TimeGenerated | datetime | |
| EventType | string | `rf_detection` / `jam_engagement` (마커) |
| UAVId | string | 방어 자산 ID(`ASSET_ID`, 예 `CUAS-SITE-1`) |
| Seq | long | 레코드 순번 |
| TrackId | string | 침입 트랙 ID |
| Band | string | 탐지 대역(433M/915M/1.5G/2.4G/5.8G) — rf_detection 전용 |
| CenterFreqMHz | real | 중심주파수(MHz) — rf_detection 전용 |
| Rssi_dBm | real | 수신 RSSI — rf_detection 전용 |
| EstRange_m, TrueRange_m | real | 추정/실제 거리(m) — rf_detection 전용 |
| Bearing_deg | real | 방위각 — rf_detection 전용 |
| Classification | string | `hostile`/`unknown`/`friendly` — rf_detection 전용 |
| Protocol | string | 추정 프로토콜 — rf_detection 전용 |
| TargetBand | string | 재밍 대상 대역 — jam_engagement 전용 |
| JamFreqMHz | real | 재밍 주파수(MHz, 시뮬) — jam_engagement 전용 |
| JamMode | string | 재밍 모드 — jam_engagement 전용 |
| JamEirp_dBm | real | 재밍 EIRP(시뮬, 실송신 없음) — jam_engagement 전용 |
| JsRatio_dB | real | J/S 비(교전 효과 판정 근거) — jam_engagement 전용 |
| Effect | string | 효과(예: `link_denied`) — jam_engagement 전용 |
| Status | string | 트랙 상태(`jammed`/`retreating` 등) — jam_engagement 전용 |
| ReasonCode | string | 교전/미교전 사유 — jam_engagement 전용 |

**예시 값과 의미**
- `EventType="rf_detection", Band="2.4GHz", Classification="hostile", EstRange_m=210, TrueRange_m=204` → 적성 2.4GHz emitter가 210m 추정거리로 접근 탐지(S62 다중센서/근접 정찰 정황).
- `EventType="jam_engagement", TargetBand="2.4GHz", JsRatio_dB=18.2, Effect="link_denied", Status="jammed", ReasonCode="proximity_auto"` → 근접임계 이내 hostile 트랙에 자동 재밍 발동, 링크 차단 성공(S30/S31 카운터 대응 폐루프 증거).

### 보류 (표준 솔루션으로 충분 / 비용 대비 낮음)
- ArduPilot dataflash(.bin)·콘솔 로그 — 대용량, MAVLink로 대부분 커버.
- OS/호스트(Syslog·AzureActivity·네트워크 egress) — `vm-monitoring`/`azure-activity` 표준 수집.
- 영상/SAR 원본 바이너리 — 메타(`UAVImagery_CL`/`UAVSarPayload_CL`)로 충분.
- C4I 공군→육군 핸드오프 — 신규 테이블 대신 `UAVC4I_CL`에 EventType 추가.

---

## 부록 B — 데이터 모델 단순 그림

```
[차량/MAVLink 층]
  └── UAVTelemetry_CL (원본)
       ├── UAVOperator_CL (필터)
       ├── UAVMissionEvent_CL (파생)
       ├── UAVFailsafe_CL (severity 필터)
       ├── UAVImagery_CL (카메라 메시지 필터)
       ├── UAVConfigAudit_CL (PARAM_VALUE 변화)
       └── UAVMavsec_CL (서명 윈도우)

[운영/관제 층]
  ├── UAVPgse_CL          (펌웨어 + 발사 승인)
  ├── UAVMaintenance_CL   (정비)
  ├── UAVMissionPlan_CL   (임무 계획 + 2PR)
  ├── UAVC4I_CL           (ATCIS/MIMS)
  ├── UAVCyberPosture_CL  (CT-3/2/1)
  ├── UAVThreatIntel_CL   (TI 피드)
  ├── UAVWeapon_CL        (무장 안전·락·발사)
  └── UAVOpAudit_CL       (운영자 인증)

[인프라 층]
  ├── UAVServiceAudit_CL  (Kubernetes Event)
  ├── UAVDatalink_CL      (datalink 네트워크 카운터)
  ├── UAVResourceMetrics_CL (모든 컨테이너 리소스)
  └── UAVDatalinkConn_CL  (TCP 연결 스냅샷)
```

---

## 부록 C — 운영 메모

- 워크스페이스 customerId: `71a8f26e-2f37-4dc7-a172-dfb0df11d74a`
- DCE ingest endpoint: `https://dah-data-dce-ttt8.koreacentral-1.ingest.monitor.azure.com`
- DCR 1 (primary): `dah-data-uav-dcr` (10 streams)
- DCR 2 (extras): `dah-data-uav-dcr-extras` (9 streams)
- VM: `uavsim-vm` (RG `dah-sim-rg`), AMA + 양쪽 DCRA 적용됨.
- 인제스트 지연: 1\~10분 (저트래픽 테이블은 fluent-bit 버퍼 임계까지 대기).
- 스키마 변경 시: `infra/sentinel/tables.bicep` + `dcr*.bicep` 동시 갱신 → `./scripts/full-ingest.sh`.
