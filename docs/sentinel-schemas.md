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

| 컬럼 | 타입 | 설명 |
|---|---|---|
| TimeGenerated | datetime | 이벤트 시각 |
| UAVId | string | 차량 식별자 (예: `MPD-001`) |
| MsgType | string | MAVLink 메시지 타입명 (예: `EKF_STATUS_REPORT`) |
| SystemId | int | MAVLink source system id |
| ComponentId | int | MAVLink source component id |
| Lat, Lon | real | 위경도 (deg, GLOBAL_POSITION_INT에 한해 값) |
| AltMSL_m, AltRel_m | real | 해수면 / 상대 고도 (m) |
| VxNorth_cms, VyEast_cms, VzDown_cms | int | 북/동/하 속도 (cm/s) |
| Heading_cdeg | int | 진로 방위 (centi-deg, 0~36000) |
| X_m, Y_m, Z_m | real | LOCAL_POSITION_NED (m) |
| Vx_ms, Vy_ms, Vz_ms | real | LOCAL_POSITION_NED 속도 (m/s) |
| FixType | int | GPS fix 종류 (0=none, 2=2D, 3=3D, 4=DGPS, 5=RTK) |
| SatellitesVisible | int | 위성 수 |
| Eph_cm, Epv_cm | int | GPS 수평/수직 오차 (cm) |
| VelGround_cms | int | 지면속도 (cm/s) |
| CourseOverGround_cdeg | int | 진행 방위 (centi-deg) |
| Roll_rad, Pitch_rad, Yaw_rad | real | 자세 (rad) |
| RollSpeed_rads, PitchSpeed_rads, YawSpeed_rads | real | 각속도 (rad/s) |
| Airspeed_ms, Groundspeed_ms | real | 대기/지면속도 (m/s) |
| Heading_deg | int | 헤딩 (deg) |
| Throttle_pct | int | 스로틀 (%) |
| ClimbRate_ms | real | 상승률 (m/s) |
| EkfFlags | int | EKF status 비트마스크 |
| **VelocityVariance** | real | **EKF 속도 잔차 (S1 GNSS 스푸핑 핵심)** |
| **PosHorizVariance** | real | **EKF 수평 위치 잔차 (S1 핵심)** |
| **PosVertVariance** | real | **EKF 수직 위치 잔차** |
| CompassVariance | real | EKF 자기장 잔차 |
| TerrainAltVariance | real | EKF 지형 고도 잔차 |
| BatteryVoltage_mV | int | 배터리 전압 (mV) |
| BatteryCurrent_cA | int | 배터리 전류 (centi-A) |
| BatteryRemaining_pct | int | 배터리 잔량 (%) |
| OnboardCpuLoad_pct | real | 온보드 CPU 부하 (%) |
| ErrorsComm | int | 통신 오류 카운트 |
| DropRateComm_pct | real | 통신 드롭률 (%) |
| VibrationX/Y/Z | real | 진동 (m/s²) |
| Clipping0/1/2 | int | 가속도계 클리핑 카운트 |
| **Command** | int | **COMMAND_LONG의 MAV_CMD (A4 인젝션)** |
| Confirmation | int | 명령 confirmation 카운터 |
| Param1~Param4 | real | 명령 파라미터 |
| TargetSystem, TargetComponent | int | 명령 타겟 |
| Result | int | COMMAND_ACK 결과 (0=ACCEPTED, 4=FAILED 등) |
| Seq | int | 미션 시퀀스 번호 |
| SystemStatus | int | HEARTBEAT system status (3=STANDBY, 4=ACTIVE) |
| BaseMode | int | HEARTBEAT base mode 플래그 |
| CustomMode | int | ArduPlane custom mode (10=AUTO, 11=RTL, 5=FBWA, 0=MANUAL...) |
| MavlinkVersion | int | MAVLink 프로토콜 버전 |
| Severity | int | STATUSTEXT severity (0=EMERG ~ 7=DEBUG) |
| Text | string | STATUSTEXT 메시지 |

