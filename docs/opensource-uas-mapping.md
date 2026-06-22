# UAS 5+1 구성요소의 오픈소스 구현

> **성격**: 소개·학습 문서. UAS(무인항공기 체계)의 각 구성요소가 실제로 무엇을 하는지, 그리고 `uav-sim-env`에서 **어떤 오픈소스로 어떻게 구현했는지**를 설명한다.
> **함께 보면 좋은 문서**: `docs/muav-background.md`(UAS 분류·KUS-FS 배경), `docs/components.md`(컨테이너별 상세).

---

## 0. UAS 5+1 구성요소란

무인기는 비행체 하나로 굴러가지 않는다. 미 육군 교범 FMI 3-04.155는 UAS를 **5대 구성요소**의 집합으로 정의하고, SATCOM을 쓰는 중고도급에는 여기에 **+1(위성·위성지상국)** 이 더해진다.

```
 [AV] ──RF──▶ [Data Link] ──▶ [GDT] ──▶ [GCS/MCE]
 비행체        LOS / BLOS       지상단말     통제소
   └ 페이로드                                  ▲
                                  [PGSE] ──────┘  발사·정비·회수
       +1 ┌ 위성 (ANASIS-II)
          └ 위성지상국 (Teleport)   ← BLOS(SATCOM) 경로
```

이 문서는 위 6칸을 차례로 따라가며 "**실제 역할 → 오픈소스 → 동작 방식**"을 정리한다.

---

## 1. 요소 ↔ 오픈소스 한눈에

| 5+1 요소 | 실제 역할 | 오픈소스 | 컨테이너 |
|---|---|---|---|
| **AV** | 비행체 + 페이로드(EO/IR·SAR) + GPS/INS/IFF | **ArduPilot SITL** + **Gazebo Garden** | `av-muav` |
| **Data Link** | LOS(C-band) + BLOS(SATCOM) 데이터 링크 | **mavlink-router** + **tc netem** (LOS) / **OpenSAND** (BLOS) | `datalink-los`, `datalink-satcom` |
| **GDT** | 지상 RF 안테나(LOS 종단) | mavlink-router UDP 라우팅 | `datalink-los` 통합 |
| **GCS/MCE** | 임무계획·조종·영상/SAR 분석 | **QGroundControl** + **noVNC** 스택 | `gcs-qgc` |
| **PGSE** | 발사·정비·회수·지상전원 | **FastAPI/uvicorn** | `pgse-stub` |
| **+1 위성/지상국** | Ku/Ka GEO 트랜스폰더 + 위성지상국 | **OpenSAND** (SAT·GW 엔티티) | `datalink-satcom` |
| (페이로드: SAR) | 합성개구레이더 영상 | **FastAPI** + 합성 SAR 이미지 생성 | `sar-stub` |

관측·보조 계층(`telemetry-tap`=pymavlink, `datalink-stats`, `service-audit`, `mps/c4i/cyber-posture/weapon/ti/auth-stub`=FastAPI)은 SOC 가시성을 위한 것으로, 자세한 내용은 `docs/components.md` 참조.

---

## 2. 요소별 구현

### 2.1 AV (Air Vehicle) — ArduPilot SITL + Gazebo Garden
- **실제 역할**: 자율비행·항법(GPS/INS), EO/IR·SAR 페이로드 탑재, IFF.
- **오픈소스**: **ArduPilot SITL**(Software-In-The-Loop)이 실기체용 비행 펌웨어(`ArduPlane`)를 PC에서 그대로 빌드·실행한다. **Gazebo Garden**이 물리·3D 시각화를 담당.
- **동작**: SITL이 가상 IMU/GPS/기압계/모터 신호를 생성하고 TCP 5760에 MAVLink 서버를 연다. persona 파라미터(`*.parm`)로 기체 특성(고정익 MALE·고고도·장기체공)을 설정하고, `-I {INSTANCE}`로 편대(2~4대)를 띄운다.
- **포인트**: 펌웨어 코드가 실기체와 같으므로 여기서 잡힌 항법·펌웨어 취약점이 곧 실기체 취약점이다.

### 2.2 Data Link — mavlink-router + tc netem (LOS) / OpenSAND (BLOS)
무인기 데이터 링크는 두 경로다.

**LOS(가시선, C-band)**
- **오픈소스**: **mavlink-router** — SITL ↔ GCS ↔ 관측탭 ↔ 외부 접근 포트 사이의 MAVLink 패킷을 라우팅. **tc netem** — 지연·지터·패킷손실을 인위적으로 주입해 실제 RF 링크의 불완전성을 모사.
- **동작**: SITL(TCP 5760)에 클라이언트로 접속 → GCS(UDP 14550)·관측탭(UDP 14552)으로 송출.

**BLOS(비가시선, SATCOM) — OpenSAND**
- **오픈소스**: **OpenSAND** — DVB-S2/RCS2 위성 통신을 물리·링크 계층까지 에뮬레이션하는 오픈소스 SATCOM 에뮬레이터. 세 엔티티로 위성 경로를 구성한다.
  - **ST (Satellite Terminal)** — AV 측 위성 단말.
  - **SAT** — 투명(transparent) 트랜스폰더. GEO 지연(왕복 ~600ms)·대역·열화를 산출.
  - **GW (Gateway)** — 위성지상국(Teleport). →`+1` 요소.
