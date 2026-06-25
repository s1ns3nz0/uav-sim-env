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
build_load uavsim/mps:local             "$REPO/mps-stub"
build_load uavsim/c4i:local             "$REPO/c4i-stub"

echo "==> [5/5] 매니페스트 적용 (namespaces → NetworkPolicy → 워크로드)"
kubectl apply -f "$HERE/manifests/"

echo
echo "완료. 확인:"
echo "  kubectl get ns"
echo "  kubectl get pods -A -o wide        # NODE 열로 노드풀 배치 확인"
echo "  bash $HERE/verify-netpol.sh         # 신뢰경계(air→ground 차단) 검증"
