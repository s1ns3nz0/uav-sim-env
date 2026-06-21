# QGroundControl (noVNC) 운용 가이드 (전체판)

브라우저만으로 클라우드 UAV 시뮬레이션의 GCS(QGroundControl)에 접속해서 미션을 띄우고, 새 미션을 만들고, 새 기체를 추가하고, 문제를 진단하는 방법.

> **대상**: 팀원 누구나 (Mac/Windows/Linux/모바일)
> **필요한 것**: 모던 브라우저 (Chrome 권장)
> **로컬에 QGC 설치 불필요** — 컨테이너 안에서 Xvfb + noVNC

---

## 목차

1. 접속 정보
2. 첫 접속 + UI 한눈에
3. 기존 미션으로 비행 (가장 빠른 시연)
4. 미션 파일이 어디에 저장되는가
5. QGC에서 미션 처음부터 만들기 (GUI)
6. 만든 미션을 컨테이너에 영구 저장하기
7. 미션 파일 (.plan) 포맷 직접 편집
8. 새 기체(UAV) 추가하기 — 멀티 UAV 시뮬
9. 페르소나 파일 커스터마이즈
10. 비행 중 관측 + 백그라운드 인제스트
11. 시연 시나리오 5종
12. 트러블슈팅 매트릭스
13. 단축키 + 참조표 (MAV_CMD / 모드 / 프레임)
14. 운영 메타 + 종료

---

## 1. 접속 정보

### 호스트
- 도메인: **`sim.pollak.store`** (양진수 소유, 한국 Azure VM으로 매핑)
- 원본 FQDN: `uavsim-2kv7vfcrafu3o.koreacentral.cloudapp.azure.com` (직접 접근도 가능)

### 접속 URL

| 용도 | URL |
|---|---|
| **QGroundControl (브라우저)** | **`http://sim.pollak.store:8080/vnc.html`** |
| pgse-stub Swagger | `http://sim.pollak.store:8000/docs` |
| mps-stub Swagger | `http://sim.pollak.store:8100/docs` |
| c4i-stub Swagger | `http://sim.pollak.store:8200/docs` |
| cyber-posture Swagger | `http://sim.pollak.store:8300/docs` |
| weapon-stub Swagger | `http://sim.pollak.store:8400/docs` |
| ti-stub Swagger | `http://sim.pollak.store:8500/docs` |
| auth-stub Swagger | `http://sim.pollak.store:8600/docs` |
| MAVLink TCP (red team) | `sim.pollak.store:5790` |
| QGC raw VNC | `sim.pollak.store:5900` |

> 본 환경은 데모용으로 NSG가 모든 IP에서 접근 허용. 발표 끝나면 닫음.

---

## 2. 첫 접속 + UI 한눈에

1. 브라우저로 `http://sim.pollak.store:8080/vnc.html` 진입
2. 우측 상단 **"Connect"** 버튼 클릭
3. 비밀번호 입력란이 뜨면 **그냥 Enter** (현재 미설정)
4. QGroundControl 화면이 나타남 (1440×900)

### UI 영역 설명

```
┌────────────────────────────────────────────────────────────────┐
│ ① 상단 상태바 ② 모드 ③ 위성 ④ Azimuth ⑤ 로고                   │
├────┬───────────────────────────────────────────────┬───────────┤
│⑥ Fly│                                              │ ⑧ 자세      │
│⑥ Plan                                              │ HUD         │
│⑥ Take│              ⑦ 메인 지도                     │ ⑧ 나침반    │
│   off│                                              │            │
│⑥ Ret│                ●  ← 차량                      │            │
│   urn│                                              │ ⑨ 영상     │
│⑥ Act│                                              │ 패널       │
│   ion│                                              │            │
├────┴───────────────────────────────────────────────┴───────────┤
│ ⑩ 하단 HUD: 고도 / 속도 / 스로틀 / 비행시간                       │
└────────────────────────────────────────────────────────────────┘
```

| 번호 | 영역 | 설명 |
|---|---|---|
| ① | 상단 상태 텍스트 | "Disconnected", "Ready To Fly", "Flying", "Armed" 등 |
| ② | 모드 | `FBW A`, `AUTO`, `MANUAL`, `QSTABILIZE`, `RTL` 등 (클릭으로 변경) |
| ③ | 위성 + HDOP | 위성 수 / 정밀도 — 정상 10+/1.0 이하 |
| ④ | Yaw follow | Azimuth/Pitch — 짐벌 가리킴 방향 |
| ⑤ | 로고 | 우상단 ArduPilot/PX4 마크 |
| ⑥ | 좌측 사이드바 | Fly / Plan / Takeoff / Return / Action / Pause 버튼 (상황에 따라 변함) |
| ⑦ | 지도 | 차량 위치 + waypoint + 비행 궤적 |
| ⑧ | 자세 + 나침반 | 우상단 작은 인디케이터 |
| ⑨ | 영상 패널 | (현재 비활성 — EO/IR 스트림 없음) |
| ⑩ | 하단 HUD | 실시간 비행 수치 |

