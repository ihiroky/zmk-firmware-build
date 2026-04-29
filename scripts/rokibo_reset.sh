#!/bin/bash -x

cd $WORKSPACE_DIR
west build \
  -s zmk/app \
  -d ../zmk-config/build/reset \
  -b seeeduino_xiao_ble \
  -S studio-rpc-usb-uart \
  -- \
  -DZMK_CONFIG=/workspaces/zmk-config/config \
  -DZMK_EXTRA_MODULES=/workspaces/zmk-config \
  -DSHIELD=settings_reset
