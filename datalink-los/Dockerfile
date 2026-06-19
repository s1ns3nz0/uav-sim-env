# datalink-los — LOS RF link emulation (mavlink-router + tc netem)
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Seoul

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git build-essential \
        meson ninja-build pkg-config \
        python3 python3-pip \
        iproute2 iputils-ping net-tools tcpdump \
        tzdata && \
    rm -rf /var/lib/apt/lists/*

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Build mavlink-router from source (official)
RUN git clone --recursive --depth 1 https://github.com/mavlink-router/mavlink-router.git /tmp/mavlink-router && \
    cd /tmp/mavlink-router && \
    meson setup build . && \
    ninja -C build && \
    ninja -C build install && \
    ldconfig && \
    rm -rf /tmp/mavlink-router

COPY mavlink-router.conf /etc/mavlink-router/main.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 14550/udp 14551/udp 14552/udp
ENTRYPOINT ["/entrypoint.sh"]
