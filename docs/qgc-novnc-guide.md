# QGroundControl (noVNC) 접속 가이드

브라우저만으로 클라우드 UAV 시뮬레이션의 GCS(QGroundControl)에 접속해서 미션을 띄우는 방법.

> **대상**: 팀원 누구나 (Mac/Windows/Linux/모바일도 가능)
> **필요한 것**: 모던 브라우저(Chrome/Firefox/Edge/Safari)
> **로컬에 QGC 설치 불필요** — 컨테이너 안에서 Xvfb + noVNC로 띄움

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

> 본 환경은 데모용으로 NSG가 모든 IP에서 접근 허용. 발표 끝나면 닫음.

---

## 2. 첫 접속

1. 브라우저로 `http://sim.pollak.store:8080/vnc.html` 진입
2. 우측 상단 **"Connect"** 버튼 클릭
3. 비밀번호 입력란이 뜨면 **그냥 Enter** (현재 미설정)
4. QGroundControl 화면이 나타남

```
┌─────────────────────────────────────────────────────────────┐
│   QGroundControl                                            │
├────┬────────────────────────────────────────────────────────┤
│Fly │                                                        │
│Plan│                  [지도 — 서울 한강 일대]                  │
│    │                                                        │
│Take│                                                        │
│off │                                                        │
│    │                                                        │
│Ret │                  ●  ← 차량 (MPD-001)                    │
│urn │                                                        │
└────┴────────────────────────────────────────────────────────┘
```

좌상단 상태 표시:
- **"Ready To Fly"** 또는 **"Disconnected"** — 차량 연결 상태
- 모드 (예: `FBW A`, `AUTO`)
- 위성 수 + HDOP
- Yaw / Pitch / Azimuth

---

## 3. 미션 실행 절차

### 3a. 미션 파일 로드

1. 좌측 사이드바 **"Plan"** 클릭
2. 우상단 사이드바 **"File"** 아이콘
3. **"Storage" → "Open..."** 클릭
4. 파일 다이얼로그에서 경로 직접 입력:
   ```
   /home/qgc/missions/mpd_recon.plan
   ```
5. 미션 waypoint가 지도에 표시됨 (VTOL 이륙 → 정찰 경로 → ROI 락온 → 착륙)

### 3b. 차량으로 업로드

1. 우측 패널 **"Vehicle"** 섹션에서 **"Upload"** 클릭
2. 진행 바 채워지면 완료
3. (선택) `Plan was created for different firmware` 경고 뜨면 **"Ok"** 클릭하고 진행 — 영향 없음

### 3c. Fly 화면으로

1. 좌측 사이드바 **"Fly"** 클릭

### 3d. 모드 변경 (AUTO)

1. 상단 좌측 모드 텍스트 (예: `FBW A`) 클릭
2. 드롭다운에서 **"AUTO"** 선택
3. 모드가 `AUTO`로 표시되면 완료

> AUTO 모드는 미션이 차량에 올라가 있어야 메뉴에 보임. 안 보이면 3b 다시.

### 3e. Arm

1. 좌측 패널 **"Action"** 아이콘 (▶) 클릭
2. **"Arm"** 선택 → 슬라이드 → 확인

### 3f. 비행 시작

Arm 후 자동으로 미션 실행. 차량이:

```
1. VTOL 수직 이륙 (고도 30m)
2. 천이 모드 진입 (멀티콥터 → 고정익)
3. waypoint 통과
4. EO/IR 짐벌 표적 락온 (DO_SET_ROI_LOCATION)
5. 30초 호버 관측
6. ROI 해제
7. 이탈 경로
8. VTOL 착륙 (홈 위치)
```

좌하단 HUD에 고도 / 속도 / 스로틀 / 배터리 표시.

---

## 4. 비행 중 관측

### 차량 상태 패널
- 상단 좌측: 모드 + Armed/Disarmed
- 우상단: 자세 인디케이터 (롤/피치)
- 우상단 옆: 나침반
- 하단 중앙: 고도, 속도, 스로틀, 비행시간

### 메시지 / 경고
- 좌상단 노란 박스 클릭 → STATUSTEXT 메시지 펼침
- `PreArm: ...` / `Mode change to AUTO` 등 표시
- Severity ≥ Warning 이벤트는 동시에 **UAVFailsafe_CL** 에도 적재됨

### 백그라운드 동작
브라우저 화면 외에 자동으로 일어나는 일:
- **UAVTelemetry_CL** ← MAVLink 메시지 전부 적재
- **UAVOperator_CL** ← 모드 변경/명령 적재
- **UAVMissionEvent_CL** ← takeoff/waypoint/land 라이프사이클
- **UAVDatalink_CL** ← 링크 통계 30초마다

비행 끝나면 위 테이블에서 KQL로 분석 가능.

---

## 5. 시연 시나리오

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

---

## 6. 트러블슈팅

### 화면이 검은색 / 늦게 뜸
- 브라우저 새로고침 (Cmd+R 또는 F5)
- QGC 컨테이너 부팅까지 30초~1분 걸림
- 30초 후 새로고침

### "Disconnected"가 안 풀림
- av-mpd SITL 미부팅 가능성. 1\~2분 더 기다림
- 그래도 안 되면 SSH 가능자에게 `docker compose logs av-mpd` 요청

### Arm 실패 ("In landing sequence" 등)
- 직전 미션이 끝나지 않은 상태
- SSH 가능자에게 av-mpd 재시작 요청:
  ```bash
  docker compose restart av-mpd
  ```
- 부팅 후 bootstrap.py가 `MISSION_CURRENT=0` 으로 리셋

### AUTO 모드 안 보임
- 미션 차량 업로드 안 됨. 3b 다시.

### 마우스/키보드 안 먹음
- 브라우저 탭 포커스 확인
- noVNC 좌측 사이드바 펼침 → 입력 옵션 확인
- 다른 브라우저 시도 (Chrome 권장)

---

## 7. 운영 메타

- QGC 버전: 4.4.4 (linux/amd64 AppImage, squashfs 직접 추출)
- 컨테이너: `uav-gcs-qgc` (supervisord: Xvfb + fluxbox + x11vnc + noVNC + QGC)
- 화면 해상도: 1440×900
- 사용 모델 (av-mpd persona): ArduPlane Quadplane, MPD persona
- 홈 좌표: 37.5326, 127.0246, 50m (서울 한강대교 부근)
- 시연 미션 파일: `/home/qgc/missions/mpd_recon.plan` (저장소 `gcs-qgc/missions/`)

---

## 8. 종료

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

## 부록 — 알아두면 좋은 단축키 (noVNC)

| 키 | 동작 |
|---|---|
| F11 (브라우저) | 전체화면 |
| 좌측 사이드바 화살표 | noVNC 옵션 패널 펼침 |
| Drag handle | 클립보드 텍스트 전달 |

QGC 자체 단축키 (focus가 QGC에 있을 때):
- `Ctrl+M` 메시지 토글
- `Ctrl+P` Plan 화면
- `Ctrl+F` Fly 화면
