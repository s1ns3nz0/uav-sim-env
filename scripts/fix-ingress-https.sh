#!/usr/bin/env bash
# fix-ingress-https.sh — sim.pollak.store HTTPS (AKS ingress LB) 진단 + 시도 + 복구.
#
# 목적: ingress-nginx LB 외부 트래픽이 안 통하는 문제를 자동 진단하고, auto-IP 재생성을
#       시도하며, 안 되면 동작하는 HTTP IP로 DNS 복구 명령을 출력한다.
# 사용: bash scripts/fix-ingress-https.sh            # 진단만 (mutation 없음)
#       bash scripts/fix-ingress-https.sh --try-fix  # auto-IP 재생성까지 시도
#       bash scripts/fix-ingress-https.sh --revert   # 도메인을 동작 HTTP IP로 즉시 복구
set -uo pipefail

SIM_RG=dah-sim-rg
CLUSTER=dah-sim-aks
DNS_RG=dah-shared-rg
ZONE=pollak.store
HOST=sim
GOOD_HTTP_IP=20.249.193.191        # gcs-qgc-lb (HTTP, 동작 확인됨)
INGRESS_NS=ingress-nginx
INGRESS_SVC=ingress-nginx-controller
MODE="${1:-diagnose}"

b(){ printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
NODE_RG=$(az aks show -g "$SIM_RG" -n "$CLUSTER" --query nodeResourceGroup -o tsv)

if [ "$MODE" = "--revert" ]; then
  b "도메인을 동작 HTTP IP($GOOD_HTTP_IP)로 복구"
  CUR=$(az network dns record-set a show -g "$DNS_RG" -z "$ZONE" -n "$HOST" --query "ARecords[].ipv4Address" -o tsv)
  az network dns record-set a add-record -g "$DNS_RG" -z "$ZONE" -n "$HOST" -a "$GOOD_HTTP_IP" -o none || true
  for ip in $CUR; do
    [ "$ip" != "$GOOD_HTTP_IP" ] && az network dns record-set a remove-record -g "$DNS_RG" -z "$ZONE" -n "$HOST" -a "$ip" -o none || true
  done
  echo "복구됨. sim.pollak.store -> $GOOD_HTTP_IP (HTTP :8080). 차트 values-aks.yaml 의 ingress.enabled=false 로 끄고 push 권장."
  exit 0
fi

b "1) 컨트롤러 Pod"
kubectl -n "$INGRESS_NS" get pods -o wide

b "2) 컨트롤러 내부 응답 (404 default backend = 정상)"
kubectl -n "$INGRESS_NS" run nginxcheck --rm -i --restart=Never --image=busybox --timeout=30s -- \
  wget -qS -O- --timeout=5 "http://$INGRESS_SVC.$INGRESS_NS.svc/" 2>&1 | head -8 || true

b "3) 서비스 / EXTERNAL-IP / externalTrafficPolicy"
kubectl -n "$INGRESS_NS" get svc "$INGRESS_SVC" -o wide
EXTIP=$(kubectl -n "$INGRESS_NS" get svc "$INGRESS_SVC" -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "EXTIP=$EXTIP  policy=$(kubectl -n "$INGRESS_NS" get svc "$INGRESS_SVC" -o jsonpath='{.spec.externalTrafficPolicy}')"

b "4) 외부 접속 테스트 ($EXTIP:80)"
curl -sS -m 8 -o /dev/null -w "http_code=%{http_code} time=%{time_total}s\n" "http://$EXTIP/" || echo "  -> 외부 timeout/실패"

b "5) LB 룰 + 프론트엔드 + 헬스 프로브 (node RG=$NODE_RG)"
az network lb rule list  -g "$NODE_RG" --lb-name kubernetes --query "[].{name:name,fe:frontendPort,be:backendPort,probe:probe.id}" -o table 2>/dev/null
echo "--- frontends ---"
az network lb frontend-ip list -g "$NODE_RG" --lb-name kubernetes --query "[].{name:name,pip:publicIpAddress.id}" -o table 2>/dev/null
echo "--- probes ---"
az network lb probe list -g "$NODE_RG" --lb-name kubernetes --query "[].{name:name,proto:protocol,port:port,path:requestPath}" -o table 2>/dev/null
echo "--- backend pool 멤버 수 ---"
az network lb address-pool list -g "$NODE_RG" --lb-name kubernetes --query "[].{name:name,members:length(loadBalancerBackendAddresses)}" -o table 2>/dev/null

b "6) NSG 인바운드 80/443"
NSG=$(az network nsg list -g "$NODE_RG" --query "[0].name" -o tsv)
az network nsg rule list -g "$NODE_RG" --nsg-name "$NSG" \
  --query "[?direction=='Inbound'].{name:name,ports:destinationPortRange,ranges:destinationPortRanges,access:access,prio:priority}" -o table 2>/dev/null

b "7) cert-manager challenge 상태"
kubectl -n ground get certificate,certificaterequest,order,challenge 2>/dev/null || true

if [ "$MODE" = "--try-fix" ]; then
  b "FIX: 고정IP 강제 제거 → AKS auto-IP 재와이어링"
  kubectl -n "$INGRESS_NS" annotate svc "$INGRESS_SVC" \
    service.beta.kubernetes.io/azure-pip-name- \
    service.beta.kubernetes.io/azure-load-balancer-resource-group- 2>/dev/null || true
  kubectl -n "$INGRESS_NS" patch svc "$INGRESS_SVC" --type merge -p '{"spec":{"loadBalancerIP":null}}' || true
  echo "재와이어링 대기(60s)..."; sleep 60
  NEWIP=$(kubectl -n "$INGRESS_NS" get svc "$INGRESS_SVC" -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
  echo "NEWIP=$NEWIP"
  CODE=$(curl -sS -m 8 -o /dev/null -w "%{http_code}" "http://$NEWIP/" || echo "000")
  echo "외부 테스트: http_code=$CODE"
  if [ "$CODE" != "000" ] && [ -n "$NEWIP" ]; then
    echo "✅ LB 외부 통함. 다음으로 DNS 를 $NEWIP 로 돌리면 cert 발급됨:"
    echo "   az network dns record-set a add-record    -g $DNS_RG -z $ZONE -n $HOST -a $NEWIP"
    echo "   az network dns record-set a remove-record -g $DNS_RG -z $ZONE -n $HOST -a 20.194.99.116"
  else
    echo "❌ auto-IP 도 외부 timeout. LB/프로브 더 파보거나(§3 후보) HTTPS 접고 복구:"
    echo "   bash scripts/fix-ingress-https.sh --revert"
  fi
fi

b "끝. 판단: 컨트롤러 내부 404 OK + 외부 timeout 이면 = LB 외부 경로 문제(§5의 프로브/백엔드 확인 또는 --try-fix)."
echo "도메인이 깨진 IP를 가리키는 동안 GCS 접속 불가 → 빨리 못 고치면: bash scripts/fix-ingress-https.sh --revert"