### 사이드바 버튼 종류 (상태별로 다름)

| 상황 | 보이는 버튼 |
|---|---|
| 차량 연결 안 됨 | (없음) |
| 차량 연결, Disarmed | Fly / Plan / Takeoff / Return |
| Armed, 비행 안함 | + Action |
| Flying (AUTO) | + Pause |

---

## 3. 기존 미션으로 비행 (가장 빠른 시연)

이미 만들어진 정찰 미션 `mpd_recon.plan`을 띄우는 절차. **3분 안에 비행 시작 → 미션 완료까지 약 3분**.

### 3a. 미션 파일 로드

1. 좌측 사이드바 **"Plan"** 클릭
2. 우상단 사이드바 **"File"** 아이콘 (폴더+톱니바퀴)
3. **"Storage"** 섹션의 **"Open..."** 클릭
4. 파일 다이얼로그 상단 경로 입력란에 다음 입력 + Enter:
   ```
   /home/qgc/missions/
   ```
5. 디렉토리에 `mpd_recon.plan` 파일 보임. 클릭 → **"Open"**
6. 지도에 waypoint 8개 표시 + 우측 패널에 미션 아이템 리스트

> **경로 직접 입력 안 되면**: 좌측 사이드바에서 `home` → `qgc` → `missions` 폴더로 클릭 진입.

### 3b. 차량으로 업로드

1. 우측 패널 **"Vehicle"** 섹션에서 **"Upload"** 클릭
2. 진행 바 (Mission Upload Progress) 채워지면 완료
3. (선택) `Plan was created for different firmware` 경고가 뜨면 **"Ok"** 클릭 (영향 없음)

### 3c. Fly 화면으로

좌측 사이드바 **"Fly"** 클릭. 지도가 메인으로.

### 3d. 모드를 AUTO로

1. 상단 좌측 모드 텍스트(예: `FBW A`) 클릭
2. 드롭다운에서 **"AUTO"** 선택
3. 모드 표시가 `AUTO`로 바뀜

> AUTO가 메뉴에 없으면 미션 업로드 안 됨. 3b 다시.

### 3e. Arm

1. 좌측 패널 **"Action"** 아이콘 (▶) 클릭
2. **"Arm"** 선택
3. **슬라이드 to confirm** — 슬라이더 끝까지 끌기

### 3f. 비행 시작 — 자동 진행

Arm 후 자동으로 미션 1번부터 실행:

```
step 1: VTOL_TAKEOFF (84)        → 수직 이륙 고도 30 m
step 2: WAYPOINT (16)            → 천이, 80 m, 첫 waypoint
step 3: WAYPOINT (16)            → 두번째 waypoint, 120 m
step 4: DO_SET_ROI_LOCATION (195)→ 표적(37.5410, 127.0310) EO/IR 락온
step 5: LOITER_TIME (19)         → 30초 표적 상공 호버
step 6: DO_SET_ROI_NONE (197)    → ROI 해제
step 7: WAYPOINT (16)            → 이탈 코스
step 8: VTOL_LAND (85)           → 수직 착륙 (홈)
```

좌하단 HUD에 고도 / 속도 / 스로틀 / 배터리 / 비행시간 표시.

---

## 4. 미션 파일이 어디에 저장되는가

### 4.1 컨테이너 내부 경로

QGC가 도는 `uav-gcs-qgc` 컨테이너 안:

```
/home/qgc/                   ← 컨테이너 안 QGC home
└── missions/                ← 미션 파일 디렉토리
    └── mpd_recon.plan       ← 기본 제공 정찰 미션
```

이 디렉토리는 **컨테이너 이미지 빌드 시 박힌 것**. 컨테이너 재시작해도 파일 그대로.

### 4.2 호스트(VM) 경로

QGC 컨테이너의 `/home/qgc/missions`는 호스트 파일시스템과 연결되어 있지 **않음** (bind mount 없음). 즉:
- 컨테이너 안에서 QGC가 새 미션 저장 → 컨테이너 안 임시 보관
- 컨테이너 재기동 시 사라짐 (이미지에 박힌 것만 남음)

### 4.3 영구 저장 (저장소)

미션을 **영구 보관하려면 git 저장소에 박아야** 함:

```
github.com/s1ns3nz0/uav-sim-env
└── gcs-qgc/
    └── missions/
        └── mpd_recon.plan   ← 이미지 빌드 시 /home/qgc/missions/로 복사됨
```

흐름:
```
저장소 gcs-qgc/missions/X.plan
       ↓ docker compose build gcs-qgc
컨테이너 이미지에 박힘
       ↓ docker compose up -d
실행 중 컨테이너 안에서 사용 가능
```

→ **새 미션 만들고 영구 저장하려면 저장소에 commit + push 후 재빌드**. (자세한 절차는 6절)

---

