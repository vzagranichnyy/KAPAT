#!/bin/bash

set -e # Stop the script on any critical error

echo "================================================="
echo "       🚀 Installing KAPAT (Klipper Auto PA Tuning)"
echo "================================================="

# Paths
KAPAT_DIR="$HOME/KAPAT"
KLIPPER_EXTRAS="$HOME/klipper/klippy/extras"
SERVICE_FILE="/etc/systemd/system/kapat.service"

# 1. Install system dependencies (important for clean images!)
echo "📦 Checking system packages (python3-venv)..."
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip

# 2. Clone or update the repository
if [ -d "$KAPAT_DIR" ]; then
    echo "🔄 Updating the KAPAT repository..."
    cd "$KAPAT_DIR"
    git pull
else
    echo "📥 Downloading KAPAT from GitHub..."
    git clone https://github.com/vzagranichnyy/KAPAT.git "$KAPAT_DIR"
fi

# 3. Set up the Python virtual environment
echo "🐍 Setting up an isolated Python environment..."
cd "$KAPAT_DIR"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate

# 4. Install required libraries
echo "📦 Installing required libraries (FastAPI, NumPy, SciPy)..."
pip install --upgrade pip
pip install --no-cache-dir -r requirements.txt

# 5. Detect the application entry point (FIXED FOR SERVER OPERATION)
if [ -f "$KAPAT_DIR/prusa_pa_tuner/app.py" ]; then
    UVICORN_APP="prusa_pa_tuner.app:app"
else
    UVICORN_APP="app:app"
fi

# 6. Create directories for log files
echo "📁 Creating directories for test results (runs)..."
mkdir -p "$KAPAT_DIR/runs"
mkdir -p "$KAPAT_DIR/prusa_pa_tuner/runs"

# 7. Copy Klipper modules and restart Klipper
echo "⚙️ Installing Klipper files..."
if [ -d "$KLIPPER_EXTRAS" ]; then
    # Locate the Klipper module files within the repository
    if [ -d "$KAPAT_DIR/klipper/klippy/extras" ]; then
        cp $KAPAT_DIR/klipper/klippy/extras/*.py $KLIPPER_EXTRAS/
    elif [ -d "$KAPAT_DIR/klipper_extras" ]; then
        cp $KAPAT_DIR/klipper_extras/*.py $KLIPPER_EXTRAS/
    fi
    echo "✅ Klipper modules copied."

    echo "🔄 Restarting Klipper to apply the changes..."
    sudo systemctl restart klipper || true
else
    echo "⚠️ Directory $KLIPPER_EXTRAS not found! Is Klipper installed in a different location?"
fi

# 8. Automatically copy kapat.cfg (NEW!)
echo "📄 Configuring Klipper..."
if [ -f "$KAPAT_DIR/kapat.cfg" ]; then
    if [ -d "$HOME/printer_data/config" ]; then
        cp "$KAPAT_DIR/kapat.cfg" "$HOME/printer_data/config/"
        echo "✅ kapat.cfg has been copied to ~/printer_data/config/"
    elif [ -d "$HOME/klipper_config" ]; then
        cp "$KAPAT_DIR/kapat.cfg" "$HOME/klipper_config/"
        echo "✅ kapat.cfg has been copied to ~/klipper_config/"
    else
        echo "⚠️ Configuration directory not found. Please copy kapat.cfg manually."
    fi
else
    echo "⚠️ kapat.cfg was not found in the repository! Don't forget to create it."
fi

# 9. Configure automatic startup (systemd)
echo "🔌 Configuring the server systemd service..."
cat <<EOF | sudo tee $SERVICE_FILE > /dev/null
[Unit]
Description=KAPAT Web Server
After=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$KAPAT_DIR
ExecStart=$KAPAT_DIR/venv/bin/uvicorn $UVICORN_APP --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable kapat
sudo systemctl restart kapat

echo "================================================="
echo "🎉 KAPAT installation completed successfully!"
echo ""
echo "❗ IMPORTANT: Add the line [include kapat.cfg] to your printer.cfg!"
echo ""
echo "🌐 The web interface is available at:"
echo "   http://<your-printer-ip-address>:8000"
echo "================================================="
