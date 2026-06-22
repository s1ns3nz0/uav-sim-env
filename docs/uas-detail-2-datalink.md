# UAS 상세 (2) — Data Link

> **성격**: 소개·학습 문서. 실제 데이터 링크에 어떤 요소가 있는지 → 그 요소를 `uav-sim-env`에서 어떤 오픈소스로 구현했는지 → 거기서 발생하는 애플리케이션 로그가 무엇인지를 정리한다.
> **대상**: KUS-FS급 **이중 데이터링크** — C-band LOS + Ku/Ka SATCOM BLOS.
> **레포 참조**: `datalink-los/{Dockerfile,entrypoint.sh,mavlink-router.conf}`, `datalink-satcom/`(OpenSAND), `datalink-stats/stats.py`, `telemetry-tap/tap.py`, `docs/sentinel-schemas.md`
> **참고**: MAVLink 스트림이 NDJSON·테이블로 가공되는 메커니즘은 `docs/uas-mapping-summary.md`의 telemetry-tap 절.

---

## 0. Data Link이란

Data Link은 AV와 지상(GCS)을 잇는 **무선 통신 경로**다. 명령(상향)·텔레메트리/영상(하향)이 이 위로 흐른다. KUS-FS급은 두 경로를 동시에 가진다:

- **LOS (Line of Sight)** — C-band 직접 RF. 가시선 내 ~200km, 저지연. 이착륙·근거리 통제.
- **BLOS (Beyond Line of Sight)** — Ku/Ka SATCOM(위성 중계). 한반도 주변 ~6,000km, GEO 왕복 ~600ms. 종심 임무·영상 중계.
- 두 경로는 동시 가용하며 **한쪽 실패 시 자동 전환(failover)** 한다.

> **GDT(Ground Data Terminal, 지상 RF 안테나)는 별도 컨테이너 없이 이 LOS 경로(`datalink-los`)에 통합**되어 있다. 자세한 건 다음 문서 (3) GDT.

---

## 1. 실제 데이터 링크의 구성 요소

| 구분 | 실제 요소 | 하는 일 |
|---|---|---|
| **LOS RF 링크** | C-band 송수신기, 변복조기, 안테나 | 가시선 내 명령·텔레메트리 전송 |
| **BLOS 위성 링크** | Ku/Ka 위성 단말, 위성(트랜스폰더), 위성지상국 | 가시선 밖 종심 통제·영상 중계 |
| **링크 특성** | 지연·지터·패킷손실·대역, 재밍 내성 | 실제 RF/위성 채널의 불완전성 |
| **링크 무결성/세션** | 시퀀스·서명·세션ID(특히 위성) | 변조·하이재킹 탐지 근거 |
| **라우팅/스위칭** | 다중 엔드포인트 분배, LOS↔BLOS 전환 | 명령·텔레메트리를 올바른 목적지로 |
| **데이터링크 표준** | CDL / TCDL (Ku, 영상/SAR/SIGINT) | 군 표준 링크 프로토콜 |

---

## 2. 오픈소스 구현

데이터 링크는 두 컨테이너로 나뉜다 — LOS는 `datalink-los`, BLOS는 `datalink-satcom`.

### 2.1 LOS — mavlink-router + tc netem (`datalink-los`)

실제 데이터 링크는 **"전파 매질" + "분배(라우팅/스위칭) 기능"** 두 부분으로 이루어진다(1절 요소표 참조). `datalink-los` 한 컨테이너가 이 둘을 각각 다른 오픈소스로 구현한다.

#### (1) 분배 기능 — mavlink-router
> ⚠️ 여기서 "라우터"는 **네트워크 IP 라우터가 아니라 MAVLink 패킷 분배기(multiplexer)** 다. 1절 요소표의 **"라우팅/스위칭 — 다중 엔드포인트 분배"** 칸을 구현한 것.

**왜 필요한가.** AV(ArduPilot SITL)는 MAVLink를 **딱 하나의 포트(TCP 5760)** 로만 내보낸다. 그런데 같은 스트림을 여러 소비자(GCS·관측탭·외부 도구)가 **동시에** 받아야 한다. 하나의 TCP 연결을 그냥 여러 곳으로 복제할 수는 없으므로, AV의 한 포트에서 MAVLink를 읽어 **여러 엔드포인트로 복사·분배**하는 표준 오픈소스 멀티플렉서가 mavlink-router다. 실제 무인기 지상체계도 MAVLink/영상을 여러 콘솔·분석기로 분배하는 라우팅·스위칭 기능을 가지며, 그 소프트웨어 대역이다.

