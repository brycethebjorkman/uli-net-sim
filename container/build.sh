#!/usr/bin/env bash

. setenv

cd $PROJ_DIR
opp_makemake -f --deep \
    -KINET4_5_PROJ=$BASE_DIR/inet4.5 \
    -DINET_IMPORT \
    -Isrc \
    -I$\(INET4_5_PROJ\)/src \
    -L$\(INET4_5_PROJ\)/out/clang-release/src \
    -lINET$\(D\)

make MODE=release -j$(nproc) clean
make MODE=release -j$(nproc) all
