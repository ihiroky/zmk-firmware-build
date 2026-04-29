#!/bin/bash

cd $WORKSPACE_DIR
test -d .west || \
  west init -l config --mf /workspaces/zmk-config/config/west.yml
test -d zmk || \
  west update --fetch-opt=--filter=blob:none
test -d /root/.cmake/packages/Zephyr || \
  west zephyr-export

tail -f /dev/null
