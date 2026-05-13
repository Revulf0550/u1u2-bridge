#!/bin/bash
# /opt/u1u2-bridge/u2/video_tx.sh
#
# На У2 (Orange Pi 5):
#   composite VRX → MS2130 (USB UVC) → RKMPP H.264 encoder → RTP → UDP к У1
#
# Параметры подобраны под приоритет «низкая латенция»:
#   - profile=baseline, нет B-кадров
#   - GOP=15 кадров (быстрый recovery после потерь)
#   - bitrate 2500 kbps — с запасом для CPE710 PHY 80+ Mbps
#
# MS2130 умеет MJPEG на грабере — это снижает USB-нагрузку до ~10 МБ/с
# и убирает лишний YUY2-конверт перед энкодером.

set -euo pipefail

DEV="${VIDEO_DEV:-/dev/video0}"
WIDTH="${VIDEO_W:-720}"
HEIGHT="${VIDEO_H:-576}"      # 576 для PAL, 480 для NTSC
FPS="${VIDEO_FPS:-25}"        # 25 для PAL, 30 для NTSC
BITRATE="${VIDEO_BITRATE:-2500000}"
PEER_HOST="${PEER_HOST:-192.168.1.20}"
PEER_PORT="${PEER_PORT:-5600}"

exec gst-launch-1.0 -v \
  v4l2src device="$DEV" io-mode=4 ! \
  image/jpeg,width="$WIDTH",height="$HEIGHT",framerate="$FPS/1" ! \
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
  video/x-h264,profile=baseline ! \
  h264parse config-interval=1 ! \
  rtph264pay pt=96 mtu=1400 config-interval=1 ! \
  udpsink host="$PEER_HOST" port="$PEER_PORT" sync=false async=false
