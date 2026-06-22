# UAV 배경지식 — 분류와 구현 대상 (지작사 ISR 핸드오프 관점)

> **상태**: v0.1 (배경지식 정리)
> **목적**: `uav-sim-env` 시뮬을 분대급 MPD(Group 1)에서 **중고도 정찰체계(MUAV/KUS-FS급)** 로 확장하기 위한 사전 배경지식.
> **확장 방향 결정**: S3(SATCOM MITM) 위협면을 실재화하기 위해 **KUS-FS(공군 운용 MUAV)** 를 모사 대상으로 삼되, **육군 지작사는 ISR 정보 소비자**로 두고 **공군→육군 정보 핸드오프 지점을 보호경계/신규 공격면**으로 정의한다.
> **관련 문서**: `docs/components.md`(컴포넌트 상세), `pollack-ai/docs/uav-sim-muav-migration.md`(확장 설계서)

---

## 0. 한 줄 요약

육군 지작사가 **직접 운용**하는 유기적 UAV(대대~군단급)는 전부 **LOS+중계 방식이라 SATCOM이 없다**. SATCOM/BLOS는 한 체급 위인 **공군의 중고도(MUAV/KUS-FS)·고고도(글로벌호크) 정찰자산** 영역이다. 따라서 SATCOM 위협면(S3)을 다루려면 공군 자산 KUS-FS를 모사하고, 지작사는 그 영상·표적을 **핸드오프 받아 소비하는 경계**로 설계한다.

---

# 1. UAV의 분류와 우리가 구현하고자 하는 UAV

UAV는 보는 관점에 따라 두 갈래로 나뉜다. 둘을 겹쳐 봐야 "누가 무슨 통신으로 운용하는가"가 드러난다.

- **(A) 능력 기준** — 미 DoD **UAS Group 1~5** (무게·고도·속도)
- **(B) 운용 제대 기준** — 한국군 **대대 / 사단 / 군단 / 전구·전략**

## 1.1 능력 기준 — UAS Group 1~5 (DoD JCIDS)

분류 기준은 **최대이륙중량(MGTW) · 운용고도 · 속도** 중 **하나라도(any-of)** 상위 임계를 넘으면 상위 Group으로 재분류한다.

| Group | 중량 | 고도 | 대표 기체 | 통신 |
|---|---|---|---|---|
| 1 | < 20 lb | < 1,200 ft AGL | RQ-11 Raven, Switchblade, **MPD(현 시뮬)** | LOS RF |
| 2 | 21~55 lb | < 3,500 ft AGL | ScanEagle, RQ-21 | LOS RF |
| 3 | < 1,320 lb | < 18,000 ft MSL | RQ-7 Shadow, **RQ-101 송골매** | LOS + 일부 중계 |
| 4 | > 1,320 lb | < 18,000 ft MSL | MQ-1C Gray Eagle, **KUS-FS(MUAV)** | **★ SATCOM 필수** |
| 5 | > 1,320 lb | > 18,000 ft MSL | MQ-9 Reaper, RQ-4 Global Hawk | **★ SATCOM 필수** |

**핵심 임계점은 Group 4다.** Group 4 이상부터 작전 종심이 LOS 가시선(약 200km)을 넘어서기 때문에 **위성 중계(BLOS)가 표준**이 된다. 즉 SATCOM 위협면은 본질적으로 Group 4~5의 문제다.

## 1.2 운용 제대 기준 — 한국군 (종심이 기체를 결정한다)

| 제대 | 대표 기체 | 체급 | 작전반경 | 통신 | 운용 주체 |
|---|---|---|---|---|---|
| 대대 | 리모아이 등 | Group 1 | 수~십 km | LOS only | 육군 |
| 사단 | 서치아이/RQ-102 계열 | Group 2~3 | 수십 km | LOS only | 육군 |
| **군단** | **RQ-101 송골매** | Group 3 | 110km(중계 시 ~200km) | **LOS + 지상중계** | **육군(지작사)** |
| 군단(차기) | NCUAV-II(차기 군단급) | Group 3~4 | 송골매 대비 2배↑ | LOS + 중계, SATCOM 옵션 검토 | 육군(지작사) |
| **전구** | **KUS-FS(MUAV)** | **Group 4** | **100~300km** | **LOS(C-band) + SATCOM(Ku/Ka)** | **공군(제39정찰비행단)** |
| 전략 | RQ-4 Global Hawk | Group 5 | 수천 km | SATCOM | 공군 |

