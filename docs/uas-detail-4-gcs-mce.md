# UAS 상세 (4) — GCS / MCE (Ground Control Station / Mission Control Element)

> **성격**: 소개·학습 문서. 실제 GCS가 무엇인지 → 그 역할을 `uav-sim-env`에서 어떤 오픈소스로 구현했는지 → 거기서 발생하는 애플리케이션 로그가 무엇인지를 정리한다.
> **대상**: KUS-FS급 지상 통제소 — 다중 AV(2~4대 편대) 임무계획·조종·영상/SAR 분석.
> **레포 참조**: `gcs-qgc/{Dockerfile,supervisord.conf,entrypoint.sh,missions/*.plan}`, `auth-stub/`, `mps-stub/`, `telemetry-tap/tap.py`, `docs/sentinel-schemas.md`
> **참고**: MAVLink → NDJSON·테이블 가공 메커니즘은 `docs/uas-mapping-summary.md`의 telemetry-tap 절.

---

## 0. GCS / MCE란

GCS(Ground Control Station, 지상통제소)는 **사람이 무인기를 운용하는 콘솔**이다. 임무를 계획하고, 비행을 통제하고, 들어온 영상/SAR을 분석한다. MCE(Mission Control Element, 임무통제요소)는 그 중 **임무 단위 통제**를 맡는 구성으로, 큰 체계에서는 분리되지만 본 환경에선 GCS에 흡수해 함께 다룬다.

```
운영자 ──▶ [GCS/MCE]  ──임무계획·조종 명령(MAVLink 상향)──▶ AV
              │       ◀──텔레메트리·영상/SAR(하향)──────────
              └─ 영상/SAR 분석, 운영자 인증/세션
```

---

## 1. 실제 GCS의 구성 요소

| 구분 | 실제 요소 | 하는 일 |
|---|---|---|
| HMI/디스플레이 | 지도·계기·영상 화면 | 상황 인지 |
| 조종 인터페이스 | 모드 변경·Arm·이착륙·웨이포인트 | 비행 통제 |
| 임무계획 도구 | 항로·ROI·고도 계획, 승인 절차 | 임무 생성·승인·릴리즈 |
| 영상/SAR 분석 | EO/IR·SAR 영상 판독 | 표적 식별 |
| 운영자 인증/세션 | 로그인·권한·2인 통제 | 누가 무엇을 했나 |
| 통신 인터페이스 | MAVLink 송수신 | AV와 명령·텔레메트리 교환 |
| 편대 통제 | 다중 AV 동시 운용 | 2~4대 편대 |

> 국군 표준 GCS(KGCS)는 비공개라, 기능 동등한 **MAVLink 표준 GCS(QGroundControl)** 로 구현한다.

---

## 2. 오픈소스 구현 — QGroundControl (headless)

GCS는 **QGroundControl(QGC)** 을 헤드리스로 띄운 `gcs-qgc` 컨테이너다. 브라우저만으로 조종사 콘솔에 접속하게 한다.

### 2.1 구성 스택 (`supervisord.conf` 순서)
| program | 오픈소스 | 역할 |
|---|---|---|
| `xvfb` | **Xvfb** | 가상 X 디스플레이(`:0`, 1440x900) |
| `fluxbox` | **fluxbox** | 최소 윈도우 매니저 |
| `x11vnc` | **x11vnc** | X 화면을 VNC(`:5900`)로 노출 |
| `novnc` | **websockify + noVNC** | VNC를 웹(`:8080`)으로 변환 |
| `qgc` | **QGroundControl** AppRun | 실제 조종 콘솔 |

`supervisord`가 위 5개를 한 컨테이너에서 우선순위대로 띄운다(`entrypoint.sh` → `supervisord`).

### 2.2 동작
- 접속: 브라우저 `http://localhost:8080/vnc.html` → noVNC → 데스크탑(QGC 화면).
- 차량 인식: QGC가 **UDP autoconnect**(14550/14551)로 mavlink-router에서 차량을 자동 발견.
- 운영: 임무 업로드(`missions/*.plan`)·모드 변경·Arm·이착륙 등 운영자 액션이 **MAVLink로 AV에 전달**된다.
- 임무 파일: `missions/muav_recon.plan`(활주로 이륙 → 종심 순항 → ROI 정찰 → 복귀·착륙). MAVLink 명령(`84` VTOL/이륙, `21/22` 착륙/이륙, `176` 모드, `195` set_roi 등)으로 구성.
- 편대: 다중 AV가 autoconnect로 함께 인식되어 한 콘솔에서 통제.

