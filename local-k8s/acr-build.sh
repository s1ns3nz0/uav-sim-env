#!/usr/bin/env bash
# 9개 컴포넌트 이미지를 ACR 에서 빌드+push (:v1).
# az acr build = Azure 빌더(amd64)에서 빌드 → 로컬 아키텍처(Apple Silicon arm64)
# 와 무관하고, av(ArduPilot) 같은 무거운 빌드도 클라우드에서 처리.
#
#   bash acr-build.sh dahsimacr2kv7vfcrafu3o
set -euo pipefail

ACR="${1:?usage: acr-build.sh <acr-name>}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"

# "<build-context>:<image-name>" (bash 3.2 호환: 인덱스 배열)
builds=(
  "av-mpd:av"
  "datalink-satcom:datalink-satcom"
  "mps-stub:mps"
  "c4i-stub:c4i"
  "pgse-stub:pgse"
  "weapon-stub:weapon"
  "ti-stub:ti"
  "auth-stub:auth"
  "cyber-posture-stub:cyber-posture"
  "datalink-los:datalink-los"
  "telemetry-tap:telemetry-tap"
  "gcs-qgc:gcs-qgc"
)

for b in "${builds[@]}"; do
  ctx="${b%%:*}"; img="${b##*:}"
  echo "==> az acr build  $img:v1   (context: $ctx)"
  az acr build -r "$ACR" -t "$img:v1" "$REPO/$ctx"
done

echo "완료 — 9개 이미지가 $ACR 에 :v1 로 push 됨."
echo "확인: az acr repository list -n $ACR -o table"