## 5. QGC에서 미션 처음부터 만들기 (GUI)

미니멀 정찰 미션을 새로 만들어 본다. 결과물: takeoff → 1 waypoint → loiter → land.

### 5a. Plan 화면 진입

좌측 사이드바 **"Plan"** 클릭.

### 5b. 새 계획 시작 (기존 것 지우기)

우상단 사이드바 **"File"** → **"Storage"** → **"Clear"** 클릭.
또는 좌측 사이드바 **"Create Plan"** 영역의 **"Blank"** 선택.

### 5c. Home 위치 확인 / 설정

지도 좌하단 + 와 - 버튼으로 줌. 한강대교 부근(37.5326, 127.0246)이 기본 home. 변경 시:
1. 우측 패널 **"Mission Start"** 항목 클릭
2. **"Planned Home Position"** 좌표 입력 (lat, lon, alt)

### 5d. Waypoint 추가

#### 방법 A: 지도 클릭

지도에서 원하는 위치 클릭. 우측 패널에 새 mission item 추가됨 (기본 NAV_WAYPOINT).

#### 방법 B: 좌측 사이드바 카테고리

좌측 사이드바에 미션 아이템 카테고리:

| 아이콘 | 카테고리 | MAV_CMD |
|---|---|---|
| Takeoff | 이륙 | 22 (NAV_TAKEOFF) 또는 84 (NAV_VTOL_TAKEOFF) |
| Waypoint | 일반 항로점 | 16 (NAV_WAYPOINT) |
| ROI | 짐벌 락온 | 195 (DO_SET_ROI_LOCATION) |
| Pattern | 정찰 패턴 (지그재그 등) | 자동 생성 |
| Land | 착륙 | 21 (NAV_LAND) / 85 (NAV_VTOL_LAND) |
| Center | 지도 센터 잡기 | — |

각 카테고리 클릭 → 지도에서 위치 클릭 → 자동 추가.

### 5e. 아이템 편집

지도 또는 우측 리스트에서 아이템 클릭 → 우측에 편집 패널 표시:

- **Altitude (m)** — 고도 (기본 home 기준 상대고도)
- **Hold Time (s)** — loiter 시간 (특정 cmd만)
- **Acceptance Radius (m)** — 도달 인정 반경
- **Yaw Angle** — 도달 시 기수 방향
- **Latitude/Longitude** — 정확한 좌표 (수동 입력)

### 5f. 미니멀 미션 예 (4 step)

```
1. VTOL_TAKEOFF      lat=home, lon=home, alt=30
2. NAV_WAYPOINT      lat=37.5340, lon=127.0260, alt=80
3. NAV_LOITER_TIME   lat=37.5340, lon=127.0260, alt=80, hold=20s
4. NAV_VTOL_LAND     lat=home, lon=home, alt=0
```

만들면 우상단에 `Distance: ~280m`, `Time: ~01:30` 등 통계 표시.

### 5g. 차량으로 업로드 (3b와 동일)

만든 미션을 차량에 보내려면 우측 패널 **Vehicle** 섹션 **Upload**.

---

## 6. 만든 미션을 컨테이너에 영구 저장하기

### 6a. 컨테이너 안에 임시 저장 (재시작 시 사라짐)

1. Plan 화면 → **File** → **Storage** → **"Save As..."**
2. 경로 `/home/qgc/missions/my_mission.plan` 입력
3. 저장 완료

다음 접속 시 `/home/qgc/missions/my_mission.plan` 로드 가능. 단 **컨테이너 재기동 시 사라짐**.

### 6b. 영구 저장 (저장소에 박기)

> **이건 SSH 가능자 (양진수)가 진행해야 함** — 일반 시연용자가 자기 컴퓨터로 끌어내는 절차는 없음 (noVNC만 줌).

영구화 절차:

```bash
# 1. SSH로 VM 접속
ssh azureuser@sim.pollak.store

# 2. 컨테이너 안에서 파일 꺼내기
sudo docker cp uav-gcs-qgc:/home/qgc/missions/my_mission.plan /tmp/

# 3. 호스트의 저장소로 복사
sudo cp /tmp/my_mission.plan /opt/uav-sim-env/gcs-qgc/missions/

# 4. 권한 + git commit
cd /opt/uav-sim-env
sudo git add gcs-qgc/missions/my_mission.plan
sudo git -c user.email="bot@uavsim" -c user.name="uavsim-bot" \
  commit -m "feat(missions): add my_mission.plan"
sudo git push   # 권한 필요

# 5. 이미지 재빌드 (저장소 → 이미지 → 컨테이너로 박음)
sudo docker compose build gcs-qgc
sudo docker compose up -d --force-recreate gcs-qgc
```

이후 누구든 접속하면 `/home/qgc/missions/my_mission.plan` 로 사용 가능.

### 6c. 더 간단한 방법 (양진수 로컬에서)