**설정(`mavlink-router.conf`)상 엔드포인트:**

| 엔드포인트 | 방향 | 주소/포트 | 역할 |
|---|---|---|---|
| `[TcpEndpoint av_in]` | inbound | `10.50.0.10:5760` (TCP 클라이언트) | AV(SITL)에서 MAVLink 수신 |
| `[UdpEndpoint gcs_out]` | outbound | `10.50.0.30:14550` | GCS(QGC)로 송출 |
| `[UdpEndpoint tap_out]` | outbound | `10.50.0.40:14552` | telemetry-tap으로 송출 |
| `TcpServerPort` | inbound(서버) | `:5790` | **외부 접속점** (아래 (3)) |

#### (2) 전파 매질 — tc netem
- `entrypoint.sh`가 `eth0`에 지연·지터·손실을 주입한다(기본 `delay=50ms jitter=5ms loss=1%`, 정규분포). 실제 RF의 노이즈·거리감쇠·순단(산악 LOS)을 네트워크 계층에서 대신 모사한다. (`NET_ADMIN` cap 필요)
- 즉 mavlink-router가 "어디로 보낼지"를, netem이 "얼마나 깨끗하게 도착할지"를 담당한다.

#### (3) 외부 접속점(TcpServerPort 5790)이란
mavlink-router가 여는 **TCP 서버 포트(5790)** 로, 위 고정 엔드포인트(GCS·tap) 외에 **누구든 MAVLink 클라이언트로 직접 붙어 차량과 대화할 수 있는 입구**다. 호스트로 노출된다. 두 가지 용도가 있다:

- **정상 용도** — `av-muav/bootstrap.py`가 부팅 후 이 포트로 접속해 `ARMING_CHECK=0` 등을 PARAM_SET 한다. 디버깅용 MAVProxy/pymavlink 접속도 여기로.
- **공격면(A4)** — 현재 **인증이 없으므로**, 5790에 도달 가능한 누구든 차량에 임의의 MAVLink(`COMMAND_LONG` 등)를 주입할 수 있다. 이것이 의도된 **A4(MAVLink 평문 인젝션)** 시연 진입점이다. 레드팀 도구가 여기로 붙어 명령을 주입하고, SOC는 그 흔적(비인가 PeerIp, 주입 명령)을 탐지한다.

### 2.2 BLOS — OpenSAND (`datalink-satcom`)
- **무엇**: DVB-S2/RCS2 위성 통신을 물리·링크 계층까지 에뮬레이션하는 오픈소스 SATCOM 에뮬레이터. 세 엔티티로 위성 경로를 구성:
  - **ST(Satellite Terminal)** — AV 측 위성 단말
  - **SAT** — 투명 트랜스폰더(GEO 지연 ~600ms·대역·열화 산출)
  - **GW(Gateway)** — 위성지상국(Teleport)
- **동작**: AV(ST)→SAT→GW→GCS 경로로 MAVLink·영상 트래픽을 위성 링크 위에 터널링한다. 위성 고유 지연/대역/열화는 OpenSAND가, **세션ID·시퀀스·서명상태** 같은 무결성 메타는 별도 태깅 계층이 부여한다.
- **포인트**: ANASIS 고유 프로토콜(키 협상·빔 전환)은 비공개이므로 DVB-S2/RCS2 표준 + 무결성 태깅으로 대체. 이 경로가 있어야 **S3(SATCOM MITM)** 위협면이 실재화된다.

### 2.3 링크 통계 사이드카 — datalink-stats
- **무엇**: 링크/리소스 가시성을 위한 별도 관측 컨테이너(`datalink-stats/stats.py`). 30초마다:
  - `uav-datalink-los`의 docker stats 네트워크 카운터 → 링크 헬스
  - 전 compose 컨테이너 리소스 폴링 → CPU/MEM/IO
  - `datalink-los` 안에서 `ss -tn -H` → 5760/5790/14550-2 TCP 연결 스냅샷