### 시나리오 매핑

- **S1 GNSS 스푸핑** — `MsgType == "EKF_STATUS_REPORT" and PosHorizVariance > X`
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

---

## 2. UAVOperator_CL

**출처**: `telemetry-tap` operator 필터 (COMMAND_LONG / COMMAND_ACK / MISSION_*).
**볼륨**: 중간.
**보존**: 90d / 180d.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| TimeGenerated | datetime | |
| UAVId | string | |
| ActionName | string | 정규화된 동작명 (`arm_disarm`, `mode_change`, `takeoff`, `vtol_takeoff`, `land`, `vtol_land`, `rtl`, `set_roi_location`, `set_roi_none`, `mission_current_changed`, `mission_waypoint_reached`, `ack_*`, `command_<id>`) |
| MsgType | string | 원본 MAVLink 메시지 타입 |
| SourceSystemId, SourceComponentId | int | 명령 발신자 (1=차량, 254=tap, 255=GCS) |
| TargetSystemId, TargetComponentId | int | 명령 대상 |
| Command | int | MAV_CMD 번호 |
| Confirmation | int | COMMAND_LONG confirmation |
| Param1~Param4 | real | 명령 파라미터 |
| Result | int | COMMAND_ACK 결과 |
| Seq | int | 미션 seq |

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

| 컬럼 | 타입 | 설명 |
|---|---|---|
| TimeGenerated | datetime | |
| UAVId | string | |
| EventName | string | 정규화 (`mode_change`, `mission_seq_advanced`, `waypoint_reached`, `takeoff`, `vtol_takeoff`, `land`, `vtol_land`, `rtl`, `set_roi_location`, `set_roi_none`, `arm_disarm`) |
| MsgType | string | 원본 MAVLink |
| Command | int | MAV_CMD |
| Seq | int | 미션 시퀀스 |
| Lat, Lon, AltMSL_m | real | 이벤트 발생 시 마지막 알려진 위치 |
| CustomModeBefore, CustomModeAfter | int | 모드 변경 시 이전/이후 (ArduPlane 모드 번호) |

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

| 컬럼 | 타입 | 설명 |
|---|---|---|
| TimeGenerated | datetime | |
| EventType | string | `preflight_check`, `firmware_query`, `launch_authorize`, `launch_authorize` 거부도 동일 EventType |
| UAVId | string | |
| Operator | string | 호출 운영자 |
| Serial | string | UAV 일련번호 |
| ImageHashSubmitted | string | 제출된 펌웨어 해시 (`sha256:...`) |
| ImageHashExpected | string | 승인된 펌웨어 해시 |
| HashMatch | bool | 해시 일치 여부 |
| SbomForbidden | string | 콤마 구분 금지 SBOM 컴포넌트 (예: `unsigned/x,unsigned/y`) |
| SbomForbiddenCount | int | 금지 컴포넌트 수 |
| Passed | bool | preflight 통과 여부 |
| Found | bool | firmware_query에서 등록 여부 |
| StatusCode | int | HTTP 상태 (200/403/404/409) |
| FailReason | string | `no_preflight_on_record`, `preflight_failed` 등 |
| TokenExpiresAt | datetime | launch_authorize 토큰 만료 시각 |

### 시나리오 매핑

- **S4 펌웨어/공급망 변조** — `EventType == "preflight_check" and Passed == false`
- **인사이드 위협** — `EventType == "launch_authorize"`인데 `FailReason == "no_preflight_on_record"`

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

