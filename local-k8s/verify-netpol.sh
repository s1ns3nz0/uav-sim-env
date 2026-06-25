#!/usr/bin/env bash
# 신뢰경계(NetworkPolicy) 동작 검증.
# air 네임스페이스에서 L4 연결을 시도해 "공중→링크만 허용, 공중→지상/c4i 차단"을 확인.
set -uo pipefail
NS=air

echo "==> air 에 임시 테스트 Pod(netcheck) 기동"
kubectl run netcheck -n "$NS" --image=busybox:1.36 --restart=Never \
  --command -- sleep 3600 >/dev/null 2>&1 || true
kubectl wait -n "$NS" --for=condition=Ready pod/netcheck --timeout=60s

probe() {  # 이름 host port 기대(REACHABLE|BLOCKED)
  local name="$1" host="$2" port="$3" expect="$4" res
  if kubectl exec -n "$NS" netcheck -- nc -w 4 "$host" "$port" </dev/null >/dev/null 2>&1; then
    res=REACHABLE
  else
    res=BLOCKED
  fi
  printf "  %-24s %-10s (기대 %-9s) %s\n" "$name" "$res" "$expect" \
    "$([ "$res" = "$expect" ] && echo ✅ || echo ❌ MISMATCH)"
}

echo "==> 신뢰경계 검증 (출발: air)"
probe "air→link  (datalink)" datalink-satcom.link.svc.cluster.local   8800 REACHABLE
probe "air→ground (mps)"     mps-stub.ground.svc.cluster.local        8100 BLOCKED
probe "air→c4i   (c4i)"      c4i-stub.c4i.svc.cluster.local           8200 BLOCKED

echo "==> 정리"
kubectl delete pod -n "$NS" netcheck --wait=false >/dev/null 2>&1 || true
echo "끝. 모두 ✅ 면 '공중→지상 직행 불가, 데이터링크로만' 경계가 강제되는 것."