```bash
# QGC가 컨테이너에 만든 파일을 다운로드 받기 어려우므로
# 차라리 로컬에서 .plan 파일 작성 후 저장소에 추가
vim ~/uav-sim-env/gcs-qgc/missions/my_mission.plan
git add gcs-qgc/missions/my_mission.plan
git commit -m "..."
git push

# VM에 반영
ssh azureuser@sim.pollak.store '
cd /opt/uav-sim-env && sudo git pull
sudo docker compose build gcs-qgc
sudo docker compose up -d --force-recreate gcs-qgc
'
```

---

## 7. 미션 파일 (.plan) 포맷 직접 편집

`.plan`은 QGC가 정의한 JSON 포맷.

### 7a. 최상위 구조

```json
{
    "fileType": "Plan",
    "groundStation": "QGroundControl",
    "version": 1,
    "geoFence": { "circles": [], "polygons": [], "version": 2 },
    "rallyPoints": { "points": [], "version": 2 },
    "mission": {
        "cruiseSpeed": 18,
        "firmwareType": 3,
        "hoverSpeed": 5,
        "vehicleType": 1,
        "version": 2,
        "globalPlanAltitudeMode": 1,
        "plannedHomePosition": [37.5326, 127.0246, 50],
        "items": [ /* ... mission items ... */ ]
    }
}
```

### 7b. mission 필드 의미

| 필드 | 값 | 설명 |
|---|---|---|
| `cruiseSpeed` | 18 | 고정익 순항속도 (m/s) |
| `firmwareType` | 3 | 펌웨어 (3 = ArduPilotMega, 12 = PX4) |
| `hoverSpeed` | 5 | 멀티콥터 호버 속도 (m/s) |
| `vehicleType` | 1 | MAV_TYPE — 1=Fixed Wing (Quadplane 포함), 2=Quadrotor |
| `globalPlanAltitudeMode` | 1 | 1 = 상대고도, 0 = AMSL |
| `plannedHomePosition` | `[lat, lon, alt]` | 가상 home (이륙 기준점) |

### 7c. items 배열 — mission item 하나

각 항목은 `SimpleItem` (단일 명령) 또는 `ComplexItem` (지그재그 등 매크로).

```json
{
    "AMSLAltAboveTerrain": null,
    "Altitude": 30,
    "AltitudeMode": 1,
    "autoContinue": true,
    "command": 84,
    "doJumpId": 1,
    "frame": 3,
    "params": [0, 0, 0, 0, 37.5326, 127.0246, 30],
    "type": "SimpleItem"
}
```

| 필드 | 의미 |
|---|---|
| `Altitude` | 표시용 고도 (m) |
| `AltitudeMode` | 1 = home 상대, 0 = AMSL, 2 = 지형 상대 |
| `command` | MAV_CMD 번호 (참조표 13절) |
| `doJumpId` | 순서 (1부터, 미션 안 내 jump 명령 참조용) |
| `frame` | MAV_FRAME (3 = GLOBAL_RELATIVE_ALT, 2 = MISSION) |
| `params` | `[param1, param2, param3, param4, lat, lon, alt]` — 명령 종속 |
| `type` | `SimpleItem` (단일) 또는 `ComplexItem` (매크로) |
| `autoContinue` | true면 자동 다음 step 진행 |

### 7d. command 별 params 의미 (요약)

| command | 이름 | params[0] | [1] | [2] | [3] | [4,5,6] |
|---|---|---|---|---|---|---|
| 16 | NAV_WAYPOINT | hold sec | accept radius | pass radius | yaw deg | lat/lon/alt |
| 19 | NAV_LOITER_TIME | hold sec | empty | radius | empty | lat/lon/alt |
| 21 | NAV_LAND | abort alt | precision | empty | yaw | lat/lon/alt |
| 22 | NAV_TAKEOFF | min pitch | empty | empty | yaw | lat/lon/alt |
| 84 | NAV_VTOL_TAKEOFF | empty | empty | empty | yaw | lat/lon/alt |
| 85 | NAV_VTOL_LAND | empty | empty | approach alt | yaw | lat/lon/alt |
| 195 | DO_SET_ROI_LOCATION | empty | empty | empty | empty | lat/lon/alt (표적) |
| 197 | DO_SET_ROI_NONE | empty | empty | empty | empty | 0,0,0 |
| 176 | DO_SET_MODE | base mode | custom mode | custom sub | empty | 0,0,0 |
| 400 | COMPONENT_ARM_DISARM | 0=disarm, 1=arm | force | empty | empty | 0,0,0 |

### 7e. 최소 미션 예 — VTOL 이륙 후 즉시 착륙

