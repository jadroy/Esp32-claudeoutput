// ESP32 Claude E-Ink Display — Firmware
// Receives text over HTTP and renders it on a Waveshare 7.5" e-ink display.

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <SPI.h>
#include <ArduinoJson.h>

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
// B. Word-wrap text rendering
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

// Render precomputed lines to the display using paged drawing
void renderText(const String& text) {
    const GFXfont* font = pickFont(text.length());
    int lineHeight = getLineHeight(font);
    int usableWidth = DISPLAY_WIDTH - 2 * MARGIN_X;
    int usableHeight = DISPLAY_HEIGHT - 2 * MARGIN_Y;
    int maxLines = usableHeight / lineHeight;

    // Precompute all wrapped lines
    WrappedLines wrapped;
    wordWrap(text, font, usableWidth, wrapped);

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

    // Paged drawing — all draw calls inside the loop must be deterministic
    display.setFont(font);
    display.setFullWindow();
    display.firstPage();
    do {
        display.fillScreen(GxEPD_WHITE);
        for (int i = 0; i < wrapped.count; i++) {
            display.setCursor(MARGIN_X, baselineY + i * lineHeight);
            display.print(wrapped.lines[i]);
        }
    } while (display.nextPage());

    if (truncated) {
        Serial.println("[display] Text truncated — too long for screen");
    }
}

// ============================================================
// C. HTTP server handlers
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

void handleNotFound() {
    server.send(404, "application/json", "{\"error\":\"not found\"}");
}

// ============================================================
// D. setup() and loop()
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

    // Start HTTP server
    server.on("/", HTTP_GET, handleRoot);
    server.on("/display", HTTP_POST, handleDisplay);
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