| 컬럼 | 타입 | 설명 |
|---|---|---|
| TimeGenerated | datetime | |
| EventType | string | `plan_created`, `plan_approved`, `plan_approve_rejected`, `plan_released`, `plan_release_rejected` |
| PlanId | string | 무작위 ID |
| UAVId | string | |
| Planner | string | 계획자 |
| Approver | string | 승인자 (없으면 빈값) |
| ReleasedBy | string | 릴리즈한 사람 |
| Callsign | string | (예: `FALCON-1`) |
| Roe | string | 교전규칙 (`recon-only`, `engage-confirmed-hostile`) |
| PayloadConfig | string | (`EO_IR`, `SAR`, `STRIKE_870G`) |
| WaypointCount | int | waypoint 수 |
| Status | string | `DRAFT`, `APPROVED`, `RELEASED` |
| Comment | string | 승인 코멘트 |
| FailReason | string | `not_in_draft`, `planner_equals_approver`, `not_approved` |
| StatusCode | int | HTTP 코드 |

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

**출처**: `service-audit` 사이드카 (`/var/run/docker.sock` 이벤트 스트림).
**볼륨**: 낮음~중간.
**보존**: 30d / 90d.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| TimeGenerated | datetime | |
| EventType | string | `container`, `image`, `network`, `volume` |
| Action | string | `start`, `die`, `kill`, `oom`, `restart`, `pull`, `exec_create` 등 |
| ActorId | string | 컨테이너 / 이미지 / 네트워크 id (64자 SHA) |
| ContainerName | string | (예: `uav-av-mpd`) |
| ImageName | string | (예: `uav-sim-env-av-mpd`) |
| ExitCode | string | die 이벤트의 종료 코드 |
| Signal | string | kill 이벤트의 시그널 |
| ServiceLabel | string | docker-compose 서비스명 |
| ProjectLabel | string | `uav-sim-env` |
| Scope | string | `local` |

### 시나리오 매핑

- **비행 중 SITL 죽음** — `Action == "die" and ServiceLabel == "av-mpd"`
- **비인가 이미지 풀** — `Action == "pull" and ImageName not in (...)`

---

## 7. UAVDatalink_CL

**출처**: `datalink-stats` 사이드카. 30초마다 `uav-datalink-los` 컨테이너의 네트워크 카운터.
**볼륨**: 일정 (2/분).
**보존**: 30d / 90d.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| TimeGenerated | datetime | |
| ContainerName | string | `uav-datalink-los` |
| InterfaceName | string | `eth0` |
| RxBytes, RxPackets | long | 누적 수신 |
| RxErrors, RxDropped | long | 누적 오류/드롭 |
| TxBytes, TxPackets, TxErrors, TxDropped | long | 송신 측 |
| CpuUsagePct | real | 직전 폴 대비 CPU 사용률 (%) |
| MemoryUsageBytes, MemoryLimitBytes | long | 메모리 |

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

| 컬럼 | 타입 | 설명 |
|---|---|---|
| TimeGenerated | datetime | |
| EventType | string | `atcis_order_issued`, `mims_target_update`, `atcis_friendly_position` |
| OrderId | string | ATCIS 명령 ID |
| Callsign | string | UAV 콜사인 |
| OperationName | string | (예: `WHITE_TIGER`) |
| Objective | string | 임무 목표 |
| Roe | string | 교전규칙 |
| AreaLat, AreaLon, AreaRadiusM | real | 작전 지역 |
| TargetPriority | string | `LOW/MEDIUM/HIGH/CRITICAL` |
| IssuedBy | string | 명령 발행자 |
| TargetId | string | MIMS 표적 ID |
| Lat, Lon, AltM | real | 표적/우군 위치 |
| Classification | string | `UNKNOWN/FRIENDLY/NEUTRAL/HOSTILE/SUSPECT` |
| ConfidencePct | int | 표적 신뢰도 |
| Source | string | `sigint/humint/uav-eoir` |
| ReportedBy | string | 표적 보고자 |
| UnitCallsign | string | 우군 단위 |
| StatusCode | int | |

### 시나리오 매핑

- **METT+TC 상관분석** — `EventType == "atcis_order_issued"` + `UAVTelemetry_CL` 경로 조인
- **fratricide 버퍼 위반** — `EventType == "atcis_friendly_position"` + `UAVTelemetry_CL` 위치 근접 join