```json
{
    "fileType": "Plan", "version": 1,
    "geoFence": {"circles":[],"polygons":[],"version":2},
    "rallyPoints": {"points":[],"version":2},
    "mission": {
        "cruiseSpeed": 18, "firmwareType": 3, "hoverSpeed": 5, "vehicleType": 1,
        "version": 2, "globalPlanAltitudeMode": 1,
        "plannedHomePosition": [37.5326, 127.0246, 50],
        "items": [
            { "type":"SimpleItem", "command":84, "frame":3, "doJumpId":1, "autoContinue":true,
              "AMSLAltAboveTerrain":null, "Altitude":20, "AltitudeMode":1,
              "params":[0,0,0,0, 37.5326, 127.0246, 20] },
            { "type":"SimpleItem", "command":85, "frame":3, "doJumpId":2, "autoContinue":true,
              "AMSLAltAboveTerrain":null, "Altitude":0, "AltitudeMode":1,
              "params":[0,0,0,0, 37.5326, 127.0246, 0] }
        ]
    }
}
```

저장: `gcs-qgc/missions/quick_test.plan`.

---

## 8. 새 기체(UAV) 추가하기 — 멀티 UAV 시뮬

현재 시뮬은 **단일 MPD-001** 뿐. SOC 룰을 멀티 UAV로 테스트하거나 스웜 시연 하려면 2번째 SITL 인스턴스 추가 필요.

### 8a. 개념

ArduPilot SITL은 `-I` 옵션으로 인스턴스 번호 부여 → MAVLink 포트가 다르게 열림:

| 인스턴스 (`-I N`) | SITL TCP 포트 |
|---|---|
| 0 | 5760 (현재 MPD-001) |
| 1 | 5770 |
| 2 | 5780 |

각 인스턴스마다 다른 `UAV_ID`로 telemetry-tap 분기.

### 8b. 추가 절차 (양진수)

#### 1. 페르소나 파일 만들기

`av-mpd/persona/kcd200_quadplane.parm` 같은 새 파일. (예: KCD-200급 수송 드론)

```
# KCD-200 페르소나 (200kg 수소연료전지 VTOL)
Q_M_THST_HOVER     0.45
BATT_CAPACITY      60000
GPS_TYPE           1
GPS_AUTO_SWITCH    1
SR0_POSITION       2
ARMING_CHECK       0
```

#### 2. docker-compose.yml에 새 서비스 추가

```yaml
  av-kcd200:
    build:
      context: ./av-mpd
    container_name: uav-av-kcd200
    hostname: av-kcd200
    networks:
      uas-los:
        ipv4_address: 10.50.0.11
    environment:
      VEHICLE: ArduPlane
      FRAME: quadplane
      INSTANCE: "1"                  # ← 핵심: 인스턴스 1
      MAVLINK_OUT_HOST: datalink-los
      MAVLINK_OUT_PORT: "14550"
      HOME_LAT: "37.5400"            # 다른 시작 좌표
      HOME_LON: "127.0300"
      HOME_ALT: "100"
      HOME_HEADING: "180"
      UAV_ID: "KCD-200-001"
      PERSONA_PARAM: "/home/sitl/persona/kcd200_quadplane.parm"
    ports:
      - "5770:5770"
    depends_on:
      - datalink-los
    restart: unless-stopped
```

#### 3. av-mpd/entrypoint.sh 수정 (인스턴스 + persona 동적)

```bash
INSTANCE="${INSTANCE:-0}"
PERSONA_PARAM="${PERSONA_PARAM:-/home/sitl/persona/mpd_quadplane.parm}"

exec sim_vehicle.py -v ArduPlane -f quadplane -I "$INSTANCE" \
    --no-mavproxy --wipe-eeprom \
    --custom-location "$HOME_LAT,$HOME_LON,$HOME_ALT,$HOME_HEADING" \
    --add-param-file "$PERSONA_PARAM"
```

#### 4. mavlink-router.conf — 두번째 SITL TCP 추가

```
[TcpEndpoint av_in]
Address=10.50.0.10
Port=5760

[TcpEndpoint av_in_2]
Address=10.50.0.11
Port=5770            # 인스턴스 1 = 5760 + 10
```

#### 5. telemetry-tap — UAV_ID per-instance 처리

(현재 telemetry-tap은 단일 UAV_ID 환경변수. 멀티 UAV는 MAVLink SystemId로 분리 필요. 별도 작업)

> 이 모든 게 단순히 `docker compose up`으로 가능하지만 **telemetry-tap의 UAV_ID 매핑 로직 수정** 이 핵심. Phase 2 작업.

### 8c. QGC 측에서 멀티 차량 보기

QGC는 같은 MAVLink 채널 위에서 여러 SystemId 차량을 자동 인식. 좌상단에 차량 1, 2 토글 표시. 클릭으로 활성 차량 전환.

---

## 9. 페르소나 파일 커스터마이즈

`av-mpd/persona/mpd_quadplane.parm`은 ArduPilot 파라미터 오버라이드.

### 9a. 파일 포맷

```
# 주석 (해시로 시작)
PARAM_ID    VALUE

# 예시
ARMING_CHECK       0
BATT_CAPACITY      12000
WP_RADIUS          15
```

ArduPilot이 부팅 시 이 파일을 읽고 default 위에 덮어씀.