> ⚠️ **조직 경계 (설계의 핵심)**: 송골매·차기 군단급(NCUAV-II)까지가 **지작사가 직접 운용**하는 한계선이며 **전부 LOS/중계**다. KUS-FS·글로벌호크는 **공군 제39정찰비행단이 운용**하고, 지작사는 그 산출물(영상·표적)을 **C4I로 전달받아 소비**한다. 따라서 SOC의 "보호 경계"는 단일 부대 망이 아니라 **공군 자산 망 + 육군 소비 핸드오프**로 확장되며, 이 조직 간 데이터 핸드오프 지점 자체가 새로운 공격면이다.

## 1.3 구현 대상 — KUS-FS (MUAV, 중고도 정찰용 무인기)

본 확장에서 모사할 기체는 **KUS-FS**다.

- **개발/제작**: 국방과학연구소(ADD) + 대한항공
- **형상**: 전장 13.3m / 전폭 25.3m / 전고 3m, 한화 1,200마력 터보프롭 1기
- **중량**: 최대이륙중량(MTOW) 5,750kg
- **고도/체공**: 최대 45,000ft(약 13.7km), **24시간** 장기체공
- **능력**: 6~13km 상공에서 **약 100km 밖** 표적 고해상도 촬영
- **페이로드**: EO/IR + (SAR/GMTI 정찰 중심)
- **구성**: 비행체 **2~4대 + 지상통제(GCS) + 지상지원장비**
- **통신**: **LOS(C-band) + BLOS(SATCOM, Ku/Ka)** 이중 링크
- **사업 일정**: 2023.3 전투용 적합 판정 → 2024.1 양산 → **2027년부터 공군 순차 배치**

**왜 KUS-FS인가.** 현 시뮬(MPD, Group 1, LOS only)에서 비활성이던 **S3(SATCOM MITM)** 위협면을 실재화할 수 있는 최소 체급이 Group 4이고, 한국군에서 그 실체가 KUS-FS다. 송골매(군단급)는 SATCOM이 없어 S3을 칠 대상이 없다. 즉 **"SATCOM을 다루겠다"는 결정이 곧 KUS-FS(공군 자산) 모사를 의미**한다.

---

# 2. KUS-FS의 목적 · 통달거리 · 통신방법 · 운용시스템 구성요소

## 2.1 목적 (Mission)

중고도 장기체공(MALE)을 살린 **광역 감시정찰(ISR)** 이 본분이다.

- 6~13km 상공에서 **24시간 무중단** 체공하며 광역 감시
- EO/IR + (SAR) 로 **주야·악천후** 표적 고해상도 촬영
- 북한 핵·미사일 시설 등 **종심 표적 상시 감시**, 위기 시 표적 갱신
- 산출 영상/표적을 **C4I(ATCIS/MIMS) 망으로 전파** → 육군 등 수요 제대가 소비

## 2.2 통달거리 (Reach)

| 링크 | 매체 | 통달거리 | 지연 | 용도 |
|---|---|---|---|---|
| LOS | C-band 직접 RF | 가시선 내 ~200km | 저지연(수~수십 ms) | 이착륙·근거리 통제 |
| BLOS | Ku/Ka SATCOM(위성 중계) | **한반도 주변 약 6,000km** | **GEO 왕복 ~600ms** | 종심 임무 통제·영상 중계 |

작전반경 자체는 100~300km급이지만, **SATCOM을 거치면 가시선과 무관하게 한반도 전역을 커버**한다. 두 경로가 동시 가용하여 **한 링크 실패 시 자동 전환(failover)** 한다 — 이착륙은 C-band LOS, 순항/임무 구간은 위성 BLOS가 표준 운용이다.

## 2.3 통신방법 (Communication)

### (1) 이중 데이터링크 구조