---

## 9. UAVCyberPosture_CL

**출처**: `cyber-posture-stub`. CT-3 / CT-2 / CT-1 전이.
**볼륨**: 매우 낮음.
**보존**: 365d / 730d (가장 길게 — OSCAL 증거).

| 컬럼 | 타입 | 설명 |
|---|---|---|
| TimeGenerated | datetime | |
| EventType | string | `posture_baseline`, `posture_changed` |
| PreviousLevel | string | 이전 태세 (`CT-3` 등) |
| Level | string | 현재 태세 |
| ChangedBy | string | 변경자 |
| Reason | string | 변경 사유 |
| Source | string | `국정원`, `사이버사`, `internal` |
| StatusCode | int | |

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

| 컬럼 | 타입 | 설명 |
|---|---|---|
| TimeGenerated | datetime | |
| EventType | string | `safety_set`, `lock`, `lock_rejected`, `unlock`, `fire_authorized`, `fire_rejected` |
| WeaponId | string | `MPD-001-PAYLOAD` |
| Operator | string | 명령 운영자 |
| TargetId | string | 락온 표적 |
| SafetyState | string | `ARMED` / `SAFE` |
| SafetyStateBefore | string | 변경 전 상태 |
| ArmedBy | string | 무장 운영자 (2-person 비교용) |
| Status | string | `OK`, `LOCKED`, `UNLOCKED`, `AUTHORIZED`, `REJECTED` |
| FailReason | string | `safety_not_armed`, `target_mismatch_or_unlocked`, `two_person_rule_violation` |
| StatusCode | int | |

### 시나리오 매핑

- **2-person 위반** — `EventType == "fire_rejected" and FailReason == "two_person_rule_violation"`
- **언락 없이 발사 시도** — `EventType == "fire_rejected" and FailReason == "target_mismatch_or_unlocked"`

---

## 11. UAVThreatIntel_CL

**출처**: `ti-stub` (:8500). 인디케이터 / 피드 / 태세 권고.
**볼륨**: 낮음 (이벤트 기반).
**보존**: 180d / 365d.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| TimeGenerated | datetime | |
| EventType | string | `indicator_added`, `feed_update`, `posture_recommendation` |
| IndicatorType | string | `cve`, `ip`, `hash`, `domain`, `url` |
| Indicator | string | 실제 값 (CVE 번호 / IP / 해시) |
| Severity | string | `LOW/MEDIUM/HIGH/CRITICAL` |
| ConfidencePct | int | |
| Source | string | `NVD/CISA/AbuseIPDB/internal` |
| Description | string | 인디케이터 설명 |
| FeedName | string | 피드 이름 (CISA-KEV-2026-06 등) |
| IndicatorCount | int | feed_update에서 일괄 개수 |
| Recommendation | string | posture_recommendation 권장 태세 |
| StatusCode | int | |

### 시나리오 매핑

- **신규 CRITICAL CVE 도착** — `EventType == "indicator_added" and Severity == "CRITICAL"`
- **태세 상향 권고 vs 실제 변경 시차** — `UAVThreatIntel_CL`의 `posture_recommendation` + `UAVCyberPosture_CL` join

---

## 12. UAVOpAudit_CL

**출처**: `auth-stub` (:8600). 로그인 / 로그아웃 / 토큰 검증.
**볼륨**: 낮음.
**보존**: 90d / 365d.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| TimeGenerated | datetime | |
| EventType | string | `login_success`, `login_failure`, `token_validated`, `token_validation_failed`, `logout`, `logout_unknown` |
| Operator | string | 사용자명 |
| ClientIp | string | 접속 IP |
| UserAgent | string | 클라이언트 (qgc-desktop 등) |
| SessionId | string | 세션 토큰 |
| FailReason | string | `invalid_credentials`, `wrong_password`, `unknown_session` |
| StatusCode | int | |

### 시나리오 매핑

