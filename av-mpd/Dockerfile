# ArduPilot SITL + Gazebo Garden, MPD persona (Quadplane VTOL)
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Seoul \
    USER=sitl \
    ARDUPILOT_BRANCH=Plane-4.5 \
    GZ_VERSION=garden

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl wget gnupg lsb-release sudo \
        git build-essential python3 python3-pip python3-dev python3-venv \
        python3-numpy python3-pexpect python3-future python3-lxml \
        libxml2-dev libxslt1-dev libtool automake autoconf \
        ccache g++ gcc rsync openssh-client \
        net-tools iproute2 iputils-ping \
        tzdata locales && \
    rm -rf /var/lib/apt/lists/*

RUN locale-gen en_US.UTF-8 && \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Gazebo Garden repo
RUN wget https://packages.osrfoundation.org/gazebo.gpg -O /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg] http://packages.osrfoundation.org/gazebo/ubuntu-stable $(lsb_release -cs) main" \
        > /etc/apt/sources.list.d/gazebo-stable.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends gz-garden && \
    rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash -u 1000 $USER && \
    echo "$USER ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers
USER $USER
WORKDIR /home/$USER

# Clone ArduPilot (shallow)
RUN git clone --recursive --depth 1 --branch $ARDUPILOT_BRANCH \
        https://github.com/ArduPilot/ardupilot.git

WORKDIR /home/$USER/ardupilot
RUN Tools/environment_install/install-prereqs-ubuntu.sh -y

# Add waf to PATH and build SITL ArduPlane
ENV PATH="/home/$USER/.local/bin:/home/$USER/ardupilot/Tools/autotest:${PATH}"
RUN bash -lc "./waf configure --board sitl && ./waf plane"

# MPD persona files
COPY --chown=$USER:$USER persona/ /home/$USER/persona/
COPY --chown=$USER:$USER world/ /home/$USER/world/
COPY --chown=$USER:$USER bootstrap.py /home/$USER/bootstrap.py
COPY --chown=$USER:$USER entrypoint.sh /home/$USER/entrypoint.sh
RUN sudo chmod +x /home/$USER/entrypoint.sh

EXPOSE 5760
ENTRYPOINT ["/home/sitl/entrypoint.sh"]
