# DEPRECATED — standalone manifests (옛 kind 트랙)

이 디렉토리는 **2026-06-27 이전** 의 kind 환경 standalone yaml.

이후 helm chart (`local-k8s/helm/uav-sim/`) 가 AKS+kind 단일 진실이 됨.
kind 도 `up.sh` 에서 `helm install -f values-kind.yaml` 으로 chart 사용.

이 디렉토리의 yaml 들은 **편대(F1) / 안흥 HOME / SOC 일원화(H3b) /
gcs-qgc satcom 이전 / Fluent Bit rewrite_tag** 등 후속 변경이 **반영되어 있지 않음**.
참고용으로만 보존. apply 하지 말 것.