- **brute force** — `EventType == "login_failure"` 단일 IP 1분 내 5회+
- **세션 IP 변경** — 같은 SessionId가 다른 ClientIp에서 사용

---

## 13. UAVFailsafe_CL

**출처**: `telemetry-tap` failsafe 필터 (STATUSTEXT severity ≤4 또는 모드 RTL/QRTL/QLand 전이).
**볼륨**: 매우 낮음 (이벤트 기반).
**보존**: 90d / 180d.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| TimeGenerated | datetime | |
| UAVId | string | |
| EventType | string | `statustext_warning`, `mode_failsafe_transition` |
| Severity | int | MAVLink severity (0=EMERG, 1=ALERT, 2=CRIT, 3=ERR, 4=WARN) |
| Text | string | STATUSTEXT 메시지 본문 |
| ModeBefore | int | 모드 전이 직전 |
| ModeAfter | int | 전이 후 (11=RTL, 25=QRTL, 21=QLand) |

### KQL 샘플

```kql
// 15분 내 강제 failsafe 모드 전이
UAVFailsafe_CL
| where TimeGenerated > ago(15m)
| where EventType == "mode_failsafe_transition"
| project TimeGenerated, UAVId, ModeBefore, ModeAfter
```

---

## 14. UAVMavsec_CL

**출처**: `telemetry-tap` 30초 윈도우 MAVLink 서명 요약.
**볼륨**: 일정 (분당 2).
**보존**: 30d / 90d.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| TimeGenerated | datetime | |
| UAVId | string | |
| EventType | string | `signing_check_summary` |
| SignedCount | long | 윈도우 내 서명된 메시지 수 |
| UnsignedCount | long | 비서명 메시지 수 |
| FailedCount | long | 서명 검증 실패 수 (현재 0, MAVLink 2.0 통합 시 확장) |
| WindowSec | int | 윈도우 크기 (30) |

> 현재 SITL은 MAVLink 2.0 서명 미적용 → `UnsignedCount`만 카운트. Phase 2 (MAVSec 적용 후) `FailedCount > 0` 트리거 룰 가능.

---

## 15. UAVMaintenance_CL

**출처**: `pgse-stub` 정비 엔드포인트 (`/maintenance/battery/cycle`, `/calibration`, `/inspection/sign`).
**볼륨**: 매우 낮음.
**보존**: 365d / 730d.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| TimeGenerated | datetime | |
| EventType | string | `battery_cycle_logged`, `calibration_completed`, `inspection_signed` |
| UAVId | string | |
| Operator | string | 정비 담당 |
| BatteryId | string | 배터리 식별자 |
| CycleCount | int | 충방전 사이클 |
| VoltageMin, VoltageMax | real | 사이클 중 전압 범위 (V) |
| ComponentName | string | calibration 대상 (`compass`, `accel`, `gyro`, `esc`) |
| ChecklistId | string | 점검표 ID |
| ItemsPassed, ItemsTotal | int | 통과/전체 항목 |
| Notes | string | 자유서식 메모 |
| StatusCode | int | |

### 시나리오 매핑

- **점검 미수행 차량 발사 시도** — `UAVPgse_CL` launch_authorize + 동일 UAVId의 `UAVMaintenance_CL` 최근 inspection_signed 부재 → 룰 alert

---

## 16. UAVImagery_CL

**출처**: `telemetry-tap` 카메라/짐벌 메시지 필터 (CAMERA_TRIGGER, CAMERA_IMAGE_CAPTURED, VIDEO_STREAM_INFORMATION, MOUNT_ORIENTATION, CAMERA_INFORMATION).
**볼륨**: 변동 (SITL 자동 발생 안 함, 외부 트리거 필요).
**보존**: 90d / 180d.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| TimeGenerated | datetime | |
| UAVId | string | |
| EventType | string | 소문자 메시지 타입 (`camera_trigger` 등) |
| MsgType | string | 원본 MAVLink 메시지 타입 |

