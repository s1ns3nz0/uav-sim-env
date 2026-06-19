# gcs-qgc — QGroundControl in headless Xvfb + noVNC (browser-accessible GCS)
# Pinned to linux/amd64 — QGroundControl AppImage v4.4.4 is x86_64-only.
# On ARM hosts (Mac M-series), this builds via Rosetta or QEMU emulation.
FROM --platform=linux/amd64 ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Seoul \
    DISPLAY=:0 \
    QGC_VERSION=v4.4.4

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl wget \
        xvfb x11vnc fluxbox novnc websockify supervisor \
        libgl1-mesa-glx libxkbcommon0 libxkbcommon-x11-0 libpulse0 libnss3 \
        libxcomposite1 libxdamage1 libxrandr2 libxi6 libxcursor1 libxtst6 \
        libfontconfig1 libdbus-1-3 libsm6 libxext6 libxrender1 \
        libasound2 libssl3 \
        fonts-noto-cjk \
        tzdata && \
    rm -rf /var/lib/apt/lists/*

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Download QGroundControl AppImage (Linux x86_64)
RUN wget -O /opt/QGroundControl.AppImage \
        "https://github.com/mavlink/qgroundcontrol/releases/download/${QGC_VERSION}/QGroundControl.AppImage" && \
    chmod +x /opt/QGroundControl.AppImage && \
    cd /opt && ./QGroundControl.AppImage --appimage-extract > /dev/null && \
    mv squashfs-root /opt/qgc && \
    rm /opt/QGroundControl.AppImage

COPY missions/ /root/missions/
COPY supervisord.conf /etc/supervisor/conf.d/qgc.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5900 8080
ENTRYPOINT ["/entrypoint.sh"]
