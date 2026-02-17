#!/bin/bash
# Install the daily e-ink generator as a macOS background service.
# Runs every morning — no app needs to be open.
#
# Usage:
#   ./install_daily.sh            # install (default 8:00 AM)
#   ./install_daily.sh 07 30      # install at 7:30 AM
#   ./install_daily.sh uninstall  # remove the service

set -e

LABEL="com.claudeeink.daily"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$(which python3)"
LOG_DIR="$HOME/Library/Logs"

HOUR="${1:-8}"
MINUTE="${2:-0}"

if [ "$1" = "uninstall" ]; then
    echo "Uninstalling daily service..."
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    rm -f "$PLIST_PATH"
    echo "Done. Service removed."
    exit 0
fi

# Prompt for API key if not set
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "Enter your Anthropic API key:"
    read -r API_KEY
else
    API_KEY="$ANTHROPIC_API_KEY"
fi

if [ -z "$API_KEY" ]; then
    echo "Error: API key required"
    exit 1
fi

# Prompt for ESP32 IP
ESP32_IP="${ESP32_IP:-192.168.1.50}"
echo "ESP32 IP [$ESP32_IP]:"
read -r INPUT_IP
ESP32_IP="${INPUT_IP:-$ESP32_IP}"

echo "Installing daily service..."
echo "  Time: ${HOUR}:$(printf '%02d' $MINUTE) every day"
echo "  ESP32: ${ESP32_IP}"
echo "  Script: ${SCRIPT_DIR}/daily_gen.py"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON}</string>
        <string>${SCRIPT_DIR}/daily_gen.py</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>ANTHROPIC_API_KEY</key>
        <string>${API_KEY}</string>
        <key>ESP32_IP</key>
        <string>${ESP32_IP}</string>
    </dict>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>${HOUR}</integer>
        <key>Minute</key>
        <integer>${MINUTE}</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/claudeeink-daily.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/claudeeink-daily.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF

launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo ""
echo "Installed! The daily pick will generate at ${HOUR}:$(printf '%02d' $MINUTE) every day."
echo "Logs: ${LOG_DIR}/claudeeink-daily.log"
echo ""
echo "To test now:  launchctl start ${LABEL}"
echo "To remove:    $0 uninstall"
