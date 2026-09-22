#!/usr/bin/env bash
# ==============================================================================
# First-Boot Remote Access & Pi Connect Activator
# Device: anikdiary | User: goosepi
# ==============================================================================

set -e

CONNECT_TOKEN="rpuak_fKp3etgZdqgTA48dyZgcrbTf"

echo "=== [1/2] Installing Raspberry Pi Connect Lite ==="
sudo apt-get update
sudo apt-get install -y rpi-connect-lite

echo "=== [2/2] Linking Device to Raspberry Pi Connect Account ==="
rpi-connect signin "$CONNECT_TOKEN"

echo ""
echo "Checking connection status..."
rpi-connect status

echo ""
echo "Device 'anikdiary' is now linked!"
echo "Access remote terminal from anywhere at: https://connect.raspberrypi.com/"
