#ifndef CONFIG_H
#define CONFIG_H

// ============================================================
// WiFi credentials — EDIT THESE TWO LINES
// ============================================================
#define WIFI_SSID "YOUR_WIFI_SSID"
#define WIFI_PASS "YOUR_WIFI_PASSWORD"

// ============================================================
// E-ink display pin wiring (FireBeetle 2 → DESPI-C02 / Waveshare HAT)
// ============================================================
#define PIN_EPD_BUSY  14
#define PIN_EPD_CS    13
#define PIN_EPD_RST   21
#define PIN_EPD_DC    22
#define PIN_EPD_SCK   18
#define PIN_EPD_MISO  19
#define PIN_EPD_MOSI  23
#define PIN_EPD_PWR   26  // GPIO-controlled power to display

// ============================================================
// Display dimensions (Waveshare 7.5" v2)
// ============================================================
#define DISPLAY_WIDTH   800
#define DISPLAY_HEIGHT  480

// ============================================================
// Text rendering
// ============================================================
#define MARGIN_X  20
#define MARGIN_Y  10
#define LINE_SPACING_EXTRA  4  // extra pixels between lines

// ============================================================
// HTTP server
// ============================================================
#define HTTP_PORT  80

#endif // CONFIG_H