> 현재 SITL 미션에서 카메라 트리거 메시지 안 발생. **시연용으로는 직접 MAVLink 인젝션 또는 ArduPilot DO_DIGICAM_CONTROL 명령 필요**.

---

## 17. UAVConfigAudit_CL

**출처**: `telemetry-tap` PARAM_VALUE 변화 추적.
**볼륨**: 부팅 시 다량 (persona_loaded) + 이후 변경 시.
**보존**: 180d / 730d.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| TimeGenerated | datetime | |
| UAVId | string | |
| EventType | string | `persona_loaded` (첫 값) / `param_changed` (이후 변경) |
| ParamId | string | 파라미터 이름 (`ARMING_CHECK`, `FS_GCS_ENABL` 등) |
| ParamValueBefore | real | 변경 전 값 (`persona_loaded`는 null) |
| ParamValueAfter | real | 변경 후 값 |
| Source | string | `sitl` (현재 단일 출처) |

### 시나리오 매핑

- **공격자 ARMING_CHECK 무력화** — `ParamId == "ARMING_CHECK" and ParamValueBefore == 1 and ParamValueAfter == 0`
- **failsafe 비활성화 시도** — `ParamId startswith "FS_"` and `ParamValueAfter == 0`

---

## 18. UAVResourceMetrics_CL

**출처**: `datalink-stats` 사이드카가 전 compose 컨테이너 폴링.
**볼륨**: 30초마다 컨테이너 수 × 행.
**보존**: 30d / 90d.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| TimeGenerated | datetime | |
| ContainerName | string | (예: `uav-av-mpd`) |
| CpuUsagePct | real | |
| MemoryUsageBytes, MemoryLimitBytes | long | |
| NetworkRxBytes, NetworkTxBytes | long | 누적 |
| BlockReadBytes, BlockWriteBytes | long | 디스크 IO |

### 시나리오 매핑

- **공격자 컨테이너 추가 (cryptominer 등)** — 새 ContainerName 등장 + CpuUsagePct 비정상
- **OOM 직전 예측** — MemoryUsageBytes / MemoryLimitBytes > 0.9

---

## 19. UAVDatalinkConn_CL

**출처**: `datalink-stats` 가 `uav-datalink-los` 안에서 `ss -tn -H` 실행 → 5760/5790/14550-2 포트 관련 TCP 연결 스냅샷.
**볼륨**: 30초마다 연결 수 × 행.
**보존**: 30d / 90d.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| TimeGenerated | datetime | |
| State | string | `ESTAB`, `LISTEN` 등 |
| LocalIp, LocalPort | string/int | datalink-los 측 |
| PeerIp, PeerPort | string/int | 원격 측 |

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

## 20. 추가 테이블 후보 (확장 시 — 아직 미배포)

> 아래는 KUS-FS급 확장 검토에서 도출된 **추가 테이블 후보**다. 현재 tables.bicep/dcr에는 **없으며**, 실제 Sentinel 반영은 확장 단계에서 진행한다. 우선순위 순.

### 20.1 `UAVSatcomLink_CL` (A순위 — 확장 핵심)
- **출처**: `datalink-satcom`(OpenSAND) 자체 NDJSON (`satcom.ndjson`). MAVLink 경로 아님.
- **위협면**: **S3**(SATCOM MITM·무결성·세션 하이재킹·재밍).

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

### 20.5 `UAVFleetState_CL` (C순위 — 선택; 분석룰 우선)
- 편대(2~4대) 동시 항로이탈·일괄 명령 등 횡적확산은 **기존 `UAVTelemetry_CL`/`UAVOperator_CL` 위 KQL 분석으로 우선 처리** 권장. 부하·재사용성이 문제될 때만 요약 테이블로 신설.
- (신설 시 안) `WindowStart`, `FleetId`, `ActiveUAVCount`, `DivergingCount`, `CommonCommand`, `AnomalyScore`.

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
  ├── UAVServiceAudit_CL  (Docker 이벤트)
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
