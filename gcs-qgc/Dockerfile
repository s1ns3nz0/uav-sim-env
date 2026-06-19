# gcs-qgc — QGroundControl in headless Xvfb + noVNC (browser-accessible GCS)
# Pinned to linux/amd64 — QGroundControl AppImage v4.4.4 is x86_64-only.
# On ARM hosts (Mac M-series), this builds via Rosetta or QEMU emulation.
FROM --platform=linux/amd64 ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Seoul \
    DISPLAY=:0 \
    QGC_VERSION=v4.4.4

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl wget grep \
        squashfs-tools binutils \
        xvfb x11vnc fluxbox novnc websockify supervisor \
        libgl1-mesa-glx libxkbcommon0 libxkbcommon-x11-0 libpulse0 libnss3 \
        libxcomposite1 libxdamage1 libxrandr2 libxi6 libxcursor1 libxtst6 \
        libfontconfig1 libdbus-1-3 libsm6 libxext6 libxrender1 \
        libasound2 libssl3 \
        libxcb-icccm4 libxcb-image0 libxcb-util1 libxcb-keysyms1 \
        libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 \
        libsdl2-2.0-0 \
        libgstreamer1.0-0 libgstreamer-plugins-base1.0-0 libgstreamer-gl1.0-0 \
        gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-libav \
        libpulse-mainloop-glib0 \
        fonts-noto-cjk \
        tzdata && \
    rm -rf /var/lib/apt/lists/*

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Download QGC AppImage. Do NOT execute it (AppImage bootstrap fails under cross-arch emulation).
# Compute end-of-ELF offset via readelf (e_shoff + e_shnum * e_shentsize) — that's where the
# embedded squashfs blob starts in AppImage type 2.
RUN wget -O /opt/QGroundControl.AppImage \
        "https://github.com/mavlink/qgroundcontrol/releases/download/${QGC_VERSION}/QGroundControl.AppImage" && \
    SHOFF=$(readelf -h /opt/QGroundControl.AppImage | awk '/Start of section headers/ {print $5}') && \
    SHNUM=$(readelf -h /opt/QGroundControl.AppImage | awk '/Number of section headers/ {print $5}') && \
    SHSIZE=$(readelf -h /opt/QGroundControl.AppImage | awk '/Size of section headers/ {print $5}') && \
    OFFSET=$((SHOFF + SHNUM * SHSIZE)) && \
    echo "[gcs-qgc] squashfs offset: $OFFSET (shoff=$SHOFF shnum=$SHNUM shsize=$SHSIZE)" && \
    unsquashfs -d /opt/qgc -o "$OFFSET" /opt/QGroundControl.AppImage > /dev/null && \
    rm /opt/QGroundControl.AppImage

RUN useradd -m -s /bin/bash -u 1000 qgc

COPY missions/ /home/qgc/missions/
RUN chown -R qgc:qgc /home/qgc/missions
COPY supervisord.conf /etc/supervisor/conf.d/qgc.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5900 8080
ENTRYPOINT ["/entrypoint.sh"]
