// ESP32 Claude E-Ink Display — Firmware
// Receives text over HTTP and renders it on a Waveshare 7.5" e-ink display.

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <HTTPClient.h>
#include <SPI.h>
#include <ArduinoJson.h>
#include <time.h>

// GxEPD2 — Waveshare 7.5" v2 (800x480, black/white)
#include <GxEPD2_BW.h>
#include <epd/GxEPD2_750_T7.h>

// Adafruit GFX free fonts
#include <Fonts/FreeSans9pt7b.h>
#include <Fonts/FreeSans12pt7b.h>
#include <Fonts/FreeSans18pt7b.h>

#include "config.h"

// ============================================================
// Display object
// ============================================================
GxEPD2_BW<GxEPD2_750_T7, GxEPD2_750_T7::HEIGHT> display(
    GxEPD2_750_T7(PIN_EPD_CS, PIN_EPD_DC, PIN_EPD_RST, PIN_EPD_BUSY));

// ============================================================
// HTTP server
// ============================================================
WebServer server(HTTP_PORT);

// ============================================================
// Status bar — cached strings (must be stable across paged draws)
// ============================================================
String statusBattery;
String statusWifi;
String statusTime;

// ============================================================
// A. Display initialization
// ============================================================
void initDisplay() {
    // Power on the e-ink display via GPIO
    pinMode(PIN_EPD_PWR, OUTPUT);
    digitalWrite(PIN_EPD_PWR, HIGH);
    delay(100);  // let power stabilize

    display.init(115200, true, 10, false);  // serial diag, initial=true, reset duration (10 for DESPI-C02), pulldown RST

    // CRITICAL: Remap SPI pins for FireBeetle 2 wiring
    // Must be called AFTER display.init() which starts SPI with default pins
    SPI.end();
    SPI.begin(PIN_EPD_SCK, PIN_EPD_MISO, PIN_EPD_MOSI, PIN_EPD_CS);

    display.setRotation(0);  // landscape, 800 wide x 480 tall
    display.setTextColor(GxEPD_BLACK);
    display.setTextWrap(false);  // we handle wrapping ourselves
}

// ============================================================
// B. Battery voltage reading
// ============================================================
float readBatteryVoltage() {
    uint32_t sum = 0;
    for (int i = 0; i < BAT_SAMPLES; i++) {
        sum += analogRead(PIN_BAT_ADC);
    }
    float avg = (float)sum / BAT_SAMPLES;
    // ESP32 ADC: 12-bit (0-4095), 3.3V reference
    // FireBeetle 2 has a built-in voltage divider (factor ×2)
    float voltage = (avg / 4095.0) * 3.3 * 2.0;
    return voltage;
}

String getBatteryIndicator(float voltage) {
    // LiPo range: ~3.0V (empty) to ~4.2V (full)
    // If device is running but voltage < 3.0V, it can't be on battery — must be USB
    if (voltage > 4.5 || voltage < 3.0) return "USB";

    // Map to 4 bars
    int bars;
    if (voltage >= 4.05)     bars = 4;  // 90-100%
    else if (voltage >= 3.8) bars = 3;  // 50-90%
    else if (voltage >= 3.5) bars = 2;  // 20-50%
    else if (voltage >= 3.2) bars = 1;  // 5-20%
    else                     bars = 0;  // <5%

    String indicator = "[";
    for (int i = 0; i < 4; i++) {
        indicator += (i < bars) ? "=" : " ";
    }
    indicator += "] " + String(voltage, 1) + "V";
    return indicator;
}

// ============================================================
// C. NTP time
// ============================================================
String getCurrentTime() {
    struct tm timeinfo;
    if (!getLocalTime(&timeinfo, 1000)) {
        return "No time";
    }
    char buf[24];
    strftime(buf, sizeof(buf), "%b %d, %I:%M %p", &timeinfo);
    return String(buf);
}

// ============================================================
// D. Status bar preparation & drawing
// ============================================================
void prepareStatusBar() {
    float voltage = readBatteryVoltage();
    statusBattery = getBatteryIndicator(voltage);
    statusWifi = (WiFi.status() == WL_CONNECTED) ? "WiFi OK" : "WiFi X";
    statusTime = getCurrentTime();
    Serial.printf("[status] %s | %s | %s\n",
                  statusBattery.c_str(), statusWifi.c_str(), statusTime.c_str());
}