### 2.3 GCS의 "주변 기능"은 별도 stub
QGC는 조종·표시를 담당하지만, **임무계획 승인 절차**와 **운영자 인증**은 실제 체계에서 별도 시스템이다. 본 환경도 이를 분리한다:
- **임무계획 워크플로우(2인 통제)** → `mps-stub`(FastAPI)
- **운영자 로그인/세션** → `auth-stub`(FastAPI)

---

## 3. 발생하는 애플리케이션 로그

GCS의 로그는 **세 출처**다 — (A) 조종 액션(MAVLink → telemetry-tap), (B) 운영자 인증(auth-stub), (C) 임무계획 승인(mps-stub).

### (A) 조종 액션 — MAVLink 경유 (telemetry-tap 가공)
운영자가 QGC에서 누른 명령은 MAVLink로 나가고, telemetry-tap이 가공한다.

| 무엇 | 테이블 | 핵심 컬럼 |
|---|---|---|
| 운영자 명령(Arm·모드·이착륙·ROI) | **`UAVOperator_CL`** | `ActionName`, `SourceSystemId`(255=GCS), `Command`, `Param1~4` |
| 미션 라이프사이클(takeoff/waypoint/land/mode) | **`UAVMissionEvent_CL`** | `EventName`, `Seq`, `CustomModeBefore/After` |

> `SourceSystemId`가 핵심: 정상 명령은 GCS(255)에서 온다. **GCS가 아닌 출처(예: 외부 인젝션)** 면 비정상(→ A4).

### (B) 운영자 인증 — auth-stub (`UAVOpAudit_CL`)
- 로그인/로그아웃/토큰검증 감사. 컬럼: `EventType`(`login_success/failure`, `token_validated`…), `Operator`, `ClientIp`, `UserAgent`(`qgc-desktop` 등).
- **인사이드 위협·세션 도용** 탐지 입력.

### (C) 임무계획 승인 — mps-stub (`UAVMissionPlan_CL`)
- 임무계획 생성→승인→릴리즈 + **2인 통제(계획자≠승인자)** 강제. 컬럼: `EventType`(`plan_created/approved/rejected/released`), `Planner`, `PlanId`, `UAVId`.
- OSCAL 증거로 가장 길게 보존.

### 3.1 어떻게 시나리오로 연결되나
- **세션 도용/인사이드 위협**: `UAVOpAudit_CL`에서 같은 `SessionId`가 다른 `ClientIp`에서 사용 / 1분 내 다수 `login_failure` → 계정 도용·brute force.
- **2인 통제 위반**: `UAVMissionPlan_CL`의 `plan_approve_rejected` + `FailReason=planner_equals_approver`.
- **비인가 조종 명령**: `UAVOperator_CL`의 `SourceSystemId != 255`(GCS 아님)인 Arm/모드 변경 → 외부 인젝션(A4) 의심.
- **편대 일괄 이상**: 다수 `UAVId`가 동시에 같은 명령 수신/항로 이탈 → 편대 단위 이상행위.

---

## 4. 요약

GCS/MCE는 **QGroundControl을 헤드리스(Xvfb+noVNC)로 띄운 `gcs-qgc`** 로 구현되어 브라우저만으로 조종 콘솔에 접속한다(KGCS 비공개 → QGC 대체). 조종 액션은 MAVLink로 나가 telemetry-tap이 `UAVOperator_CL`·`UAVMissionEvent_CL`로 가공하고, GCS 주변 기능인 **운영자 인증은 `auth-stub`(`UAVOpAudit_CL`)**, **임무계획 2인 통제는 `mps-stub`(`UAVMissionPlan_CL`)** 가 별도로 기록한다. 핵심 위협면은 **세션 도용·2인 통제 위반·비인가 조종 명령(A4)** 이다.

다음 상세 문서: (5) PGSE.
