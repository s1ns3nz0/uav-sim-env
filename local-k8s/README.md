# local-k8s — AKS 유사 로컬 환경 (kind)

팀원이 노트북에서 **AKS와 최대한 비슷한 환경**으로 KUS-FS 시뮬을 테스트하기 위한 셋업.
compose 로는 검증 불가능한 **신뢰경계(NetworkPolicy)·기체 식별(StatefulSet)·노드풀**을 실제 쿠버네티스에서 재현한다.

> 충실도: **균형** — kind 멀티노드 + Calico(NetworkPolicy 강제) + 노드풀 라벨/taint.
> Multus(이중 링크)·OpenSAND 물리계층은 다음 단계(최대 충실도).

---

## 1. 사전 요구

| 도구 | 설치 |
|---|---|
| Docker | Docker Desktop / Engine |
| kind | `brew install kind` (또는 [공식 설치](https://kind.sigs.k8s.io/docs/user/quick-start/)) |
| kubectl | `brew install kubectl` / `az aks install-cli` |

> 왜 kind 인가: 순수 upstream 쿠버네티스라 **AKS와 동일한 API/오브젝트**를 쓴다. k3s/minikube/Docker Desktop 대비 AKS 충실도·재현성이 높다.

## 2. 기동 / 정리

```bash
cd local-k8s
bash up.sh          # 클러스터 생성 → Calico → 노드풀 라벨 → 이미지 build+load → helm install (uav-sim chart + values-kind.yaml)
bash verify-netpol.sh   # 신뢰경계 검증 (air→ground 차단 / air→link 허용)
bash down.sh        # 전체 삭제
```

첫 `up.sh`는 av 이미지(ArduPilot 빌드)가 최초면 오래 걸린다(이후 캐시 히트). 나머지는 수십 초.

## 3. 확인

```bash
kubectl get nodes -L pool         # 노드풀 라벨(system/sitl/satcom)
kubectl get pods -A -o wide       # NODE 열에서 워크로드가 의도한 노드풀에 떴는지
kubectl get netpol -A             # 네임스페이스별 NetworkPolicy
```

## 4. 무엇이 AKS의 무엇을 모사하는가

| 실제/AKS | 이 로컬 환경 |
|---|---|
| 망 분리(공중/RF링크/지상/C4I/SOC) | namespace `air`·`link`·`ground`·`c4i`·`soc` + NetworkPolicy default-deny |
| "공중→지상은 datalink 링크뿐" | `air`는 `link`로만 egress 허용, `ground` 직행 차단 (`verify-netpol.sh`로 증명) |
| 공군→육군 핸드오프 | `ground → c4i` 단일 방향 허용 |
| AV 1대 = 독립 비행컴퓨터 | `av-muav` **StatefulSet** (안정 식별 `av-muav-0`) |
| 편대 규모 가변 | `kubectl scale statefulset/av-muav -n air --replicas=4` |
| 이종 노드풀(SITL/OpenSAND/시스템) | 워커 노드 `pool=system\|sitl\|satcom` 라벨, satcom 노드 taint |
| SOC out-of-band | `soc` ns 는 각 plane 으로 egress(관측)만, ingress 없음 |
| Azure CNI | Calico (정확히 같진 않으나 NetworkPolicy 동작 동형) |

## 5. 편대 / S3 시연 (클러스터 안)

```bash
# 편대 2대로 스케일
kubectl scale statefulset/av-muav -n air --replicas=2
kubectl get pods -n air            # av-muav-0, av-muav-1

# S3(SATCOM MITM) 주입 — datalink-satcom 으로 포트포워드 후 inject
kubectl -n link port-forward svc/datalink-satcom 8800:8800 &
curl -s -X POST localhost:8800/satcom/inject \
  -H 'content-type: application/json' -d '{"type":"integrity","duration_sec":30}'
kubectl -n link exec deploy/datalink-satcom -- tail -n 2 /var/log/uav-sim-env/satcom.ndjson
```

## 6. 로컬에서 안 되는 것 (의도적 생략)

- **Container Insights / Sentinel** — 관측 백엔드는 Azure 전용. 로컬은 토폴로지·정책 검증까지.
- **관리 ID 기반 AcrPull** — kind 는 `kind load` 로 이미지 주입(레지스트리 불필요).
- **Multus 이중 인터페이스 / OpenSAND 물리계층** — 다음(최대 충실도) 단계.

## 7. 현재 워크로드 / 다음 단계

**배치 완료(매니페스트 존재):**

| ns | 워크로드 |
|---|---|
| air | `av-muav` (StatefulSet) |
| link | `datalink-satcom` |
| ground | `mps-stub`, `pgse-stub`(+ConfigMap), `weapon-stub`, `ti-stub`, `auth-stub`, `cyber-posture-stub` |
| c4i | `c4i-stub` |

**보류(데이터패스 단계에서):** `datalink-los`·`telemetry-tap`·`gcs-qgc` 는 av↔datalink↔tap MAVLink 배선에 의존하므로, Multus 이중 링크 + OpenSAND 단계에서 함께 올린다(standalone 으로는 반쪽). 

**다음 단계:**

1. datalink 데이터패스 배선(av↔datalink↔telemetry-tap 사이드카) + `datalink-los`/`gcs-qgc` 매니페스트.
2. 검증 끝나면 동일 매니페스트를 `dah-sim-aks`(Azure)로 그대로 `kubectl apply`.

## 8. 이중 링크 PoC — Multus + netem (선택)

av-muav 에 LOS/SATCOM 두 RF 링크를 **실제 별도 인터페이스**로 붙이고 링크별 지연/손실을 차등 적용한다. AKS 의 최대 리스크(Multus CNI)를 로컬에서 미리 검증.

```bash
bash enable-dual-link.sh      # Multus 설치 → NAD → av-muav 패치 → 검증
```

- `net-los`(10.70.0.0/24) / `net-satcom`(10.80.0.0/24) NetworkAttachmentDefinition.
- av-muav 가 `eth0`(Calico) + `los` + `sat` 3개 인터페이스 보유.
- netem: `los`=50ms, `sat`=600ms+2% loss → `sat` 게이트웨이 ping 이 ~10배 느림.
- 되돌리기: `kubectl rollout undo statefulset/av-muav -n air` (또는 `bash down.sh` 후 재기동).
