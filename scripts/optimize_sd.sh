#!/usr/bin/env bash
# ==============================================================================
# MicroSD Card Longevity Optimization Script for Raspberry Pi 4B
# Reduces flash write-amplification for high-frequency 1-second data loggers.
# ==============================================================================

set -e

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo bash scripts/optimize_sd.sh"
    exit 1
fi

echo "=== [1/3] Configuring journald to use RAM (volatile) ==="
mkdir -p /etc/systemd/journald.conf.d/
cat << 'EOF' > /etc/systemd/journald.conf.d/00-sd-protect.conf
[Journal]
Storage=volatile
RuntimeMaxUse=64M
RateLimitIntervalSec=30s
RateLimitBurst=500
EOF
systemctl restart systemd-journald
echo "Journald set to RAM storage (max 64MB)."

echo "=== [2/3] Enabling tmpfs for /tmp ==="
if ! grep -q "tmpfs /tmp" /etc/fstab; then
    echo "tmpfs /tmp tmpfs defaults,noatime,nosuid,size=128m 0 0" >> /etc/fstab
    echo "Added tmpfs /tmp to /etc/fstab"
else
    echo "/tmp is already mounted on tmpfs."
fi

echo "=== [3/3] SD Card Mount Options Check ==="
echo "Inspect your /etc/fstab root partition. Ensure 'noatime' is present."
echo "Current /etc/fstab:"
grep -v "^#" /etc/fstab

echo ""
echo "=== SD Card Optimization Completed ==="
echo "Reboot recommended to apply tmpfs: sudo reboot"