void drawStatusBar() {
    int barTop = DISPLAY_HEIGHT - STATUS_BAR_HEIGHT;

    // Separator line
    display.drawLine(MARGIN_X, barTop, DISPLAY_WIDTH - MARGIN_X, barTop, GxEPD_BLACK);

    // Use smallest font for status
    display.setFont(&FreeSans9pt7b);

    int textY = barTop + 17;  // baseline offset within status bar

    // Left: battery
    display.setCursor(MARGIN_X, textY);
    display.print(statusBattery);

    // Center: WiFi status
    int16_t x1, y1;
    uint16_t w, h;
    display.getTextBounds(statusWifi.c_str(), 0, 0, &x1, &y1, &w, &h);
    display.setCursor((DISPLAY_WIDTH - w) / 2, textY);
    display.print(statusWifi);

    // Right: timestamp
    display.getTextBounds(statusTime.c_str(), 0, 0, &x1, &y1, &w, &h);
    display.setCursor(DISPLAY_WIDTH - MARGIN_X - w, textY);
    display.print(statusTime);
}

// ============================================================
// E. Word-wrap text rendering
// ============================================================

// Pick a font based on text length
const GFXfont* pickFont(int len) {
    if (len < 200)  return &FreeSans18pt7b;
    if (len <= 800)  return &FreeSans12pt7b;
    return &FreeSans9pt7b;
}

// Get the line height for a font (ascent + descent + spacing)
int getLineHeight(const GFXfont* font) {
    // yAdvance gives the recommended line spacing for the font
    return font->yAdvance + LINE_SPACING_EXTRA;
}

// Precompute wrapped lines from text, respecting display width.
// Returns a vector of String lines ready to draw.
struct WrappedLines {
    String lines[60];  // max lines we'll ever need
    int count;
};

void wordWrap(const String& text, const GFXfont* font, int maxWidth, WrappedLines& result) {
    result.count = 0;
    display.setFont(font);

    int i = 0;
    int len = text.length();

    while (i < len && result.count < 60) {
        // Find end of current segment (up to next newline or end)
        int nlPos = text.indexOf('\n', i);
        if (nlPos == -1) nlPos = len;

        String segment = text.substring(i, nlPos);
        i = nlPos + 1;  // skip past the newline

        // If segment is empty (blank line), add empty line
        if (segment.length() == 0) {
            result.lines[result.count++] = "";
            continue;
        }

        // Word-wrap this segment
        int segStart = 0;
        while (segStart < (int)segment.length() && result.count < 60) {
            // Try fitting as many words as possible on one line
            String line = "";
            String candidate = "";
            int pos = segStart;

            while (pos < (int)segment.length()) {
                // Find next space or end of segment
                int spacePos = segment.indexOf(' ', pos);
                if (spacePos == -1) spacePos = segment.length();

                String word = segment.substring(pos, spacePos);

                if (candidate.length() == 0) {
                    candidate = word;
                } else {
                    candidate = candidate + " " + word;
                }

                // Measure width
                int16_t x1, y1;
                uint16_t w, h;
                display.getTextBounds(candidate.c_str(), 0, 0, &x1, &y1, &w, &h);

                if ((int)w > maxWidth && line.length() > 0) {
                    // This word doesn't fit — use the line without it
                    break;
                }

                line = candidate;
                pos = spacePos + 1;

                if (pos > (int)segment.length()) break;
            }

            // If we couldn't fit even one word, force it on the line anyway
            if (line.length() == 0) {
                int spacePos = segment.indexOf(' ', segStart);
                if (spacePos == -1) spacePos = segment.length();
                line = segment.substring(segStart, spacePos);
                segStart = spacePos + 1;
            } else {
                segStart += line.length();
                // Skip the space after the line
                if (segStart < (int)segment.length() && segment.charAt(segStart) == ' ') {
                    segStart++;
                }
            }

            result.lines[result.count++] = line;
        }
    }
}

