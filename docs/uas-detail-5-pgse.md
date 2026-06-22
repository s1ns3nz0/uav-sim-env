# UAS 상세 (5) — PGSE (Payload & Ground Support Equipment)

> **성격**: 소개·학습 문서. 실제 PGSE가 무엇인지 → 그 역할을 `uav-sim-env`에서 어떤 오픈소스로 구현했는지 → 거기서 발생하는 애플리케이션 로그가 무엇인지를 정리한다.
> **대상**: KUS-FS급 지상지원 — 활주로 이착륙 지원·정비·발사 승인·펌웨어 관리.
> **레포 참조**: `pgse-stub/{Dockerfile,app.py,data/approved_firmware.json}`, `docs/sentinel-schemas.md`

---

## 0. PGSE란

PGSE(Payload & Ground Support Equipment, 페이로드·지상지원장비)는 **비행체를 띄우고·정비하고·회수하는 지상 장비 일체**다. 발사 카타펄트(또는 활주로 지원), 정비공구, 회수 네트, 지상전원, 그리고 출격 전 펌웨어·무장 검증과 발사 승인 절차까지 포함한다.

> **SOC 관심사는 물리 장비가 아니라 "절차의 무결성"** 이다 — 출격 전에 *승인된 펌웨어인지*, *발사가 정당하게 승인됐는지*를 판정하는 결정 로직이 조작되면 위조된 출격이 가능해진다. 그래서 PGSE는 **디지털 결정 표면**만 모사한다.

---

## 1. 실제 PGSE의 구성 요소

| 구분 | 실제 요소 | 하는 일 |
|---|---|---|
| 발사 장비 | 카타펄트 / 활주로 이착륙 지원 | 기체 출격 |
| 정비 | 정비공구·점검 절차·캘리브레이션 | 가동 상태 유지 |
| 회수 | 회수 네트 / 착륙 지원 | 기체 회수 |
| 지상 전원 | 발전·전원공급 | 출격 전 급전 |
| **무기고/펌웨어(Armory)** | 승인 펌웨어·무장 관리 | 출격 전 무결성 보증 |
| **발사 승인 절차** | preflight 검증 → 발사 인가 | "이 기체를 띄워도 되는가" 판정 |

---

## 2. 오픈소스 구현 — FastAPI 결정 표면 (`pgse-stub`)

PGSE는 **FastAPI/uvicorn** 으로 장비의 결정 로직만 REST API로 구현한다(`pgse-stub`, 포트 8000, Swagger `/docs`). 물리 장비는 모사하지 않는다.

### 2.1 엔드포인트 (`app.py`)
| 메소드 + 경로 | 동작 |
|---|---|
| `GET /armory/firmware/{uav_id}` | 승인된 펌웨어 해시 조회 (`data/approved_firmware.json`) |
| `POST /preflight/check` | 제출 펌웨어 해시 + SBOM 검증 → `Passed` 판정 |
| `POST /launch/authorize` | preflight 통과 시에만 단기 발사 토큰 발급 |
| `GET /launch/token/{token}` | 토큰 유효성 검증 |
| `POST /maintenance/battery/cycle` | 배터리 사이클 기록 |
| `POST /maintenance/calibration` | 센서 캘리브레이션 기록 |
| `POST /maintenance/inspection/sign` | 점검표 서명 |

### 2.2 핵심 결정 로직
- **펌웨어 무결성**: 제출 해시(`ImageHashSubmitted`)가 승인 해시(`ImageHashExpected`)와 일치(`HashMatch`)하고, SBOM에 금지(`unsigned/*`) 컴포넌트가 없어야 `Passed=true`.
- **발사 인가 게이트**: preflight 기록이 없거나(`no_preflight_on_record`) 통과하지 못했으면(`preflight_failed`) 발사 토큰을 거부한다. 즉 **"검증 통과 → 발사" 순서를 강제**한다.

> KUS-FS 전환: 이착륙이 VTOL→활주로/카타펄트라 발사 절차 메타만 조정하며, 결정 표면 구조는 동일하게 재사용.

---

## 3. 발생하는 애플리케이션 로그

PGSE는 FastAPI stub이 **자체 NDJSON**을 떨군다(telemetry-tap 경유 아님 — MAVLink가 아니라 REST 이벤트이므로).

| 무엇 | EventType | 테이블 | 핵심 컬럼 |
|---|---|---|---|
| 펌웨어 조회 | `firmware_query` | **`UAVPgse_CL`** | `UAVId`, `Found`, `ImageHashExpected` |
| 출격 전 검증 | `preflight_check` | **`UAVPgse_CL`** | `HashMatch`, `SbomForbiddenCount`, `Passed` |
| 발사 인가 | `launch_authorize`(거부 포함) | **`UAVPgse_CL`** | `Passed`, `FailReason`, `TokenExpiresAt`, `StatusCode` |
| 정비 기록 | `battery_cycle_logged`/`calibration_completed`/`inspection_signed` | **`UAVMaintenance_CL`** | 정비 이벤트·서명자 |

### 3.1 어떻게 시나리오로 연결되나 — S4 (펌웨어·공급망 변조)
- **펌웨어 해시 변조**: 제출 해시 ≠ 승인 해시 → `preflight_check`에서 `HashMatch=false`, `Passed=false`.
- **공급망 오염**: SBOM에 `unsigned/*` 포함 → `SbomForbiddenCount > 0` → `Passed=false`.
- **위조 출격 시도**: preflight 없이/실패 후 `launch/authorize` 호출 → `FailReason=no_preflight_on_record` 또는 `preflight_failed`, `StatusCode=403/409`.
- **정비 위변조**: `UAVMaintenance_CL`의 서명·캘리브레이션 이력 이상.

---

## 4. 요약

PGSE는 발사·정비·회수·지상전원 장비지만, SOC 관점에서 중요한 것은 **출격 전 결정의 무결성**이다. 그래서 `pgse-stub`(FastAPI)은 물리 장비 대신 **펌웨어 검증·발사 승인·정비 기록의 결정 표면**만 구현한다. 로그는 stub이 직접 떨구는 `UAVPgse_CL`(펌웨어/preflight/launch)·`UAVMaintenance_CL`(정비)이며, 핵심 위협면은 **S4(펌웨어 해시 변조·SBOM 오염·위조 출격)** 다.

다음 상세 문서: (6) +1 위성 / 위성지상국.