- **동작**: AV(ST)→SAT→GW(Teleport)→GCS 경로로 MAVLink·영상 트래픽을 위성 링크 위에 터널링한다. S3(SATCOM 무결성) 탐지에 필요한 **세션ID·시퀀스·서명상태** 메타는 별도 태깅 계층에서 부여해 NDJSON으로 떨군다.

### 2.3 GDT (Ground Data Terminal) — datalink-los 통합
- **실제 역할**: 지상의 C-band RF 안테나, LOS 신호의 지상 종단.
- **오픈소스**: 별도 컨테이너 없이 **mavlink-router**의 UDP 라우팅이 지상 단말 역할을 흡수한다.
- **포인트**: 물리 안테나가 아니라 "지상 종단에서의 패킷 흐름"이 관심사이므로 라우팅 모사로 충분하다.

### 2.4 GCS / MCE (Ground Control Station) — QGroundControl + noVNC
- **실제 역할**: 임무계획·조종·영상/SAR 분석. KUS-FS급에서는 다중 AV(편대) 통제.
- **오픈소스**: **QGroundControl**(MAVLink 표준 GCS) AppImage를 헤드리스로 띄운다 — **Xvfb**(가상 디스플레이) + **fluxbox**(WM) + **x11vnc** + **websockify/noVNC**(웹 접속) + **supervisord**(통합 실행).
- **동작**: UDP 14550 autoconnect로 차량을 인식하고, 브라우저(noVNC)로 조종사 콘솔에 접속한다. 임무 업로드·모드 변경·Arm 등 운영자 액션이 MAVLink로 차량에 전달된다.
- **포인트**: 국군 표준 GCS(KGCS)는 비공개라 MAVLink 표준 GCS인 QGC로 기능을 동등 구현한다.

### 2.5 PGSE (Payload & Ground Support Equipment) — FastAPI stub
- **실제 역할**: 발사 카타펄트·정비공구·회수 네트·지상전원 등 지상 지원 장비.
- **오픈소스**: **FastAPI/uvicorn**로 장비의 **디지털 결정 표면**을 REST API로 모사 (`/armory/firmware`, `/preflight/check`, `/launch/authorize`, `/maintenance/*`).
- **포인트**: 물리 장비가 아니라 "발사 승인·펌웨어 검증 절차의 무결성"이 관심사이므로 결정 로직만 구현한다.

### 2.6 +1 — 위성(ANASIS-II) + 위성지상국(Teleport) — OpenSAND
- **실제 역할**: ANASIS-II(GEO 36,000km, Ku/Ka, 군 전용) 트랜스폰더와, 위성↔지상을 잇는 위성지상국.
- **오픈소스**: **OpenSAND의 SAT(트랜스폰더)·GW(게이트웨이)** 엔티티가 이 둘을 담당한다. DVB-S2/RCS2 표준 물리계층으로 지연·대역·열화를 사실적으로 산출한다.
- **동작**: 2.2의 BLOS 경로와 동일한 구성요소 — `datalink-satcom` 컨테이너 안에서 OpenSAND `*.conf`로 SAT/GW를 띄운다. 위성 링크 통계와 무결성 메타가 `UAVSatcomLink_CL`(link_id, session_id, seq, integrity_status, rtt_ms, jam_indicator…)로 적재된다.
- **포인트**: ANASIS 고유 프로토콜(키 협상·빔 전환)은 비공개이므로 DVB-S2/RCS2 표준 + 세션/시퀀스/서명 태깅으로 대체한다.

### 2.7 페이로드: SAR — sar-stub (FastAPI + 합성 이미지)
- **실제 역할**: 합성개구레이더(SAR) — 구름·야간을 투시해 지형/표적 영상을 수집.
- **오픈소스**: **FastAPI**가 SAR 프레임 메타데이터(frame_id, target_lat/lon, resolution, sensor_mode…)를 생성하고, **합성 SAR 패치 이미지(더미 바이너리)** 도 함께 만든다.
- **동작**: 주기적으로 SAR 프레임 이벤트 + 이미지를 떨궈 `UAVSarPayload_CL`에 적재한다. 더미 이미지를 포함해 영상 유출·변조·표적 조작 시나리오를 실제 바이너리 흐름으로 다룰 수 있다.

### 2.8 C4I 핸드오프 — c4i-stub에 흡수
- **실제 역할**: 공군이 운용하는 KUS-FS의 영상/표적이 육군(지작사) 제대로 전달되는 지점.
- **오픈소스**: 별도 컨테이너 없이 기존 **`c4i-stub`(FastAPI, ATCIS/MIMS 모사)** 에 핸드오프 이벤트를 추가한다(출처=공군 자산, 소비=육군 제대).
- **포인트**: 조직 간 데이터 전달의 무결성·인가가 관심사이므로, 운용 그림(Operational Picture)을 다루는 c4i-stub에 자연스럽게 통합된다.

---

## 3. 참고 자료 (Sources)

- `docs/muav-background.md` — UAS 분류, 5+1 정의, KUS-FS 배경
- `docs/components.md` — 컨테이너별 오픈소스 상세
- [OpenSAND — 오픈소스 SATCOM(DVB-S2/RCS2) 에뮬레이터](https://www.opensand.org/overview.html)
- [ArduPilot SITL 공식 문서](https://ardupilot.org/dev/docs/sitl-simulator-software-in-the-loop.html)
- [QGroundControl](http://qgroundcontrol.com/)
- [MAVLink common dialect](https://mavlink.io/en/messages/common.html)
