#!/usr/bin/env bash
# kind 노드에 표준 CNI 레퍼런스 플러그인(bridge/host-local/loopback 등) 설치.
# Multus 보조 네트워크(net-los/net-satcom)가 'bridge' 플러그인을 필요로 하는데,
# disableDefaultCNI + Calico 조합에서는 /opt/cni/bin 에 빠져 있어 직접 넣어준다.
set -euo pipefail

CLUSTER="${CLUSTER:-uav-sim}"
CNI_VERSION="${CNI_VERSION:-v1.5.1}"

# 노드 아키텍처 감지 (Intel Mac=amd64 / Apple Silicon=arm64)
CP="$(kind get nodes --name "$CLUSTER" | head -1)"
MACH="$(docker exec "$CP" uname -m)"
case "$MACH" in
  x86_64)        ARCH=amd64 ;;
  aarch64|arm64) ARCH=arm64 ;;
  *) echo "unknown arch: $MACH" >&2; exit 1 ;;
esac
echo "노드 아키텍처: $MACH → $ARCH"

TARBALL="$(mktemp -d)/cni.tgz"
URL="https://github.com/containernetworking/plugins/releases/download/${CNI_VERSION}/cni-plugins-linux-${ARCH}-${CNI_VERSION}.tgz"
echo "다운로드: $URL"
curl -fsSL -o "$TARBALL" "$URL"

EXTRACT="$(mktemp -d)"
tar -xzf "$TARBALL" -C "$EXTRACT"

for n in $(kind get nodes --name "$CLUSTER"); do
  echo "→ $n:/opt/cni/bin 에 복사"
  docker exec "$n" mkdir -p /opt/cni/bin
  docker cp "$EXTRACT/." "$n:/opt/cni/bin/"
done

rm -rf "$EXTRACT" "$(dirname "$TARBALL")"
echo "완료 — bridge/host-local 등 표준 CNI 플러그인 설치됨."