// Replace common Unicode characters with ASCII equivalents
String sanitizeText(const String& text) {
    String out = text;
    // Em dash (UTF-8: E2 80 94) and en dash (E2 80 93) → " - "
    out.replace("\xe2\x80\x94", " - ");
    out.replace("\xe2\x80\x93", " - ");
    // Curly quotes → straight quotes
    out.replace("\xe2\x80\x9c", "\"");  // left double
    out.replace("\xe2\x80\x9d", "\"");  // right double
    out.replace("\xe2\x80\x98", "'");   // left single
    out.replace("\xe2\x80\x99", "'");   // right single
    // Ellipsis → three dots
    out.replace("\xe2\x80\xa6", "...");
    return out;
}

// Render precomputed lines to the display using paged drawing
void renderText(const String& text) {
    String cleanText = sanitizeText(text);
    const GFXfont* font = pickFont(cleanText.length());
    int lineHeight = getLineHeight(font);
    int usableWidth = DISPLAY_WIDTH - 2 * MARGIN_X;
    int usableHeight = DISPLAY_HEIGHT - 2 * MARGIN_Y - STATUS_BAR_HEIGHT;
    int maxLines = usableHeight / lineHeight;

    // Precompute all wrapped lines
    WrappedLines wrapped;
    wordWrap(cleanText, font, usableWidth, wrapped);

    // Check if we need to truncate
    bool truncated = false;
    if (wrapped.count > maxLines) {
        wrapped.count = maxLines;
        truncated = true;
        // Replace last line's end with "..."
        String& lastLine = wrapped.lines[wrapped.count - 1];
        if (lastLine.length() > 3) {
            lastLine = lastLine.substring(0, lastLine.length() - 3) + "...";
        } else {
            lastLine = "...";
        }
    }

    // First baseline Y = margin + font ascent
    // The font's yAdvance includes ascent; first line baseline offset ≈ lineHeight - LINE_SPACING_EXTRA
    int baselineY = MARGIN_Y + lineHeight - LINE_SPACING_EXTRA;

    // Cache status bar strings before paged drawing (must be deterministic)
    prepareStatusBar();

    // Paged drawing — all draw calls inside the loop must be deterministic
    display.setFont(font);
    display.setFullWindow();
    display.firstPage();
    do {
        display.fillScreen(GxEPD_WHITE);

        // Main content
        display.setFont(font);
        for (int i = 0; i < wrapped.count; i++) {
            display.setCursor(MARGIN_X, baselineY + i * lineHeight);
            display.print(wrapped.lines[i]);
        }

        // Status bar at bottom
        drawStatusBar();
    } while (display.nextPage());

    if (truncated) {
        Serial.println("[display] Text truncated — too long for screen");
    }
}

// ============================================================
// F. Slow mode (battery / deep sleep)
// ============================================================
void runSlowMode() {
    Serial.println("[slow] Battery detected — running slow mode");

    HTTPClient http;
    http.begin(CONTENT_URL);
    http.setTimeout(15000);
    int httpCode = http.GET();

    String text;
    if (httpCode == 200) {
        String payload = http.getString();
        JsonDocument doc;
        DeserializationError err = deserializeJson(doc, payload);
        if (err || !doc["text"].is<const char*>()) {
            text = "Content error:\nReceived invalid data from server.";
            Serial.println("[slow] JSON parse error");
        } else {
            text = doc["text"].as<String>();
            Serial.printf("[slow] Got content (%d chars)\n", text.length());
        }
    } else if (httpCode == 204) {
        text = "No content for today yet.";
        Serial.println("[slow] No content available (204)");
    } else {
        text = "Cannot reach server.\nHTTP " + String(httpCode);
        Serial.printf("[slow] HTTP error: %d\n", httpCode);
    }
    http.end();

    renderText(text);
    Serial.println("[slow] Display updated");

    // Shut down for deep sleep
    WiFi.disconnect(true);
    WiFi.mode(WIFI_OFF);
    digitalWrite(PIN_EPD_PWR, LOW);

    Serial.printf("[slow] Sleeping for %llu us (~%llu h)\n",
                  (unsigned long long)SLEEP_DURATION_US,
                  (unsigned long long)(SLEEP_DURATION_US / 3600000000ULL));
    Serial.flush();
    esp_deep_sleep(SLEEP_DURATION_US);
    // Device resets on wake — setup() runs again
}

