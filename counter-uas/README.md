# counter-uas — 카운터 드론 RF 탐지 → 근접 → 자동 재밍 (시뮬)

방어 자산에 접근하는 **다른 드론의 RF 주파수를 수동 탐지**하고, 추정 거리가 임계
이내로 들어오면 **해당 대역에 자동으로 방해(재밍)** 를 거는 카운터-UAS 시스템의
**순수 소프트웨어 시뮬레이션**. 하드웨어 불필요.

> ⚠️ **법적 고지 — 실제 송신 없음.** 이 컴포넌트는 어떤 주파수도 방사하지 않는다.
> RF 탐지(수신)는 합법이지만 실제 재밍 송신은 한국·대부분 국가에서 허가 없이
> 불법이며 주변 통신/항법에 실제 피해를 준다. 여기서 재밍은 **J/S(jam-to-signal)
> 비로 효과만 계산해 로깅**한다. 실송신은 허가·차폐환경에서만 별도로 다룰 사안.

---

## 무엇을 모델링하나

```
                    [ 방어 자산 (원점) ]
                     수동 RF 탐지기 + 재밍기(시뮬)
                          ▲ RSSI          │ J/S 효과
          탐지(거리추정)  │                ▼ (시뮬 작동)
   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
   │ HOSTILE 2.4G │   │ UNKNOWN 915M │   │ FRIENDLY 5.8G│  ← 침입 트랙
   │  접근중 ───▶ │   │  접근중 ───▶ │   │  통과(보호)  │
   └──────────────┘   └──────────────┘   └──────────────┘
```

처리 루프(매 tick):

1. **공역 전진** — 침입 트랙을 기동(접근/이탈)시킨다.
2. **수동 탐지** — 각 emitter 의 RSSI 를 경로손실 모델로 계산(+측정잡음) → 수신감도
   이상이면 탐지. RSSI 로 **거리 역추정**, 주파수로 **대역 분류**.
3. **근접 교전 판정** — 추정 거리 ≤ 임계 & 적성(hostile/unknown) & ROE=auto 면
   해당 대역에 재밍(시뮬). **아군(friendly)은 근접해도 보호(미교전).**
4. **효과 모델** — 드론 수신단 J/S 가 차단 임계 이상이면 링크 차단 → 트랙이 정지
   (jammed) → 이탈(retreating). 폐루프가 눈에 보인다.
5. **NDJSON 방출** — 탐지/교전 레코드를 `UAVCounterUas_CL` 스키마로 출력.

### RF 물리 (`counter_uas/rf.py`)

- **경로손실**: log-distance 모델 `PL(d)=FSPL(1m)+10·n·log10(d)` (n=경로손실지수).
- **RSSI**: `EIRP − PL(d) + 수신이득`.
- **거리추정**: RSSI 역산. 탐지기는 실제 EIRP 를 모르므로 대역별 기준 EIRP 가정 →
  추정 거리에 현실적 오차가 생긴다.
- **대역**: 433MHz / 915MHz / 1.5GHz(GPS L1) / 2.4GHz(제어) / 5.8GHz(FPV).

---

## 빠른 실행

### 1) 콘솔 데모 (하드웨어·의존성 0 — 발표용)

```bash
cd counter-uas
python3 scripts/demo.py
```
3개 트랙(접근 hostile 2.4G · unknown 915M · friendly 5.8G)이 동시 접근하며,
hostile 이 200m 진입 시 자동 재밍 → 링크 차단 → 이탈하는 폐루프가 출력된다.

### 2) 서비스 (FastAPI 제어면)

```bash
pip install -r requirements.txt
LOG_FILE_PATH=/dev/stdout uvicorn app:app --host 0.0.0.0 --port 8810
```
| 엔드포인트 | 설명 |
|---|---|
| `GET /health` | 헬스 체크 |
| `GET /state` | 자산/재밍/트랙 현재 상태 |
| `POST /intruder/spawn` | 접근 침입자 주입(`track_id/start_range_m/bearing_deg/speed_mps/center_mhz/allegiance`) |
| `DELETE /intruder/{id}` | 침입자 제거 |
| `POST /jammer/config` | 재밍 정책 갱신(`armed/roe/threshold_m/jam_eirp_dbm/engage_friendly`) |

예시:
```bash
curl -XPOST localhost:8810/intruder/spawn -H 'content-type: application/json' \
  -d '{"track_id":"H1","start_range_m":500,"bearing_deg":30,"speed_mps":25,"center_mhz":2440,"allegiance":"hostile"}'
curl localhost:8810/state
```