```
                   ┌─────────────────────────────┐
                   │  ANASIS-II (군 전용 GEO 위성) │
                   │  Ku/Ka 트랜스폰더, 고도 36,000km │
                   └──────▲───────────────┬────────┘
              Ku/Ka Uplink                │ Downlink
                          │               │
        ┌─────────────────┴───┐    ┌──────▼───────────────┐
        │ AV (KUS-FS)         │    │ 위성지상국(Teleport) │
        │ Ku Uplink + C-band  │    └──────┬───────────────┘
        └──────────┬──────────┘           │ 지상 광케이블/IP
            C-band LOS │ (이착륙·근거리)    │
                       ▼                   ▼
                ┌──────────────┐    ┌──────────────────────────┐
                │ GDT (C-band) │───▶│ GCS / MCE                │
                │ 지상 RF 안테나│ 유선│ 임무계획·조종·영상/SAR 분석 │
                └──────────────┘    └──────────────────────────┘
```

- **LOS(가시선)**: C-band 직접 RF. 이착륙·근거리 통제. 저지연.
- **BLOS(비가시선)**: Ku/Ka SATCOM. AV가 위성으로 올린(Uplink) 신호를 **위성지상국(Teleport)** 이 받아 광케이블/IP로 GCS·MCE에 전달. 종심 임무·영상 중계.
- **데이터링크 표준 계열**: CDL(Common Data Link, Ku, ~274Mbit/s), TCDL(Tactical CDL, 1.5~10.7Mbit/s, 영상/SAR/SIGINT).

### (2) 위성 백본 — ANASIS-II

- **ANASIS-II(아나시스 2호)**: 2020.7.21 발사, 고도 36,000km **정지궤도(GEO)**, 한국 **최초의 순수 군 전용** 통신위성(에어버스 Eurostar E3000).
- 다중대역(UHF/X/Ka), 기존 대비 데이터 전송용량 2배↑, **재밍 저항성 강화**.
- **ANASIS-I = 무궁화 5호(2006)**: 민·군 겸용. 노후화로 군 전용 ANASIS-II가 대체. (초기 MUAV 관련 자료에 "무궁화 5호"로 언급되는 것은 ANASIS-I 시절 표현.)

### (3) 통신 관점 위협면 (왜 SOC가 이 구조를 보는가)

- **S3 — SATCOM MITM/무결성 위반**: 위성 경로의 시퀀스 점프·서명 불일치·세션 하이재킹·중간자 주입. (LOS only인 현 MPD엔 없던 신규 위협면.)
- **지연/재밍 의존성**: GEO ~600ms RTT, 재밍 시 BLOS↔LOS 전환 거동.
- **공군→육군 핸드오프**: 위성지상국→GCS/MCE→C4I로 넘어가는 **조직 간 데이터 전달 지점**의 무결성·인가.

## 2.4 운용시스템 구성요소 (UAS 5대 구성요소 + 위성 요소)

미 육군 교범 **FMI 3-04.155** 의 UAS 5대 구성요소에, SATCOM 체계 특유의 **위성/지상국 요소**가 추가된다.

| 구성요소 | 역할 | KUS-FS급에서의 의미 | 현 시뮬 매핑(`uav-sim-env`) |
|---|---|---|---|
| **AV** (Air Vehicle) | 비행체 + 페이로드(EO/IR·SAR) + GPS/INS/IFF | 고정익 MALE, 2~4대 편대 | `av-mpd` → `av-muav`(신규, `-f plane`) |
| **Data Link** | LOS C-band + **BLOS SATCOM** 이중 링크 | SATCOM 신설이 정의적 변화 | `datalink-los` + `datalink-satcom`(신규) |
| **GDT** (Ground Data Terminal) | 지상 RF 안테나(LOS) | C-band 근거리 단말 | `datalink-los` 통합 |
| **GCS / MCE** (Ground Control Station / Mission Control Element) | 임무계획·조종·영상/SAR 분석 | 다중 AV 통제 | `gcs-qgc` |
| **PGSE** (Payload & Ground Support Equip.) | 발사·정비·회수·지상전원 | 활주로 이착륙 지원 | `pgse-stub` |
| **위성지상국 (Teleport)** | 위성↔지상 광케이블/IP 게이트웨이 | BLOS 경로의 지상 종단 | `datalink-satcom` 내 모사(신규) |
| **위성 (ANASIS-II)** | Ku/Ka GEO 트랜스폰더 | BLOS 중계 백본 | 링크 특성(지연·세션)으로 추상화 |