### 9b. 자주 만지는 파라미터

| 파라미터 | 의미 | MPD 기본 | 추천 범위 |
|---|---|---|---|
| `ARMING_CHECK` | 사전 안전점검 (0=무시) | 0 (SITL용) | 실배치는 1 |
| `BATT_CAPACITY` | 배터리 용량 (mAh) | 12000 | 기체별 |
| `WP_RADIUS` | waypoint 도달 반경 (m) | 15 | 5\~50 |
| `Q_M_THST_HOVER` | 호버 추력 비율 | 0.30 | 0.20\~0.50 |
| `GPS_TYPE` | GPS 종류 (1=일반) | 1 | 1, 2(uBlox), 5(NMEA) |
| `FS_GCS_ENABL` | GCS 손실 failsafe (0=꺼짐, 1=켜짐) | 1 | 보통 1 |
| `FS_LONG_ACTN` | 장기 failsafe 동작 | 1 (RTL) | 0\~3 |
| `MNT1_TYPE` | 짐벌 종류 (1=Servo) | 1 | 1\~6 |
| `SR0_POSITION` | 위치 메시지 출력률 (Hz) | 2 | 1\~10 |

### 9c. 변경 후 반영

```bash
cd ~/uav-sim-env
# 편집
vim av-mpd/persona/mpd_quadplane.parm

# commit + push (영구화)
git add av-mpd/persona/mpd_quadplane.parm
git commit -m "..."
git push

# VM에 반영
ssh azureuser@sim.pollak.store '
cd /opt/uav-sim-env && sudo git pull
sudo docker compose restart av-mpd
'
```

부팅 시 새 파라미터 적용 (1\~2분).

### 9d. 런타임 PARAM_SET (재빌드 없이)

빠른 실험용:
```bash
ssh azureuser@sim.pollak.store '
sudo docker compose exec telemetry-tap python -c "
from pymavlink import mavutil
m = mavutil.mavlink_connection(\"tcp:datalink-los:5790\")
m.wait_heartbeat(timeout=10)
m.mav.param_set_send(m.target_system, m.target_component,
    b\"WP_RADIUS\", 25.0, mavutil.mavlink.MAV_PARAM_TYPE_REAL32)
print(\"OK\")
"
'
```

### 9e. 변경 추적

PARAM_VALUE 메시지 변화 → `UAVConfigAudit_CL` 테이블에 자동 적재. KQL로 조회:
```kql
UAVConfigAudit_CL
| where TimeGenerated > ago(1h)
| where ParamId == "WP_RADIUS"
```

---

## 10. 비행 중 관측 + 백그라운드 인제스트

### 10a. 차량 상태 패널
- 상단 좌측: 모드 + Armed/Disarmed
- 우상단: 자세 인디케이터 (롤/피치)
- 우상단 옆: 나침반
- 하단 중앙: 고도, 속도, 스로틀, 비행시간

### 10b. 메시지 / 경고
- 좌상단 노란 박스 클릭 → STATUSTEXT 메시지 펼침
- `PreArm: ...` / `Mode change to AUTO` 등 표시
- Severity ≥ Warning → `UAVFailsafe_CL` 적재

### 10c. 백그라운드 동작 — 비행 1초마다 SOC에 흐르는 데이터

| MAVLink 메시지 | 적재 테이블 | 컬럼 |
|---|---|---|
| HEARTBEAT | `UAVTelemetry_CL` | SystemStatus, BaseMode, CustomMode |
| GLOBAL_POSITION_INT | `UAVTelemetry_CL` | Lat, Lon, AltMSL_m, Heading_cdeg |
| GPS_RAW_INT | `UAVTelemetry_CL` | FixType, SatellitesVisible, Eph_cm |
| ATTITUDE | `UAVTelemetry_CL` | Roll/Pitch/Yaw_rad |
| VFR_HUD | `UAVTelemetry_CL` | Airspeed, Throttle, ClimbRate |
| EKF_STATUS_REPORT | `UAVTelemetry_CL` | **VelocityVariance, PosHorizVariance** |
| COMMAND_LONG | `UAVTelemetry_CL` + `UAVOperator_CL` | Command, Param1\~4 |
| MISSION_CURRENT/REACHED | `UAVOperator_CL` + `UAVMissionEvent_CL` | Seq, EventName |
| STATUSTEXT (sev≤4) | `UAVTelemetry_CL` + `UAVFailsafe_CL` | Severity, Text |
| PARAM_VALUE | `UAVTelemetry_CL` + `UAVConfigAudit_CL` | ParamId, ParamValue |

비행 끝나면 KQL로 분석 가능.

---

## 11. 시연 시나리오 5종

### A. 정상 비행 (정찰 임무)
3절 그대로. 한 사이클 ~3분.

