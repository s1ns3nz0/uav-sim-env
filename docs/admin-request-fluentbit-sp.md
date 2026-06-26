# 🔐 관리자 요청 — Fluent Bit 서비스 프린시플 (AKS → Sentinel 일원화)

> ⏱️ 권한 있는 관리자(Entra 앱 등록 가능자)가 **1회 수행**, 약 5분.
> 일반 사용자 계정은 테넌트 정책상 앱 등록(SP 생성)이 막혀 있어 이 작업만 대신 필요합니다.

## 1. 배경 (왜 필요한가)

AKS 클러스터(`dah-sim-aks`)에서 도는 UAV SOC 시뮬의 텔레메트리(NDJSON)를 Microsoft Sentinel 커스텀 테이블(`UAVSatcomLink_CL` 등)로 보내려면, 클러스터 안의 Fluent Bit가 **Azure Logs Ingestion API**에 인증해야 합니다. 이 인증은 **서비스 프린시플(client_id + client secret)** 이 필요한데, 요청자 계정은 앱 등록 권한이 없어 막혀 있습니다(`az ad app create` → *Insufficient privileges*). 그래서 관리자 1회 작업이 필요합니다.

## 2. 관리자가 할 일 (요약)

1. 서비스 프린시플 `uav-fluentbit-sp` 생성
2. 역할 **Monitoring Metrics Publisher** 를 리소스 그룹 **`dah-data-rg`** 범위로 부여
3. **appId / client secret(password) / tenant** 세 값을 요청자에게 전달

## 3. 명령어 (az CLI — 한 번에)

```bash
az ad sp create-for-rbac --name uav-fluentbit-sp \
  --role "Monitoring Metrics Publisher" \
  --scopes "$(az group show -n dah-data-rg --query id -o tsv)" \
  --years 1 \
  -o json
```

출력의 `appId` / `password` / `tenant` 세 값이 필요합니다. **`password`(client secret)는 이때만 표시**되니 꼭 복사해 주세요.

## 4. 전달받을 값

| 값 | 의미 | 비고 |
|---|---|---|
| `appId` | client_id | 공개 가능 |
| `password` | client secret | **민감** — 안전한 채널로 |
| `tenant` | 테넌트 ID | — |

## 5. 보안 메모

- **최소권한**: 범위를 `dah-data-rg`로 한정. `Monitoring Metrics Publisher`는 로그 *발행*만 가능하며 데이터 읽기/삭제 권한은 없습니다.
- client secret은 평문(이메일/메신저) 대신 안전한 경로로. 요청자는 이 값을 **git에 올리지 않고 Kubernetes Secret에만** 저장합니다.
- 만료 1년(`--years 1`) 설정됨. 만료 시 `az ad app credential reset`으로 갱신.

## 6. 요청자(이후 작업, 참고)

`appId`를 Helm values에 넣고, secret을 `kubectl`로 Kubernetes Secret(`fluentbit-azure`)에 저장한 뒤 GitOps 배포 → AKS 텔레메트리가 Sentinel로 흐릅니다. (관리자 작업 범위 밖)

---

참고 — 구독: `b7acdba2-f2d6-4ff5-a059-008b20432f79` · 데이터 RG: `dah-data-rg` · DCE: `dah-data-dce` · 대상 테이블: `UAVSatcomLink_CL` 외 `UAV*_CL`.
관리자 작업이 어려우면 요청자가 **워크로드 ID 기반 우회로(자체 log shipper)** 로 진행 가능 — 그 경우 이 SP 요청은 불필요.
