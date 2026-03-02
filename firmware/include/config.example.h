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
// Battery ADC (FireBeetle 2 built-in voltage divider on GPIO34)
// ============================================================
#define PIN_BAT_ADC       34
#define BAT_SAMPLES       16    // ADC averaging for noise reduction

// ============================================================
// Status bar
// ============================================================
#define STATUS_BAR_HEIGHT 25    // pixels reserved at bottom of display

// ============================================================
// NTP time sync
// ============================================================
#define NTP_SERVER        "pool.ntp.org"
#define UTC_OFFSET_SEC    -28800  // UTC-8 (Pacific Standard Time)
#define DST_OFFSET_SEC    3600    // +1 hour for daylight saving

// ============================================================
// HTTP server
// ============================================================
#define HTTP_PORT  80

// ============================================================
// Slow mode (battery / deep sleep)
// ============================================================
#define CONTENT_URL          "http://192.168.1.50:8080/api/content"
#define SLEEP_DURATION_US    86400000000ULL  // 24 hours in microseconds
#define USB_VOLTAGE_THRESHOLD 4.5            // above = USB, below = battery

#endif // CONFIG_H
