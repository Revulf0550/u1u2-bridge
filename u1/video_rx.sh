#!/bin/bash
# /opt/u1u2-bridge/u1/video_rx.sh
#
# На У1 (Orange Pi 5):
#   UDP RTP H.264 → RKMPP decode → fullscreen HDMI вывод через kmssink
#
# kmssink выводит напрямую в DRM/KMS, минуя композитор — самая короткая
# цепочка для HDMI на Orange Pi 5.
#
# Если очки аналоговые: ставим HDMI→CVBS конвертер (CX2262 и подобные)
# между HDMI Orange Pi и входом MECH/VTX. В скрипте ничего не меняется.

set -euo pipefail

LISTEN_PORT="${LISTEN_PORT:-5600}"

# Перед запуском убедитесь, что Orange Pi загрузился без X/wayland-композитора:
#   sudo systemctl set-default multi-user.target
# kmssink не уживается с Xorg/wayland, ему нужен прямой доступ к DRM.

exec gst-launch-1.0 -v \
  udpsrc port="$LISTEN_PORT" \
    caps="application/x-rtp,encoding-name=H264,payload=96,clock-rate=90000" \
    buffer-size=2097152 ! \
  rtpjitterbuffer latency=15 drop-on-latency=true do-lost=true ! \
  rtph264depay ! \
  h264parse ! \
  mppvideodec ! \
  videoconvert ! \
  kmssink sync=false force-modesetting=true can-scale=true
