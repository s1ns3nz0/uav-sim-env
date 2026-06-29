#!/usr/bin/env bash
# gcs-qgc entrypoint — start supervisord (Xvfb + fluxbox + x11vnc + noVNC + QGC)
set -euo pipefail

echo "[gcs-qgc] noVNC available at http://localhost:8080/vnc.html (nginx → websockify:8081 → x11vnc:5900)"
echo "[gcs-qgc] VNC raw at localhost:5900 (no password, bypasses nginx — not in UAVGcsAccess_CL)"
echo "[gcs-qgc] nginx access log → stdout in NDJSON (UAVGcsAccess_CL schema, marker=Transport)"
echo "[gcs-qgc] QGC will auto-discover MAVLink UDP on port ${MAVLINK_IN_PORT:-14551}"

exec /usr/bin/supervisord -c /etc/supervisor/conf.d/qgc.conf
