#!/bin/bash
# /opt/u1u2-bridge/u1/video_rx.sh
#
# На У1 (Orange Pi 5):
#   UDP RTP H.264 → RKMPP decode → fullscreen HDMI через cage+waylandsink.
#
# kmssink НЕ работает на joshua-riek + RK3588 (VOP2 driver bugs:
# `wait pd0 off timeout`, `unexpected power on pd5`). cage поднимает
# минимальный headless Wayland-композитор, waylandsink рисует в него.
# Стоит ~5–10 мс латенции против kmssink, но единственный рабочий путь
# в текущем стеке. См. Lessons & Incidents 2026-06-03.
#
# Требует /run/user/0 (tmpfs, пересоздаётся через tmpfiles.d — см. install.sh).

set -euo pipefail

LISTEN_PORT="${LISTEN_PORT:-5600}"
# 500 ms — под wg-через-интернет (RTT 180 мс). На CPE710 (3–7 мс) — снижать
# до 30–50, это основной knob для glass-to-glass latency.
JITTER_LATENCY="${JITTER_LATENCY:-500}"

# Перед запуском убедитесь, что Orange Pi загрузился без display-manager'а:
#   sudo systemctl set-default multi-user.target
# cage берёт DRM-устройство монопольно.

exec env XDG_RUNTIME_DIR=/run/user/0 cage -- gst-launch-1.0 -v \
  udpsrc port="$LISTEN_PORT" \
    caps="application/x-rtp,encoding-name=H264,payload=96,clock-rate=90000" \
    buffer-size=2097152 ! \
  rtpjitterbuffer latency="$JITTER_LATENCY" drop-on-latency=false do-lost=true ! \
  rtph264depay ! \
  h264parse ! \
  mppvideodec ! \
  videoconvert ! \
  waylandsink sync=false
