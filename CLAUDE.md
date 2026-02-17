# Project: ESP32 Claude E-Ink Display

## Security — NEVER commit identifying info

Before every git commit, you MUST check staged files for:
- WiFi SSIDs or passwords
- Home addresses or street names
- Specific IP addresses on the local network (e.g. 10.0.0.x, 192.168.x.x that aren't generic defaults)
- API keys (ANTHROPIC_API_KEY or any sk-ant-* strings)
- Full names or usernames that could identify the user

If any are found, replace with generic placeholders before committing:
- WiFi: `YOUR_WIFI_SSID` / `YOUR_WIFI_PASSWORD`
- Addresses: `Your Address, City`
- IPs: `192.168.1.50` (generic default)
- API keys: `sk-ant-...`

`firmware/include/config.h` is gitignored — only `config.example.h` should be committed.

## Architecture

- `firmware/` — PlatformIO ESP32 project (GxEPD2, ArduinoJson, WebServer)
- `script/app.py` — Mac app (Flask + pywebview) with Claude chat, ride estimates, daily generation
- `script/daily_gen.py` — Standalone daily generator for launchd background scheduling
- `script/install_daily.sh` — Installs macOS launchd service for auto-generation