### B. 펌웨어 변조 시연
별도 터미널에서:
```bash
HOST=sim.pollak.store
curl -X POST http://$HOST:8000/preflight/check \
  -H "Content-Type: application/json" \
  -d '{
    "uav_id":"MPD-001",
    "image_hash":"sha256:DEADBEEF...",
    "sbom_components":["unsigned/malicious-x"],
    "operator":"attacker",
    "serial":"MPD-AC-0001"
  }'
```
→ `Passed: false`. **UAVPgse_CL**에 적재.

### C. 임무계획 2-person 위반
```bash
HOST=sim.pollak.store
PLAN=$(curl -s -X POST http://$HOST:8100/plans \
  -H "Content-Type: application/json" \
  -d '{"uav_id":"MPD-001","planner":"lt.kim","callsign":"X","waypoints":[{"seq":0,"lat":37.5326,"lon":127.0246,"alt_m":30,"action":"navigate"}],"roe":"recon-only","payload_config":"EO_IR"}' \
  | jq -r .plan_id)

curl -X POST http://$HOST:8100/plans/$PLAN/approve \
  -H "Content-Type: application/json" \
  -d '{"approver":"lt.kim","comment":"self-approve"}'
```
→ 403 + **UAVMissionPlan_CL** 위반 이벤트.

### D. 사이버 태세 상향
```bash
curl -X POST http://$HOST:8300/posture \
  -H "Content-Type: application/json" \
  -d '{"level":"CT-1","changed_by":"col.lee","reason":"active-jamming","source":"사이버사"}'
```

### E. MAVLink 인젝션 (A4)
별도 터미널에서 MAVProxy 또는 pymavlink로 직접:
```bash
pip install pymavlink
python -c "
from pymavlink import mavutil
m = mavutil.mavlink_connection('tcp:sim.pollak.store:5790')
m.wait_heartbeat(timeout=10)
# 강제 RTL 명령 인젝션
m.mav.command_long_send(
    m.target_system, m.target_component,
    mavutil.mavlink.MAV_CMD_DO_SET_MODE, 0,
    1, 11, 0, 0, 0, 0, 0   # custom_mode 11 = RTL
)
print('injected MODE RTL')
"
```
→ QGC 화면에서 차량이 갑자기 RTL 모드 전환됨 + `UAVOperator_CL`에 `command_176` 적재.

---

## 12. 트러블슈팅 매트릭스

### 화면이 검은색 / 늦게 뜸
- 브라우저 새로고침 (Cmd+R 또는 F5)
- QGC 컨테이너 부팅까지 30초~1분 걸림
- 30초 후 새로고침

### "Disconnected"가 안 풀림
- av-mpd SITL 미부팅 가능성. 1\~2분 더 기다림
- SSH 가능자에게 `docker compose logs av-mpd | tail -10` 요청
- 마지막 라인에 `EKF3 IMU0 is using GPS` 또는 `RiTW: Starting ArduPlane` 보여야 정상

### Arm 실패 ("In landing sequence", "missing takeoff waypoint" 등)
- 직전 미션이 끝나지 않은 상태 OR 미션 인덱스가 land에 머묾
- SSH 가능자에게 av-mpd 재시작 요청:
  ```bash
  ssh azureuser@sim.pollak.store 'sudo docker compose -f /opt/uav-sim-env/docker-compose.yml restart av-mpd'
  ```
- 부팅 후 bootstrap.py가 `MISSION_CURRENT=0` + `ARMING_CHECK=0` 으로 리셋
- 1~2분 후 다시 미션 업로드 + AUTO + Arm

### AUTO 모드 안 보임
- 미션 차량 업로드 안 됨. 3b 다시.
- vehicleType이 1 (Fixed Wing)인지 확인 (`.plan` 파일)

### 마우스/키보드 안 먹음
- 브라우저 탭 포커스 확인
- noVNC 좌측 사이드바 펼침 → 입력 옵션 확인
- 다른 브라우저 시도 (Chrome 권장)

### "Plan was created for different firmware" 경고
- `vehicleType=22` (VTOL_QUADROTOR) 와 ArduPlane Quadplane 펌웨어 차이로 발생
- "Ok" 클릭 + 그대로 진행. 동작에 영향 없음
- 영구 해결: `.plan` 파일의 `vehicleType` 을 `1` 로 변경

### 미션 업로드 후 차량이 안 움직임
- AUTO 모드 진입 확인
- Arm 성공 여부 확인 (상단 상태 "Armed" 표시)
- 좌상단 메시지 패널에 PreArm 에러 확인

### `Plan Upload` 다이얼로그가 화면 밖에 떠 있음
- 브라우저 zoom 100% 확인
- 또는 전체화면 F11

### QGC가 응답 없음 / 멈춤
- noVNC 우측 사이드바의 "Send Ctrl+Alt+Del" 등 시도 안 됨
- 결국 SSH 가능자에게 `docker compose restart gcs-qgc` 요청

---

## 13. 단축키 + 참조표

