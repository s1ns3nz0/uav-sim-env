# UAS 상세 (3) — GDT (Ground Data Terminal)

> **성격**: 소개·학습 문서. 실제 GDT가 무엇인지 → 그 역할을 `uav-sim-env`에서 어떻게 구현했는지 → 거기서 발생하는 애플리케이션 로그가 무엇인지를 정리한다.
> **대상**: KUS-FS급 LOS(C-band) 지상 단말.
> **레포 참조**: `datalink-los/mavlink-router.conf`, `datalink-stats/stats.py`, `docs/sentinel-schemas.md`
> **앞 문서**: (2) Data Link — GDT는 그 LOS 경로에 통합되어 있다.

---

## 0. GDT란

GDT(Ground Data Terminal, 지상 데이터 단말)는 **LOS 링크의 지상 쪽 종단**이다. 공중의 AV가 쏘는 C-band RF를 지상에서 받아(역으로 명령을 송신) **유선/IP로 GCS에 넘겨주는 안테나+모뎀**이다. 한 줄로: "하늘의 전파를 받아 통제소가 알아들을 IP 트래픽으로 바꿔주는 지상 관문".

```
   AV ─── C-band RF (LOS) ───▶ [GDT] ─── 유선/IP ───▶ GCS
        (전파)                  지상안테나·모뎀         통제소
```

> **BLOS의 대응물은 위성지상국(Teleport)** 이다. GDT가 *가시선* 지상 관문이라면, Teleport는 *위성 경유* 지상 관문이다(→ (6) +1 위성/지상국, `datalink-satcom`의 OpenSAND GW).

---

## 1. 실제 GDT의 구성 요소

| 구분 | 실제 요소 | 하는 일 |
|---|---|---|
| 안테나 | 지향성/추적 안테나(C-band) | AV 방향으로 RF 송수신 |
| RF 프런트엔드 | LNA, 송수신기, 변복조기 | RF ↔ 디지털 변환 |
| 종단/인터페이스 | 지상 단말 처리부 | 링크를 GCS로 넘기는 유선/IP 변환 |
| 추적/지향 | 안테나 포인팅(기체 추종) | 가시선 유지 |

> GDT의 SOC 관심사는 물리 안테나가 아니라 **"지상 종단에서의 패킷 흐름과 연결 상태"** 다 — 누가 이 관문에 붙어 있고, 트래픽이 정상적으로 GCS로 넘어가는가.

---

## 2. 오픈소스 구현 — datalink-los에 통합

GDT는 **별도 컨테이너가 없다.** LOS 데이터 링크(`datalink-los`)가 지상 단말 역할을 함께 수행한다 — 즉 GDT는 (2) Data Link의 LOS 경로에 흡수된 "가상 요소"다.

- **지상 종단 = mavlink-router의 GCS-facing 측**: 라우터가 AV(공중, `10.50.0.10:5760`)에서 받은 MAVLink를 **GCS(`10.50.0.30:14550`)로 넘기는 경로**가 곧 "GDT가 전파를 받아 유선으로 GCS에 전달"하는 동작이다.
- **물리 RF는 모사 대상 아님**: 안테나·변복조 같은 물리계층은 다루지 않는다. 대신 그 위의 **패킷 흐름·연결**만 본다(전파 열화 자체는 (2)의 tc netem이 담당).
- **왜 통합인가**: GDT는 독립된 결정 로직이 없는 "통과 지점"이라, 별도 stub을 두기보다 LOS 라우팅에 흡수하는 편이 단순하고 충실하다.

---

## 3. 발생하는 애플리케이션 로그

GDT는 자체 로그를 따로 만들지 않는다. 그 **지상 종단에서의 연결·트래픽 상태**가 `datalink-stats` 사이드카를 통해 드러난다(→ (2) Data Link의 로그 절과 동일 출처).

| 무엇 | 출처 | 테이블 | 핵심 컬럼 |
|---|---|---|---|
| 지상 종단 TCP 연결 스냅샷 | datalink-stats(`ss -tn`) | **`UAVDatalinkConn_CL`** | `State`, `LocalPort`(5760/5790/14550-2), `PeerIp/PeerPort` |
| 지상 링크 헬스(드롭/오류/대역) | datalink-stats | **`UAVDatalink_CL`** | `RxErrors`, `RxDropped`, `Rx/TxBytes` |

- **GDT 관점의 의미**: `UAVDatalinkConn_CL`은 "지금 이 지상 관문에 누가 붙어 있나"를 보여준다 — GCS·tap 같은 정상 피어 외에 **예상치 못한 PeerIp**가 종단에 연결됐는지 감시할 수 있다.

### 3.1 어떻게 시나리오로 연결되나
- **비인가 접속**: `UAVDatalinkConn_CL`에 정상 피어(GCS 10.50.0.30, tap 10.50.0.40) 외 `PeerIp` 출현 → 외부 접속점(5790) 경유 침입 의심(→ A4와 연계).
- **링크 단절/열화**: `UAVDatalink_CL`의 `RxDropped`/`RxErrors` 급증 → 지상 종단에서 본 링크 품질 저하(재밍·거리·장애).

---

## 4. 요약

GDT는 LOS 링크의 **지상 종단(안테나→유선/IP→GCS)** 으로, 본 환경에서는 별도 컨테이너 없이 **`datalink-los`(mavlink-router의 GCS-facing 경로)에 통합**되어 있다. 물리 RF가 아닌 **연결·트래픽 상태**가 관심사라, 로그는 `datalink-stats`가 만드는 `UAVDatalinkConn_CL`(연결 스냅샷)·`UAVDatalink_CL`(링크 헬스)로 나타난다. BLOS의 대응물은 위성지상국(Teleport)이며 (6) +1에서 다룬다.

다음 상세 문서: (4) GCS / MCE.
