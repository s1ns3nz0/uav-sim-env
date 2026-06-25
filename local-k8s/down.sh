#!/usr/bin/env bash
# 로컬 클러스터 삭제 (전체 정리).
set -euo pipefail
CLUSTER="${CLUSTER:-uav-sim}"
kind delete cluster --name "$CLUSTER"
echo "삭제됨: $CLUSTER"
