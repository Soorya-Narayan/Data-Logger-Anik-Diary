#!/usr/bin/env bash
# ==============================================================================
# Setup script for Anik Dairy 10 KL Pasteurizer Logger on Raspberry Pi 4B
# OS: Raspberry Pi OS Lite (64-bit, Bookworm)
# ==============================================================================

set -e

echo "=== [1/5] Updating System Packages ==="
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip python3-dev git sqlite3 curl

INSTALL_DIR="/home/elanadu/pasteurizer-logger"
CURRENT_DIR="$(pwd)"

if [ "$CURRENT_DIR" != "$INSTALL_DIR" ]; then
    echo "Note: Current directory is $CURRENT_DIR."
    echo "If you intend to install to $INSTALL_DIR, ensure files are in place."
fi

echo "=== [2/5] Setting up Python Virtual Environment ==="
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "Created virtualenv in ./venv"
fi

source venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

echo "=== [3/5] Creating Directories ==="
mkdir -p data reports logs

echo "=== [4/5] Testing Mock Poller & Storage ==="
python3 -c "
from src.plc.mock_client import MockPLCClient
from src.storage.db import DatabaseManager
import yaml

with open('config/config.yaml') as f:
    cfg = yaml.safe_load(f)

client = MockPLCClient(cfg)
client.connect()
sample = client.read_tags()
print('Sample Telemetry Generated:', sample['status'], '| Flow:', sample['milk_flow'], 'L/hr')
client.disconnect()

db = DatabaseManager('data/pasteurizer_data.db')
db.insert_batch([sample])
print('Database insertion verified successfully.')
"

echo "=== [5/5] Installing Systemd Services ==="
read -p "Do you want to install and enable the systemd services now? (y/N): " -r
if [[ $REPLY =~ ^[Yy]$ ]]; then
    sudo cp systemd/pasteurizer-poller.service /etc/systemd/system/
    sudo cp systemd/pasteurizer-dashboard.service /etc/systemd/system/
    sudo cp systemd/pasteurizer-report.service /etc/systemd/system/
    sudo cp systemd/pasteurizer-report.timer /etc/systemd/system/

    sudo systemctl daemon-reload
    sudo systemctl enable pasteurizer-poller.service
    sudo systemctl enable pasteurizer-dashboard.service
    sudo systemctl enable pasteurizer-report.timer

    sudo systemctl start pasteurizer-poller.service
    sudo systemctl start pasteurizer-dashboard.service
    sudo systemctl start pasteurizer-report.timer

    echo "Services enabled and started!"
    echo "Check poller status: sudo systemctl status pasteurizer-poller.service"
    echo "Check dashboard:     sudo systemctl status pasteurizer-dashboard.service"
fi

echo "=== Setup Complete! ==="
echo "Access the dashboard on client PC browser at: http://<raspberry-pi-ip>:8080"
