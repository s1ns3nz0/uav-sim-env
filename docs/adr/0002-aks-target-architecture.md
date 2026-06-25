# ADR 0002 — AKS 타깃 아키텍처 (실제 UAV 체계 모사)

- **상태**: Proposed
- **일자**: 2026-06-23
- **관련**: ADR 0001(편대+SATCOM 런타임 AKS 이전 결정), `docs/opensource-uas-mapping.md`, `docs/uas-detail-*`

---

## 배경 (Context)

ADR 0001에서 편대+SATCOM 확장 런타임을 **AKS 이전**으로 결정했다. 본 ADR은 그 AKS 구현을 **"실제 UAS 체계에 최대한 가깝게"** 만들기 위한 타깃 아키텍처 아이디어를 정리한다.

핵심 설계 원칙: 실제 UAS의 **① 신뢰 경계(망 분리) ② 기체별 독립 식별 ③ 이종 컴퓨팅 ④ 제약된 RF/위성 링크**를 쿠버네티스 1급 객체로 그대로 모사한다.

---

## 실제 특성 → AKS 매핑

| 실제 UAV 체계 특성 | AKS 구현 |
| --- | --- |
| 망 분리(공중 버스 / RF링크 / 지상통제 / C4I / 공군↔육군) | namespace + NetworkPolicy(기본 deny): `air`·`link`·`ground`·`c4i`·`soc` 분리. 공중→지상은 datalink 서비스로만 |
| 기체마다 독립된 비행 컴퓨터 | AV 1대 = Pod 1개 (StatefulSet, 안정 식별 `MUAV-001..N`), 각자 워크로드 ID·네트워크 네임스페이스 |
| 편대 규모 가변 | StatefulSet replica 수 = 편대 규모(선언적 스케일) |
| SITL=CPU, OpenSAND=특수네트워크, Gazebo=GPU | 노드풀 분리 — CPU 최적화(SITL)/전용(OpenSAND, privileged)/GPU(시각화). taint·toleration·nodeSelector |
| LOS + SATCOM 이중 RF 링크 | Multus CNI 다중 인터페이스 — AV Pod에 `net-los`·`net-satcom` 부여, 링크별 지연·손실 주입 |
| 링크 열화·재밍 | Cilium 대역폭/지연 정책 또는 netem 사이드카로 인터페이스별 품질 제어 |
| 운영자 인증·2인 통제·공급망 무결성 | Pod Security(restricted) + 이미지 서명(cosign)+승인제어(Kyverno/Ratify) + Key Vault CSI |

---

## 핵심 발상

### (a) UAV 커스텀 리소스 + Fleet 오퍼레이터
`kind: UAV` CRD를 정의("기체 ID·persona·페이로드·링크 구성" 선언)하고, 오퍼레이터가 이를 보고 SITL Pod + persona + 링크 인터페이스를 자동 생성·정합화. 편대 운용을 `kubectl apply`로 선언 — 가장 체계적·확장적. kagent와 자연스럽게 결합.

### (b) Multus로 RF 링크를 진짜 별도 망으로
현재 docker bridge 하나에 얹힌 구조를, AKS에서 AV에 LOS·SATCOM 인터페이스를 물리적으로 분리. "위성 경로 MITM(S3)"·"LOS 재밍"이 실제 망 계층에서 재현. OpenSAND는 SATCOM 인터페이스 전용 노드풀(privileged)에 배치.

### (c) 신뢰 경계 = NetworkPolicy로 강제
실제 체계의 정수: "공중→지상 경로는 RF 링크뿐". `air` Pod가 `ground`로 직접 못 가고 **datalink 게이트웨이를 통해서만** 통신하도록 default-deny + 화이트리스트. 공군→육군 핸드오프도 별도 네임스페이스(또는 별도 클러스터) 사이 단일 게이트웨이로 모델링 → SOC가 감시할 조직 경계가 드러남.

---

## 관측·SOC 평면 분리
telemetry-tap을 AV 사이드카 또는 DaemonSet으로, 컨테이너 로그는 Container Insights/Fluent Bit → DCR → Log Analytics/Sentinel. **SOC 평면(LangGraph on kagent)은 시뮬 UAS 평면과 다른 네임스페이스**로 두어 out-of-band 관제 구조 모사.

## 현실성·실패 주입
liveness/readiness probe = 기체 건전성, PDB = 가용성. **링크 손실 = datalink Pod kill / netem 100% loss → 기체 failsafe(RTL) 유발** 같은 chaos 실험으로 실제 비상거동 검증.

## 운용 — GitOps
Helm 차트(컴포넌트별) + ArgoCD/Flux 선언적·감사가능 배포. (a) Fleet 오퍼레이터와 결합 시 "편대 구성 변경 = Git PR".

---

## 결정 (Decision)
AKS 타깃 아키텍처를 위 원칙(신뢰 경계·기체별 식별·이종 노드풀·다중 인터페이스 링크)으로 잡는다. 단계는 아래 단계화를 따른다.

**MVP 코어**: namespace 분리 + NetworkPolicy(default-deny) + AV=StatefulSet + 노드풀 분리.
**고급**: Multus 이중 링크, UAV CRD/Fleet 오퍼레이터, 멀티클러스터 조직 분리, 이미지 서명·승인제어.

---

## 결과 (Consequences)
- **긍정**: 신뢰 경계·편대·링크가 실제 체계와 동형 → SOC 위협면(S3·A4·핸드오프·횡적확산)이 현실적으로 재현. 선언적 운용·감사성 확보.
- **부담/리스크**: Multus + OpenSAND-on-k8s가 최대 난점(privileged·tun/tap·CNI) → 별도 PoC 선행. CRD/오퍼레이터 개발 비용. 멀티클러스터는 운영 복잡도↑(필요 시 단계 보류).

## 후속 작업 (Follow-ups)
- Multus + OpenSAND 노드풀 PoC.
- `kind: UAV` CRD 스키마 초안 + 오퍼레이터 reconcile 설계.
- namespace/NetworkPolicy 토폴로지(air/link/ground/c4i/soc) 정의.
- 노드풀 사이징(SITL CPU / OpenSAND / GPU) 산정.
