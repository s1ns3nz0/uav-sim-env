WORKSPACE_GUID=$(az monitor log-analytics workspace show -g dah-data-rg -n dah-data-law --query customerId -o tsv)
echo "WORKSPACE_GUID=$WORKSPACE_GUID"

TABLES="UAVWeapon_CL UAVThreatIntel_CL UAVOpAudit_CL UAVMaintenance_CL UAVDatalinkConn_CL UAVResourceMetrics_CL"
INTERVAL=30
STATE=$(mktemp)

echo "감시 시작 (${INTERVAL}초 주기, 중지: Ctrl+C)"
while true; do
  echo "──────── $(date '+%H:%M:%S') ────────"
  for t in $TABLES; do
    n=$(az monitor log-analytics query -w "$WORKSPACE_GUID" \
          --analytics-query "$t | count" --timespan PT24H -o tsv 2>/dev/null \
          | head -1 | cut -f1)
    n=${n:-ERR}
    prev=$(grep "^$t " "$STATE" 2>/dev/null | cut -d' ' -f2)
    if [ -n "$prev" ] && [ "$n" != "$prev" ]; then
      printf "  %-22s %s  ▲ (%s -> %s)\n" "$t" "$n" "$prev" "$n"
    else
      printf "  %-22s %s\n" "$t" "$n"
    fi
    grep -v "^$t " "$STATE" > "$STATE.tmp" 2>/dev/null; mv "$STATE.tmp" "$STATE"
    echo "$t $n" >> "$STATE"
  done
  sleep $INTERVAL
done
