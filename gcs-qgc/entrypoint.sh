#!/usr/bin/env bash
# gcs-qgc entrypoint — start supervisord (Xvfb + fluxbox + x11vnc + noVNC + QGC)
set -euo pipefail

echo "[gcs-qgc] noVNC available at http://localhost:8080/vnc.html"
echo "[gcs-qgc] VNC raw at localhost:5900 (no password)"
echo "[gcs-qgc] QGC will auto-discover MAVLink UDP on port ${MAVLINK_IN_PORT:-14551}"

exec /usr/bin/supervisord -c /etc/supervisor/conf.d/qgc.conf
