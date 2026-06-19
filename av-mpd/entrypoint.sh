#!/usr/bin/env bash
# av-mpd entrypoint — launch ArduPilot SITL (ArduPlane Quadplane) with MPD persona
set -euo pipefail

VEHICLE="${VEHICLE:-ArduPlane}"
FRAME="${FRAME:-quadplane}"
INSTANCE="${INSTANCE:-0}"
HOME_LAT="${HOME_LAT:-37.5326}"
HOME_LON="${HOME_LON:-127.0246}"
HOME_ALT="${HOME_ALT:-50}"
HOME_HEADING="${HOME_HEADING:-0}"
MAVLINK_OUT_HOST="${MAVLINK_OUT_HOST:-datalink-los}"
MAVLINK_OUT_PORT="${MAVLINK_OUT_PORT:-14550}"

PERSONA_PARAM="/home/sitl/persona/mpd_quadplane.parm"
LOG_DIR="/home/sitl/logs"
mkdir -p "$LOG_DIR"

cd /home/sitl/ardupilot

# Launch SITL. MAVProxy is disabled — ArduPilot's TCP server (port 5760) is the
# primary MAVLink endpoint. The datalink-los container connects as a TCP client.
exec Tools/autotest/sim_vehicle.py \
    -v "$VEHICLE" \
    -f "$FRAME" \
    -I "$INSTANCE" \
    --no-mavproxy \
    --custom-location "${HOME_LAT},${HOME_LON},${HOME_ALT},${HOME_HEADING}" \
    --add-param-file "$PERSONA_PARAM"
