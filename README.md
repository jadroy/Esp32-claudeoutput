# ESP32 Claude E-Ink Display

Prompt Claude from your laptop, see the response on a 7.5" e-ink display.

```
You type a prompt
    ↓
Python script → Claude API → gets response
    ↓
HTTP POST to ESP32 on local WiFi
    ↓
ESP32 renders text on 7.5" e-ink display (800×480)
```

## Hardware

- **Board**: DFRobot FireBeetle 2 ESP32-E
- **Display**: Waveshare 7.5" e-Paper v2 (800×480, black/white)
- **Driver board**: DESPI-C02 or Waveshare e-Paper HAT

### Wiring

| Signal | ESP32 GPIO | Display Pin |
|--------|-----------|-------------|
| BUSY   | 14        | BUSY        |
| CS     | 13        | CS          |
| RST    | 21        | RST         |
| DC     | 22        | DC          |
| SCK    | 18        | CLK         |
| MISO   | 19        | —           |
| MOSI   | 23        | DIN         |
| PWR    | 26        | VCC (via MOSFET or direct) |

## Prerequisites

- [PlatformIO](https://platformio.org/install) (CLI or VS Code extension)
- Python 3.8+
- An [Anthropic API key](https://console.anthropic.com/)

## Setup

### 1. Configure WiFi

Edit `firmware/include/config.h` and set your WiFi credentials:

```c
#define WIFI_SSID "YOUR_WIFI_SSID"
#define WIFI_PASS "YOUR_WIFI_PASSWORD"
```

### 2. Flash the firmware

```bash
cd firmware
pio run -t upload
pio device monitor   # watch serial output (115200 baud)
```

The display should show "Ready!" with the ESP32's IP address.

### 3. Install Python dependencies

```bash
cd script
pip install -r requirements.txt
```

### 4. Set your API key

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

### 5. Send a prompt

```bash
python script/claude_to_display.py --ip <ESP32_IP> "What are three fun facts about dolphins?"
```

The response prints in your terminal and appears on the e-ink display after a few seconds.

## Testing with curl

You can test the display without the Python script:

```bash
curl -X POST http://<ESP32_IP>/display \
  -H "Content-Type: application/json" \
  -d '{"text":"Hello from curl!"}'
```

## How it works

- The ESP32 runs a simple HTTP server with a `POST /display` endpoint
- It accepts `{"text": "..."}` and renders the text with automatic word wrapping
- Font size auto-scales based on text length (short → large font, long → small font)
- Text that exceeds the display area is truncated with "..."
- Full display refresh takes ~5-15 seconds (normal for 7.5" e-ink)

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Display stays blank | Check wiring, especially GPIO 26 (power pin) |
| WiFi won't connect | Verify SSID/password in `config.h`, ensure 2.4 GHz network |
| Display shows garbled output | SPI pin remapping may have failed — check serial monitor |
| "Connection refused" from Python | Confirm ESP32 IP matches `--ip` flag |
| Upload fails | Hold BOOT button on FireBeetle while uploading |