// ============================================================
// G. HTTP server handlers
// ============================================================
void handleRoot() {
    String html = "Claude E-Ink Display is running.<br>IP: " + WiFi.localIP().toString();
    server.send(200, "text/html", html);
}

void handleDisplay() {
    if (!server.hasArg("plain")) {
        server.send(400, "application/json", "{\"error\":\"no body\"}");
        return;
    }

    String body = server.arg("plain");
    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, body);

    if (err) {
        server.send(400, "application/json", "{\"error\":\"invalid JSON\"}");
        return;
    }

    if (!doc["text"].is<const char*>()) {
        server.send(400, "application/json", "{\"error\":\"missing 'text' field\"}");
        return;
    }

    String text = doc["text"].as<String>();

    if (text.length() == 0) {
        server.send(400, "application/json", "{\"error\":\"empty text\"}");
        return;
    }

    // Respond immediately — display refresh takes 5-15 seconds
    server.send(200, "application/json", "{\"status\":\"ok\"}");
    Serial.println("[http] Received text (" + String(text.length()) + " chars)");

    // Now render on display (blocking, ~5-15s for full refresh)
    renderText(text);
    Serial.println("[display] Refresh complete");
}

void handleStatus() {
    float voltage = readBatteryVoltage();
    JsonDocument doc;
    doc["battery_voltage"] = round(voltage * 100) / 100.0;
    doc["battery_indicator"] = getBatteryIndicator(voltage);
    doc["wifi_rssi"] = WiFi.RSSI();
    doc["wifi_ip"] = WiFi.localIP().toString();
    doc["uptime_seconds"] = millis() / 1000;
    doc["time"] = getCurrentTime();

    String json;
    serializeJson(doc, json);
    server.send(200, "application/json", json);
}

void handleNotFound() {
    server.send(404, "application/json", "{\"error\":\"not found\"}");
}

// ============================================================
// H. setup() and loop()
// ============================================================
void setup() {
    Serial.begin(115200);
    Serial.println("\n=== Claude E-Ink Display ===");

    // Initialize display
    initDisplay();
    Serial.println("[display] Initialized");

    // Connect to WiFi
    Serial.print("[wifi] Connecting to ");
    Serial.println(WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASS);

    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
        attempts++;
        if (attempts > 40) {  // 20 seconds timeout
            Serial.println("\n[wifi] Failed to connect! Restarting...");
            ESP.restart();
        }
    }

    Serial.println();
    Serial.print("[wifi] Connected! IP: ");
    Serial.println(WiFi.localIP());

    // Configure ADC for battery reading
    analogReadResolution(12);
    analogSetAttenuation(ADC_11db);

    // Sync NTP time
    configTime(UTC_OFFSET_SEC, DST_OFFSET_SEC, NTP_SERVER);
    Serial.print("[ntp] Syncing time...");
    struct tm timeinfo;
    if (getLocalTime(&timeinfo, 5000)) {
        char buf[32];
        strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", &timeinfo);
        Serial.printf(" OK: %s\n", buf);
    } else {
        Serial.println(" failed (will retry later)");
    }

    // Mode detection: USB vs battery
    float voltage = readBatteryVoltage();
    Serial.printf("[mode] Battery voltage: %.2fV (threshold: %.1fV)\n",
                  voltage, USB_VOLTAGE_THRESHOLD);

    // TODO: Re-enable slow mode once battery detection is reliable
    // Currently disabled — voltage-based detection can't distinguish
    // USB+low-battery from battery-only operation
    // if (voltage <= USB_VOLTAGE_THRESHOLD && voltage > 2.5) {
    //     runSlowMode();  // never returns
    // }

    // Instant mode (USB) — start web server
    Serial.println("[mode] USB power detected — instant mode");

    // Start HTTP server
    server.on("/", HTTP_GET, handleRoot);
    server.on("/display", HTTP_POST, handleDisplay);
    server.on("/status", HTTP_GET, handleStatus);
    server.onNotFound(handleNotFound);
    server.begin();
    Serial.println("[http] Server started on port " + String(HTTP_PORT));

    // Show ready message on display
    String readyMsg = "Ready!\n\nIP: " + WiFi.localIP().toString() + "\nPort: " + String(HTTP_PORT);
    renderText(readyMsg);
}

void loop() {
    server.handleClient();
}