### 3) 테스트

```bash
python3 -m pytest tests/ -q
```

---

## 환경변수

| 변수 | 기본 | 설명 |
|---|---|---|
| `ASSET_ID` | `CUAS-SITE-1` | 방어 자산 식별자(레코드 UAVId) |
| `TICK_SEC` | `1.0` | 시뮬 tick 간격(초) |
| `JAM_THRESHOLD_M` | `200` | 재밍 작동 근접 임계(m) |
| `JAM_EIRP_DBM` | `33` | 재밍 EIRP(시뮬) |
| `JAM_ROE` | `auto` | `auto`=근접 자동재밍 / `manual`=권고만 |
| `RX_SENSITIVITY_DBM` | `-95` | 탐지 수신감도 |
| `LOG_FILE_PATH` | `` | NDJSON 싱크(`/dev/stdout` 권장, 빈값=비활성) |

---

## uav-sim-env 통합 상태

| 항목 | 상태 |
|---|---|
| Dockerfile | ✅ `counter-uas/Dockerfile` (FastAPI, :8810) |
| helm 템플릿 | ✅ `local-k8s/helm/uav-sim/templates/counter-uas.yaml` (ns: ground) |
| values 블록 | ✅ `values.yaml` 의 `counterUas:` (enabled, env) |
| kind 빌드 등록 | ✅ `local-k8s/up.sh` 에 `build_load uavsim/counter-uas:local` |
| Sentinel 적재 | ⏳ 아래 "남은 단계" (DCR 스트림 + 테이블 + fluentbit 1줄) |

`cd local-k8s && bash up.sh` 하면 kind 에서 counter-uas 가 ground 네임스페이스에
함께 뜬다(fluentbit 는 kind 에서 off 이므로 NDJSON 은 pod stdout 으로 확인:
`kubectl -n ground logs deploy/counter-uas`).

### Sentinel 적재(AKS) — 남은 단계

NDJSON 17→18 스트림 패턴에 그대로 얹는다:

1. **테이블** `UAVCounterUas_CL` 추가 — `infra/sentinel/tables.bicep`. 컬럼:
   `TimeGenerated, EventType, UAVId, Seq, TrackId, Band, CenterFreqMHz, Rssi_dBm,
   EstRange_m, TrueRange_m, Bearing_deg, Classification, Protocol,
   TargetBand, JamFreqMHz, JamMode, JamEirp_dBm, JsRatio_dB, Effect, Status, ReasonCode`.
2. **DCR 스트림** `Custom-UAVCounterUas` 추가(예: ext2 DCR `dcr-1aad0b1c...`).
3. **fluentbit 1줄** — `values.yaml` 의 `fluentBit.streams` 에 추가:
   ```yaml
   - { container: counter-uas, dcrId: "dcr-1aad0b1cd2f9416e9fb954b402abc58d", stream: "UAVCounterUas", marker: "EventType" }
   ```
   (마커 `EventType` 는 항상 문자열 — `rewrite_tag` integer 매칭 함정 회피.)

### 비행 시뮬과 연동(선택)

지금은 침입자 기동을 자체 모델링한다. 실제 SITL 편대를 침입 트랙으로 쓰려면
`/intruder/spawn` 대신 MAVLink `GLOBAL_POSITION_INT` 를 받아 자산 기준 ENU 로
변환해 트랙을 갱신하면 된다(emitter 는 기체 대역으로 매핑). 탐지·교전 로직은 무변경.

---

## 파일 구조

```
counter-uas/
├── app.py                      # FastAPI 서비스 + 백그라운드 tick 루프 + 제어 API
├── counter_uas/
│   ├── rf.py                   # 경로손실/RSSI/거리추정/대역분류
│   ├── airspace.py             # 방어자산·침입자 emitter·기동
│   ├── detector.py             # 수동 스펙트럼 스캔 → 탐지
│   ├── engagement.py           # 근접 정책 + 재밍 + J/S 효과
│   └── engine.py               # 공역 전진→스캔→교전→NDJSON
├── scripts/demo.py             # 콘솔 데모(하드웨어 불요)
├── tests/test_counter_uas.py   # 단위 테스트
├── Dockerfile · requirements.txt
└── k8s/counter-uas.yaml        # helm 템플릿 사본(참고용)
```