> 보조 시스템(MPS 임무계획, C4I=ATCIS/MIMS, Cyber Posture, Weapon, TI, Auth)은 현 시뮬과 동일하게 유지된다(`docs/components.md` 참조). 다만 **C4I 핸드오프**는 공군 자산 영상이 육군 망으로 들어오는 지점이라 KUS-FS 맥락에서 보안 중요도가 올라간다.

---

## 3. 현 시뮬(MPD) 대비 변경 요약 (배경지식 → 설계 연결)

| 항목 | 현재(MPD, Group 1) | 대상(KUS-FS, Group 4) |
|---|---|---|
| 운용 제대/주체 | 분대급 / 육군 | 전구급 / 공군 운용 → 육군 소비 |
| 기체 frame | quadplane VTOL | 고정익 MALE(고고도·장기체공) |
| 통신 | LOS only | **LOS + SATCOM/BLOS 이중 링크** |
| 통달거리 | 수십 km | 100~300km(SATCOM 시 ~6,000km) |
| 운용 대수 | 단일기 | 2~4대 편대 |
| 신규 구성요소 | — | datalink-satcom, 위성지상국, (SAR) |
| 활성 위협면 | S1/S4/A4 등 | **+ S3(SATCOM MITM)**, + 편대 횡적확산, + 공군→육군 핸드오프 |

→ 상세 컴포넌트/수집/탐지 설계는 `pollack-ai/docs/uav-sim-muav-migration.md`로 이어진다.

---

## 4. 참고 자료 (Sources)

**미군 UAS 교범 / 분류**
- FMI 3-04.155 *Army Unmanned Aircraft System Operations*
- ATP 3-04.64 *Army UAS* / FM 3-04 *Army Aviation*
- [UAS groups of the United States military — Wikipedia](https://en.wikipedia.org/wiki/List_of_unmanned_aerial_vehicles_of_the_United_States_military)

**SATCOM / 데이터 링크 (사내 자료)**
- `pollack-ai/UAV 및 UGV 위성통신 시스템 구조 조사.pdf` (UAS 5요소, Group 분류, MQ-9 이중링크, CDL/TCDL, KUS-FS+ANASIS-II)

**한국군 UAV / 위성**
- [KUS-FS 중고도 무인기 — 위키백과](https://ko.wikipedia.org/wiki/KUS-FS_%EC%A4%91%EA%B3%A0%EB%8F%84_%EB%AC%B4%EC%9D%B8%EA%B8%B0)
- [중고도무인기 2027년 공군 배치 — 글로벌이코노믹](https://www.g-enews.com/article/Industry/2024/12/202412191624393158c5557f8da8_1)
- [제39정찰비행단 — 위키백과](https://ko.wikipedia.org/wiki/%EC%A0%9C39%EC%A0%95%EC%B0%B0%EB%B9%84%ED%96%89%EB%8B%A8)
- [RQ-101 송골매 — 위키백과](https://ko.wikipedia.org/wiki/RQ-101_%EC%86%A1%EA%B3%A8%EB%A7%A4)
- [차기 군단급 무인기 — 위키백과](https://ko.wikipedia.org/wiki/%EC%B0%A8%EA%B8%B0_%EA%B5%B0%EB%8B%A8%EA%B8%89_%EB%AC%B4%EC%9D%B8%EA%B8%B0)
- [ANASIS-II(아나시스 2호) — 위키백과](https://ko.wikipedia.org/wiki/%EC%95%84%EB%82%98%EC%8B%9C%EC%8A%A4_2%ED%98%B8)
- [한국군 첫 전용 통신위성 아나시스 2호 발사 — 대한민국 정책브리핑](https://www.korea.kr/news/policyNewsView.do?newsId=148874912)
