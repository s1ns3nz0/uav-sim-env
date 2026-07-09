#!/usr/bin/env bash
# AKS 유사 로컬 환경 기동 (kind + Calico + 노드풀 라벨 + 워크로드).
# 사전 요구: docker, kind, kubectl.
set -euo pipefail

CLUSTER="${CLUSTER:-uav-sim}"
CALICO_VERSION="${CALICO_VERSION:-v3.27.3}"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

echo "==> [1/5] kind 클러스터 생성 ($CLUSTER)"
if ! kind get clusters | grep -qx "$CLUSTER"; then
  kind create cluster --name "$CLUSTER" --config "$HERE/kind-config.yaml"
else
  echo "    이미 존재 — 건너뜀"
fi

echo "==> [2/5] Calico 설치 (CNI + NetworkPolicy 강제)"
kubectl apply -f "https://raw.githubusercontent.com/projectcalico/calico/${CALICO_VERSION}/manifests/calico.yaml"
echo "    Calico 컨트롤러 준비 대기..."
kubectl -n kube-system rollout status deploy/calico-kube-controllers --timeout=240s || true
kubectl wait --for=condition=Ready nodes --all --timeout=240s || true

echo "==> [3/5] 노드풀 라벨/taint (AKS 노드풀 모사)"
# macOS 기본 bash 3.2 호환 (mapfile/readarray 미지원) — while-read 로 배열 채움.
WORKERS=()
while IFS= read -r _node; do
  [ -n "$_node" ] && WORKERS+=("$_node")
done < <(kubectl get nodes -o name | grep -v control-plane)
kubectl label "${WORKERS[0]}" pool=system  --overwrite
kubectl label "${WORKERS[1]}" pool=sitl    --overwrite
kubectl label "${WORKERS[2]}" pool=satcom  --overwrite
# satcom 노드풀은 전용 — OpenSAND/satcom 워크로드만 toleration 으로 스케줄.
# kubectl taint 는 'node/<name>' 형식을 안 받으므로 'node/' 접두어를 제거한다.
kubectl taint nodes "${WORKERS[2]#node/}" dedicated=satcom:NoSchedule --overwrite

echo "==> [4/5] 로컬 이미지 build + kind load (compose 이미지 재사용)"
# av 이미지는 ArduPilot 빌드라 최초만 오래 걸림(이후 캐시 히트).
build_load() {
  local tag="$1" ctx="$2"
  docker build -t "$tag" "$ctx"
  kind load docker-image "$tag" --name "$CLUSTER"
}
build_load uavsim/av:local              "$REPO/av-mpd"
build_load uavsim/datalink-satcom:local "$REPO/datalink-satcom"
build_load uavsim/datalink-los:local    "$REPO/datalink-los"
build_load uavsim/telemetry-tap:local   "$REPO/telemetry-tap"
build_load uavsim/gcs-qgc:local         "$REPO/gcs-qgc"
build_load uavsim/mps:local             "$REPO/mps-stub"
build_load uavsim/c4i:local             "$REPO/c4i-stub"
# ground 스텁 (C-확장)
build_load uavsim/pgse:local            "$REPO/pgse-stub"
build_load uavsim/weapon:local          "$REPO/weapon-stub"
build_load uavsim/ti:local              "$REPO/ti-stub"
build_load uavsim/auth:local            "$REPO/auth-stub"
build_load uavsim/cyber-posture:local   "$REPO/cyber-posture-stub"
build_load uavsim/sar:local             "$REPO/sar-stub"
# counter-uas (카운터 드론 RF 탐지→근접→자동재밍 시뮬, 송신 없음)
build_load uavsim/counter-uas:local     "$REPO/counter-uas"
# service-audit (Kubernetes Event 기반 파드 생애주기 관측)
build_load uavsim/service-audit:local   "$REPO/service-audit"
# web-stub (IT 계층 공격면 시뮬레이션 — S48~S55)
build_load uavsim/web-stub:local        "$REPO/web-stub"

echo "==> [5/5] Helm install (AKS 와 동일 차트 — values-kind.yaml 오버라이드)"
# AKS = helm + ArgoCD GitOps. kind 도 같은 차트 단일 진실. 이전엔 standalone
# manifests/ 가 별도 트랙이었지만 편대/HOME/SOC 변경이 분기 → kind 측 미반영.
# 지금은 manifests.legacy/ 로 deprecated, helm chart 만 사용.
helm upgrade --install uav-sim "$HERE/helm/uav-sim" \
  -f "$HERE/helm/uav-sim/values.yaml" \
  -f "$HERE/helm/uav-sim/values-kind.yaml" \
  --create-namespace --wait --timeout 5m

echo
echo "완료. 확인:"
echo "  kubectl get ns"
echo "  kubectl get pods -A -o wide        # NODE 열로 노드풀 배치 확인"
echo "  bash $HERE/verify-netpol.sh         # 신뢰경계(air→ground 차단) 검증"
echo "  bash $HERE/down.sh                  # 클러스터 종료"
