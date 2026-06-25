#!/usr/bin/env bash
# Multus 이중 링크 PoC 활성화 — av-muav 에 net-los/net-satcom + netem 차등.
# 사전: up.sh 로 클러스터/av-muav 가 이미 떠 있어야 함.
set -euo pipefail

CLUSTER="${CLUSTER:-uav-sim}"
MULTUS_VERSION="${MULTUS_VERSION:-v4.1.0}"
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "==> [0/4] 표준 CNI 플러그인 설치 (bridge 등 — 보조 네트워크 전제조건)"
bash "$HERE/install-cni-plugins.sh"

echo "==> [1/4] Multus 설치 (보조 인터페이스용 meta-CNI)"
kubectl apply -f "https://raw.githubusercontent.com/k8snetworkplumbingwg/multus-cni/${MULTUS_VERSION}/deployments/multus-daemonset.yml"
kubectl -n kube-system rollout status ds/kube-multus-ds --timeout=180s
kubectl wait --for condition=established --timeout=60s \
  crd/network-attachment-definitions.k8s.cni.cncf.io

echo "==> [2/4] NetworkAttachmentDefinition 적용 (net-los / net-satcom)"
kubectl apply -f "$HERE/multus/nads.yaml"

echo "==> [3/4] av-muav 패치 (이중 인터페이스 + netem) → 롤링 재생성"
kubectl patch statefulset av-muav -n air \
  --patch-file "$HERE/multus/av-muav-duallink-patch.yaml"
kubectl rollout status statefulset/av-muav -n air --timeout=240s

echo "==> [4/4] 검증"
echo "--- 인터페이스 (eth0=calico + los + sat) ---"
kubectl exec -n air av-muav-0 -c sitl -- ip -br addr || true
echo "--- netem qdisc (los=50ms, sat=600ms+loss) ---"
kubectl exec -n air av-muav-0 -c sitl -- tc qdisc show || true
echo "--- RTT 차등: SATCOM gw(~600ms) vs LOS gw(~50ms) ---"
kubectl exec -n air av-muav-0 -c sitl -- ping -c 3 10.80.0.1 || true
kubectl exec -n air av-muav-0 -c sitl -- ping -c 3 10.70.0.1 || true
echo
echo "완료. sat ping 이 los 보다 ~10배 느리면 위성 경로가 실제 망 계층에서 재현된 것."
