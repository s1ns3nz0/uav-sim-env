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
        squashfs-tools \
        xvfb x11vnc fluxbox novnc websockify supervisor \
        libgl1-mesa-glx libxkbcommon0 libxkbcommon-x11-0 libpulse0 libnss3 \
        libxcomposite1 libxdamage1 libxrandr2 libxi6 libxcursor1 libxtst6 \
        libfontconfig1 libdbus-1-3 libsm6 libxext6 libxrender1 \
        libasound2 libssl3 \
        fonts-noto-cjk \
        tzdata && \
    rm -rf /var/lib/apt/lists/*

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Download QGC AppImage. Do NOT execute it (AppImage bootstrap fails under cross-arch emulation).
# Extract the embedded squashfs blob directly: find 'hsqs' magic offset, then unsquashfs.
RUN wget -O /opt/QGroundControl.AppImage \
        "https://github.com/mavlink/qgroundcontrol/releases/download/${QGC_VERSION}/QGroundControl.AppImage" && \
    OFFSET=$(grep -aoP '\x68\x73\x71\x73' -b /opt/QGroundControl.AppImage | head -1 | cut -d: -f1) && \
    echo "[gcs-qgc] squashfs offset detected: $OFFSET" && \
    unsquashfs -d /opt/qgc -o "$OFFSET" /opt/QGroundControl.AppImage > /dev/null && \
    rm /opt/QGroundControl.AppImage

COPY missions/ /root/missions/
COPY supervisord.conf /etc/supervisor/conf.d/qgc.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5900 8080
ENTRYPOINT ["/entrypoint.sh"]