- 의존: `/var/run/docker.sock` read-only 마운트.

---

## 3. 발생하는 애플리케이션 로그

데이터 링크의 로그는 **두 갈래**다 — (A) 링크 자체의 상태(통계·연결·세션), (B) 링크 위를 흐르는 MAVLink가 telemetry-tap에서 가공된 것.

```
av-muav ──MAVLink──▶ datalink-los (mavlink-router + netem)
                          │            └─5790─▶ 외부(A4)
                          ├─14552─▶ telemetry-tap ─▶ (B) UAV*_CL (요약 문서 참조)
av-muav ──MAVLink──▶ datalink-satcom (OpenSAND ST/SAT/GW) ──▶ satcom.ndjson ─▶ UAVSatcomLink_CL
datalink-stats (docker.sock 폴링) ──▶ (A) UAVDatalink_CL / UAVDatalinkConn_CL / UAVResourceMetrics_CL
```

### (A) 링크 자체 상태 — datalink-stats / datalink-satcom 산출

| 무엇 | 출처 | 테이블 | 핵심 컬럼 |
|---|---|---|---|
| LOS 링크 헬스(드롭/오류/대역) | datalink-stats | **`UAVDatalink_CL`** | `RxErrors`, `RxDropped`, `Rx/TxBytes`, `CpuUsagePct` |
| TCP 연결 스냅샷 | datalink-stats(`ss`) | **`UAVDatalinkConn_CL`** | `State`, `LocalPort`, `PeerIp/PeerPort` |
| 컨테이너 리소스 | datalink-stats | **`UAVResourceMetrics_CL`** | `CpuUsagePct`, `Memory*`, `Network*` |
| **SATCOM 링크/세션** | datalink-satcom | **`UAVSatcomLink_CL`** | `link_id`, `session_id`, `seq`, `integrity_status`, `rtt_ms`, `jam_indicator` |

### (B) 링크 위 트래픽(MAVLink) — telemetry-tap 가공
링크를 통과하는 MAVLink는 telemetry-tap이 NDJSON으로 풀어 `UAVTelemetry_CL`·`UAVOperator_CL` 등으로 적재한다(메커니즘·분기표는 `docs/uas-mapping-summary.md`). 데이터 링크 관점에서 특히 의미 있는 것:
- **`UAVMavsec_CL`** — telemetry-tap이 30초 윈도우로 집계한 MAVLink **서명 카운트**(`SignedCount`/`UnsignedCount`/`FailedCount`). 평문(비서명) 비율이 링크 보안 상태를 드러낸다.

### 3.1 어떻게 시나리오로 연결되나
- **재밍(JAM)**: netem 손실률 급증 또는 `UAVDatalink_CL`의 `RxDropped` 델타 급증 → 링크 열화 탐지. (위성 측은 `UAVSatcomLink_CL.jam_indicator`)
- **S3 SATCOM MITM/무결성**: `UAVSatcomLink_CL`의 `integrity_status` 위반·`seq` 점프·`session_id` 급변 → 중간자/하이재킹.
- **A4 MAVLink 인젝션**: 외부가 `5790`에 접속 → `UAVDatalinkConn_CL`에 비인가 `PeerIp` 출현, 주입된 `COMMAND_LONG`은 `UAVOperator_CL`.
- **링크 보안 저하**: `UAVMavsec_CL`의 `UnsignedCount` 비율 상승.

---

## 4. 요약

데이터 링크는 LOS(`datalink-los`: mavlink-router로 라우팅 + tc netem으로 RF 열화)와 BLOS(`datalink-satcom`: OpenSAND로 위성 물리계층 + 무결성 태깅)로 이원화된다. 로그는 **링크 자체 상태**(datalink-stats → `UAVDatalink_CL`/`Conn`/`ResourceMetrics`, datalink-satcom → `UAVSatcomLink_CL`)와 **링크 위 MAVLink**(telemetry-tap 가공, 특히 `UAVMavsec_CL`)로 나뉜다. 핵심 위협면은 **재밍·S3(SATCOM 무결성)·A4(평문 인젝션)** 다.

다음 상세 문서: (3) GDT.
