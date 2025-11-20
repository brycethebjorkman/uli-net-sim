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

# download OMNeT++
ARG VERSION=6.2.0
ARG O_NAME=omnetpp-$VERSION
RUN wget https://github.com/omnetpp/omnetpp/releases/download/$O_NAME/$O_NAME-linux-x86_64.tgz -O $O_NAME.tgz \
    && tar xf $O_NAME.tgz \
    && rm $O_NAME.tgz

# download INET Framework
ARG VERSION=4.5.4
ARG I_NAME=inet-$VERSION
RUN wget https://github.com/inet-framework/inet/releases/download/v$VERSION/$I_NAME-src.tgz -O $I_NAME.tgz \
    && tar xf $I_NAME.tgz \
    && rm $I_NAME.tgz

# build OMNeT++
WORKDIR /usr/uli-net-sim/$O_NAME
COPY container/install.sh .
RUN chmod +x install.sh
RUN ./install.sh -y --no-gui

# build INET Framework
WORKDIR /usr/uli-net-sim/inet4.5
SHELL ["/bin/bash","-c"]
RUN . ../omnetpp-6.2.0/setenv \
    && . setenv \
    && opp_featuretool enable VisualizationOsg \
    && make makefiles \
    && make -j $(nproc) MODE=release

# download eigen library
WORKDIR /usr/uli-net-sim
RUN wget https://gitlab.com/libeigen/eigen/-/archive/5.0.0/eigen-5.0.0.tar
RUN tar xf eigen-5.0.0.tar \
    && rm eigen-5.0.0.tar

# build uli-net-sim
WORKDIR /usr/uli-net-sim/uav_rid
COPY simulations simulations
COPY src src
WORKDIR /usr/uli-net-sim
COPY container/setenv .
RUN chmod +x setenv
COPY container/build.sh .
RUN chmod +x build.sh
COPY container/run.sh .
RUN chmod +x run.sh
COPY container/rid-one-off.sh .
RUN chmod +x rid-one-off.sh
COPY container/rid-csv-extract.py .
RUN chmod +x rid-csv-extract.py
RUN ./build.sh