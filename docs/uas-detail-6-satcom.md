# UAS 상세 (6) — +1 위성 / 위성지상국 (SATCOM)

> **성격**: 소개·학습 문서. SATCOM의 위성·위성지상국이 실제로 무엇인지 → 그 역할을 `uav-sim-env`에서 어떤 오픈소스로 구현했는지 → 거기서 발생하는 애플리케이션 로그가 무엇인지를 정리한다.
> **대상**: KUS-FS급 BLOS 경로 — ANASIS-II(군 전용 GEO 위성) + 위성지상국(Teleport).
> **레포 참조**: `datalink-satcom/`(OpenSAND), `telemetry-tap`(태깅 연계), `docs/sentinel-schemas.md`
> **앞 문서**: (2) Data Link — BLOS 경로가 여기서 더 깊이 다뤄진다. (3) GDT의 가시선 지상관문에 대응하는 *위성 경유 지상관문*이 본 문서의 Teleport다.

---

## 0. "+1"이란 — 왜 5요소 밖인가

FMI 3-04.155의 UAS 5요소(AV·Data Link·GDT·GCS·PGSE)는 본래 LOS 중심이다. KUS-FS급(Group 4, MALE)은 작전 종심이 가시선(~200km)을 넘어 **위성 중계(BLOS)** 가 필수가 되는데, 이때 5요소에 없던 **위성(트랜스폰더)과 위성지상국(Teleport)** 이 새 구성요소로 들어온다. 이것이 "+1"이다. 분대급 MPD(LOS only)에는 없었고, **KUS-FS 확장의 정의적 변화**다.

```
        AV(ST) ──Ku/Ka Uplink──▶ [위성: ANASIS-II] ──Downlink──▶ [위성지상국 Teleport]
                                  GEO 36,000km                         │ 유선/IP
                                  RTT ~600ms                           ▼
                                                                  GCS / MCE
```

---

## 1. 실제 구성 요소

| 구분 | 실제 요소 | 하는 일 |
|---|---|---|
| **위성 (ANASIS-II)** | 군 전용 GEO 통신위성, Ku/Ka(+UHF/X) 트랜스폰더 | 지상↔AV 신호 중계, 재밍 내성 |
| **위성 단말 (ST)** | AV 탑재 Ku/Ka 위성 모뎀·안테나 | 위성으로 업링크/다운링크 |
| **위성지상국 (Teleport)** | 대형 지상 안테나 + 게이트웨이 | 위성 신호 수신 → 유선/IP로 GCS 전달 |
| **링크 특성** | 큰 전파지연(~600ms RTT)·대역·열화 | BLOS 채널의 물리 현실 |
| **세션/무결성** | 빔 전환·키 협상·시퀀스·서명 | 변조·하이재킹 탐지 근거 |

> ANASIS-II: 2020.7 발사, 한국 최초 순수 군 전용 GEO 위성, 한반도 주변 ~6,000km BLOS, 재밍 저항성 강화. (배경: `docs/muav-background.md`)

---

## 2. 오픈소스 구현 — OpenSAND (`datalink-satcom`)

BLOS 경로는 **OpenSAND**(DVB-S2/RCS2 위성 통신을 물리·링크 계층까지 에뮬레이션하는 오픈소스 SATCOM 에뮬레이터)로 `datalink-satcom` 컨테이너에 구현한다.

### 2.1 세 엔티티 = 실제 요소 매핑
| OpenSAND 엔티티 | 실제 대응 | 역할 |
|---|---|---|
| **ST (Satellite Terminal)** | AV 측 위성 단말 | AV의 업링크/다운링크 종단 |
| **SAT** | 위성(ANASIS-II) 트랜스폰더 | GEO 지연(~600ms)·대역·열화 산출 (투명 트랜스폰더) |
| **GW (Gateway)** | 위성지상국(Teleport) | 위성 신호 수신 → GCS로 전달하는 지상 게이트웨이 |

### 2.2 동작
- AV(ST) → SAT → GW(Teleport) → GCS 경로로 **MAVLink·영상 트래픽을 위성 링크 위에 터널링**한다.
- 위성 고유의 **지연/대역/열화는 OpenSAND가 물리계층에서** 산출(GDT의 tc netem 대비 훨씬 사실적).
- ANASIS 고유 프로토콜(빔 전환·키 협상)은 비공개이므로 **DVB-S2/RCS2 표준**으로 대체한다.

### 2.3 무결성 메타 태깅 계층
- OpenSAND가 물리/링크층을 맡더라도, **S3 탐지에 필요한 보안 메타**(세션ID·시퀀스·서명상태)는 OpenSAND가 직접 주지 않는다. 그래서 `datalink-satcom`에 **별도 태깅 계층**을 두어 링크/세션 메타를 부여하고 NDJSON으로 떨군다.
- 운영 주의: OpenSAND는 셋업/파라미터가 복잡하고 컨테이너 부하가 커서, SITL과 같은 VM에서 리소스 경합에 유의(필요 시 VM 상향).

---

## 3. 발생하는 애플리케이션 로그

SATCOM은 `datalink-satcom`이 **자체 NDJSON**(`satcom.ndjson`)을 떨군다(telemetry-tap 경유 아님). OpenSAND 링크 통계 + 무결성 태깅을 합친 결과다.

| 무엇 | 테이블 | 핵심 컬럼 |
|---|---|---|
| 위성 링크/세션 상태 | **`UAVSatcomLink_CL`** | `link_id`, `session_id`, `seq`, `integrity_status`, `rtt_ms`, `jam_indicator`, `src/dst` |

- `rtt_ms` — GEO 특성(~600ms)에서 벗어나는 비정상 지연 감지.
- `seq` / `session_id` — 시퀀스 점프·세션 급변으로 하이재킹·재전송 탐지.
- `integrity_status` — 서명 불일치 등 무결성 위반.
- `jam_indicator` — 재밍 정황.

> 링크 위를 흐르는 MAVLink 자체는 (2)/(1)과 동일하게 telemetry-tap이 `UAVTelemetry_CL` 등으로 가공한다. 본 테이블은 **위성 링크 계층 고유 신호**만 담는다.

### 3.1 어떻게 시나리오로 연결되나 — S3 (SATCOM MITM)
- **무결성 위반**: `integrity_status` 실패 / `seq` 점프 → 중간자 주입·변조. (룰 예: `S3-satcom-integrity-fail`)
- **세션 하이재킹**: 동일 `link_id`에 `session_id` 급변·중복 → 세션 탈취. (룰 예: `S3-satcom-session-hijack`)
- **재밍/지연 공격**: `jam_indicator` 상승 또는 `rtt_ms` 이상 → 의도적 방해.
- **편대 적용**: 다수기의 위성 링크를 `link_id`/`uav_id`로 구분해 편대 단위 이상도 탐지.

---

## 4. 요약

"+1"은 LOS 5요소 밖에서 KUS-FS급에 새로 들어오는 **위성(ANASIS-II 트랜스폰더)과 위성지상국(Teleport)** 이다. `datalink-satcom`이 **OpenSAND의 ST/SAT/GW** 로 위성 경로를 물리계층까지 모사하고, S3 탐지용 **세션·시퀀스·서명 메타는 별도 태깅 계층**이 부여한다. 로그는 `UAVSatcomLink_CL`이며, 이 경로가 있어야 그동안 비활성이던 **S3(SATCOM MITM·무결성·세션 하이재킹·재밍)** 위협면이 실재화된다.

— UAS 5+1 요소별 상세 문서 시리즈 끝. (AV·Data Link·GDT·GCS/MCE·PGSE·+1 SATCOM)
