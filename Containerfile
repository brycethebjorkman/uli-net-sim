FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive 

RUN apt-get update && apt-get install --yes --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    git \
    python3 \
    python3-pip \
    software-properties-common \
    wget \
    xz-utils \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# install OMNeT++ dependencies
RUN apt-get update && apt-get install --yes --no-install-recommends \
    bison \
    ccache \
    clang \
    doxygen \
    flex \
    gawk \
    gdb \
    graphviz \
    libdw-dev \
    libxml2-dev \
    lld \
    lldb \
    pkg-config \
    python3-dev \
    python3-venv \
    xdg-utils \
    zlib1g-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# install OMNeT++ and INET graphical dependencies
RUN apt-get update && apt-get install --yes --no-install-recommends \
    qt6-base-dev \
    qt6-base-dev-tools \
    qmake6 \
    libqt6svg6 \
    qt6-wayland \
    libwebkit2gtk-4.1-0 \
    libopenscenegraph-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/uli-net-sim

# download OMNeT++ (must match opp_msgtool / *_m.h MSGC_VERSION in the repo — 6.3.x)
ARG VERSION=6.3.0
ARG O_NAME=omnetpp-$VERSION
RUN wget https://github.com/omnetpp/omnetpp/releases/download/$O_NAME/$O_NAME-linux-x86_64.tgz -O $O_NAME.tgz \
    && tar xf $O_NAME.tgz \
    && rm $O_NAME.tgz

# download INET Framework (extracted folder must be inet4.5 for build scripts)
ARG INET_VERSION=4.5.4
RUN wget https://github.com/inet-framework/inet/releases/download/v${INET_VERSION}/inet-${INET_VERSION}-src.tgz -O inet-src.tgz \
    && tar xf inet-src.tgz \
    && rm inet-src.tgz \
    && if [ ! -d inet4.5 ] && [ -d inet-${INET_VERSION} ]; then mv inet-${INET_VERSION} inet4.5; fi \
    && test -d inet4.5

# build OMNeT++
WORKDIR /usr/uli-net-sim/$O_NAME
COPY scripts/install.sh .
RUN chmod +x install.sh
RUN ./install.sh -y --no-gui

# build INET Framework
WORKDIR /usr/uli-net-sim/inet4.5
SHELL ["/bin/bash","-c"]
RUN . ../omnetpp-6.3.0/setenv \
    && . setenv \
    && opp_featuretool enable VisualizationOsg \
    && make makefiles \
    && make -j $(nproc) MODE=release

# download eigen library
WORKDIR /usr/uli-net-sim
RUN wget https://gitlab.com/libeigen/eigen/-/archive/5.0.0/eigen-5.0.0.tar
RUN tar xf eigen-5.0.0.tar \
    && rm eigen-5.0.0.tar

# Make OMNeT++/INET env available globally in every login shell
COPY scripts/omnetpp-env.sh /etc/profile.d/omnetpp-env.sh

# Python venv outside project tree so bind-mounting the repo for batch runs
# still uses pyarrow/pytest (see README Docker section).
COPY requirements-docker.txt /tmp/requirements-docker.txt
RUN python3 -m venv /opt/uli-venv \
    && /opt/uli-venv/bin/pip install --upgrade pip \
    && /opt/uli-venv/bin/pip install -r /tmp/requirements-docker.txt

ENV ULI_PYTHON=/opt/uli-venv/bin/python3
# opp_scavetool (vec2parquet) must be on PATH — non-login shells do not source profile.d
ENV PATH="/usr/uli-net-sim/omnetpp-${VERSION}/bin:/opt/uli-venv/bin:${PATH}"
ENV PYTHONPATH="/usr/uli-net-sim/uav_rid"

# build uli-net-sim (repository root -> /usr/uli-net-sim/uav_rid)
WORKDIR /usr/uli-net-sim/uav_rid
COPY . .

RUN chmod +x scripts/*.sh scripts/run.sh datagen/*.py 2>/dev/null || true

ENV INET_ROOT=/usr/uli-net-sim/inet4.5
RUN ./scripts/build.sh

WORKDIR /usr/uli-net-sim/uav_rid
CMD ["/bin/bash"]