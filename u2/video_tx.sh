#!/bin/bash
# /opt/u1u2-bridge/u2/video_tx.sh
#
# На У2 (Orange Pi 5):
#   composite VRX → грабер Arkmicro 18ec:5555 (UVC, EasyCAP-клон) →
#   RKMPP H.264 → RTP → UDP к У1.
#
# Параметры подобраны под приоритет «низкая латенция»:
#   - profile=66 (baseline), нет B-кадров. ВНИМАНИЕ: downstream capsfilter
#     `video/x-h264,profile=baseline` НЕ ставить — mpph264enc отдаёт
#     caps как `Baseline` (с заглавной), фильтр требует `baseline` →
#     pipeline молча виснет в PLAYING. См. Lessons & Incidents 2026-06-03.
#   - GOP=15 кадров (быстрый recovery после потерь)
#   - bitrate 2500 kbps — с запасом для CPE710 PHY 80+ Mbps
#   - mtu 1200 — резерв под WG-overhead через интернет (180 мс RTT).
#     На коротком линке (CPE710, 3–7 мс) можно поднять до 1400.
#
# Arkmicro отдаёт ТОЛЬКО 640x480 MJPG. YUYV не поддерживает, VIDIOC_ENUMSTD
# не работает. `io-mode=` у v4l2src не задаём — userptr (io-mode=4) известно
# проблемный для дешёвых UVC.

set -euo pipefail

DEV="${VIDEO_DEV:-/dev/video0}"
WIDTH="${VIDEO_W:-640}"
HEIGHT="${VIDEO_H:-480}"
FPS="${VIDEO_FPS:-30}"
BITRATE="${VIDEO_BITRATE:-2500000}"
MTU="${MTU:-1200}"
PEER_HOST="${PEER_HOST:-10.8.0.6}"
PEER_PORT="${PEER_PORT:-5600}"

exec gst-launch-1.0 -v \
  v4l2src device="$DEV" ! \
  "image/jpeg,width=$WIDTH,height=$HEIGHT,framerate=$FPS/1" ! \
  jpegdec ! \
  videoconvert ! \
  video/x-raw,format=NV12 ! \
  mpph264enc \
    rc-mode=cbr \
    bps="$BITRATE" \
    bps-max=$((BITRATE * 12 / 10)) \
    gop=15 \
    profile=66 \
    level=40 \
    header-mode=1 ! \
  h264parse config-interval=1 ! \
  rtph264pay pt=96 mtu="$MTU" config-interval=1 ! \
  udpsink host="$PEER_HOST" port="$PEER_PORT" sync=false async=false
