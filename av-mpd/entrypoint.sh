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

# Persona param file is env-selectable so one av image can serve multiple
# airframes (MPD quadplane / MUAV fixed-wing). Default keeps MPD behavior.
PERSONA_PARAM="${PERSONA_PARAM:-/home/sitl/persona/mpd_quadplane.parm}"
BOOTSTRAP_SCRIPT="/home/sitl/bootstrap.py"
LOG_DIR="/home/sitl/logs"
mkdir -p "$LOG_DIR"

# Run the post-boot bootstrap in the background. It sleeps until SITL + router
# are up, then forces ARMING_CHECK=0 and MISSION_CURRENT=0 over MAVLink.
if [ -f "$BOOTSTRAP_SCRIPT" ]; then
    (python3 "$BOOTSTRAP_SCRIPT" || true) &
fi

cd /home/sitl/ardupilot

# Launch SITL. MAVProxy is disabled — ArduPilot's TCP server (port 5760) is the
# primary MAVLink endpoint. The datalink-los container connects as a TCP client.
#
# --wipe-eeprom forces SITL to discard any cached eeprom.bin parameters on
# startup, so the MPD persona param file is the single source of truth every
# time the container restarts. Without this, ARMING_CHECK and similar params
# silently revert to whatever the previous session wrote.
# --no-rebuild: 이미지(Dockerfile)에서 이미 `./waf plane` 로 빌드된 arduplane
# 바이너리를 그대로 사용한다. 이게 없으면 sim_vehicle.py 가 시작 시 ArduPilot 을
# 런타임 재컴파일(1289 유닛)하여 컨테이너 메모리 한계를 넘겨 OOMKilled 된다.
exec Tools/autotest/sim_vehicle.py \
    -v "$VEHICLE" \
    -f "$FRAME" \
    -I "$INSTANCE" \
    --no-rebuild \
    --no-mavproxy \
    --wipe-eeprom \
    --custom-location "${HOME_LAT},${HOME_LON},${HOME_ALT},${HOME_HEADING}" \
    --add-param-file "$PERSONA_PARAM"