### noVNC 단축키
| 키 | 동작 |
|---|---|
| F11 (브라우저) | 전체화면 |
| 좌측 사이드바 화살표 | noVNC 옵션 패널 펼침 |
| Drag handle | 클립보드 텍스트 전달 |

### QGC 단축키 (focus가 QGC에 있을 때)
- `Ctrl+M` 메시지 토글
- `Ctrl+P` Plan 화면
- `Ctrl+F` Fly 화면
- 마우스 휠 — 지도 줌
- 마우스 우클릭 + 드래그 — 지도 패닝

### MAV_CMD 자주 쓰는 번호

| 번호 | 이름 | 용도 |
|---|---|---|
| 16 | NAV_WAYPOINT | 일반 항로점 |
| 17 | NAV_LOITER_UNLIM | 무한 호버 |
| 18 | NAV_LOITER_TURNS | 지정 회수 선회 |
| 19 | NAV_LOITER_TIME | 지정 시간 호버 |
| 20 | NAV_RETURN_TO_LAUNCH | RTL |
| 21 | NAV_LAND | 일반 착륙 |
| 22 | NAV_TAKEOFF | 일반 이륙 (활주로) |
| 84 | NAV_VTOL_TAKEOFF | VTOL 이륙 |
| 85 | NAV_VTOL_LAND | VTOL 착륙 |
| 176 | DO_SET_MODE | 모드 변경 |
| 179 | DO_SET_HOME | home 위치 설정 |
| 195 | DO_SET_ROI_LOCATION | 짐벌 좌표 락온 |
| 197 | DO_SET_ROI_NONE | 짐벌 ROI 해제 |
| 211 | DO_TRIGGER_CONTROL | 카메라 트리거 |
| 400 | COMPONENT_ARM_DISARM | Arm/Disarm |

### ArduPlane CustomMode 번호

| 번호 | 모드 | 의미 |
|---|---|---|
| 0 | MANUAL | 수동 |
| 1 | CIRCLE | 원형 비행 |
| 2 | STABILIZE | 안정화 |
| 5 | FBWA | Fly-By-Wire A (기본 안전 자율) |
| 6 | FBWB | Fly-By-Wire B (고도 유지) |
| 7 | CRUISE | 순항 |
| 8 | AUTOTUNE | 자동 튜닝 |
| 10 | AUTO | 미션 자동 실행 |
| 11 | RTL | Return to Launch |
| 12 | LOITER | 현 위치 호버 |
| 14 | LAND | 착륙 |
| 15 | GUIDED | 외부 명령 대기 |
| 17 | QSTABILIZE | Quadplane 안정 |
| 18 | QHOVER | Quadplane 호버 |
| 19 | QLOITER | Quadplane 위치 유지 |
| 20 | QLAND | Quadplane 착륙 |
| 21 | QRTL | Quadplane RTL |
| 22 | QAUTOTUNE | Quadplane 자동튜닝 |
| 23 | QACRO | Quadplane 아크로 |

### ArduPilot Quadplane 프레임 클래스
사용 중: `quadplane` (틸트로터 4발 + 고정익). 다른 옵션: `quadtailsitter`, `tilttri`.

---

## 14. 운영 메타 + 종료

### 운영 메타
- QGC 버전: 4.4.4 (linux/amd64 AppImage, squashfs 직접 추출)
- 컨테이너: `uav-gcs-qgc` (supervisord: Xvfb + fluxbox + x11vnc + noVNC + QGC)
- 화면 해상도: 1440×900
- 사용 모델 (av-mpd persona): ArduPlane Quadplane, MPD persona
- 홈 좌표: 37.5326, 127.0246, 50m (서울 한강대교 부근)
- 시연 미션 파일: `/home/qgc/missions/mpd_recon.plan` (저장소 `gcs-qgc/missions/`)
- 페르소나 파일: `/home/sitl/persona/mpd_quadplane.parm` (저장소 `av-mpd/persona/`)

### 종료
특별한 종료 절차 없음. 브라우저 탭 닫으면 끝.
- 시뮬은 계속 돌아감 (다른 사람이 동시에 접속 가능)
- 미션 완료 후 차량은 홈으로 복귀, Disarmed 됨

전체 환경을 끄려면 (관리자):
```bash
az vm deallocate -g dah-sim-rg -n uavsim-vm   # 비용 정지
# 다시 켜기:
az vm start -g dah-sim-rg -n uavsim-vm
```

---

## 15. 관련 문서

- 컴포넌트 상세: [`docs/components.md`](./components.md)
- Sentinel 테이블 스키마: [`docs/sentinel-schemas.md`](./sentinel-schemas.md)
- 본 문서 (이 가이드): `docs/qgc-novnc-guide.md`

소스 코드:
- 미션 파일들: `gcs-qgc/missions/*.plan`
- 페르소나 파일: `av-mpd/persona/*.parm`
- av-mpd Dockerfile + entrypoint: `av-mpd/`
- QGC 컨테이너: `gcs-qgc/Dockerfile`, `supervisord.conf`
