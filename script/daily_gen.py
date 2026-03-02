#!/usr/bin/env python3
"""
Standalone daily generator — runs via macOS launchd scheduler.
No GUI needed. Generates a daily pick from Claude and sends it to the ESP32.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import anthropic
import requests

ESP32_IP = os.environ.get("ESP32_IP", "192.168.1.50")
LOG_PATH = str(Path(__file__).parent / "daily_log.json")
CONTENT_PATH = str(Path(__file__).parent / "content_daily.json")

DAILY_PROMPT = (
    "You are the voice of an e-ink display on someone's wall. Each day you choose "
    "ONE thing to display. You have complete creative freedom. It could be:\n\n"
    "- A thought-provoking quote (attributed)\n"
    "- An obscure, fascinating historical fact\n"
    "- A tiny poem you write\n"
    "- A philosophical question to sit with\n"
    "- A beautiful or rare word and its meaning\n"
    "- Something that happened on this day in history\n"
    "- A mini story in 3 sentences\n"
    "- A piece of wisdom from an unexpected source\n"
    "- A scientific wonder\n"
    "- A perspective shift\n"
    "- Or anything else you find genuinely interesting\n\n"
    "Be surprising. Be varied. Make it something worth glancing at all day. "
    "Write ONLY the content — no preamble, no 'here's today's display', no meta-commentary. "
    "Plain text only, no markdown. Use only basic ASCII — no em dashes, curly quotes, or "
    "special Unicode. Use regular dashes (-) and straight quotes. "
    "Keep it under 400 characters so it displays in a large, beautiful font on the 800x480 screen."
)


def load_log():
    try:
        with open(LOG_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_log(history):
    with open(LOG_PATH, "w") as f:
        json.dump(history, f, indent=2)


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    history = load_log()

    # Build context so Claude doesn't repeat
    recent = "\n".join([f"- {h['text'][:80]}" for h in history[-10:]])
    user_msg = f"Today is {datetime.now().strftime('%A, %B %d, %Y')}. Pick something for the display."
    if recent:
        user_msg += f"\n\nHere are your recent picks (do NOT repeat any of these):\n{recent}"

    # Generate
    print(f"[{datetime.now().strftime('%H:%M')}] Generating daily pick...")
    client = anthropic.Anthropic()
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=512,
        system=DAILY_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    text = message.content[0].text.strip()
    print(f"[daily] {text}")

    # Save to log
    history.append({
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time": datetime.now().strftime("%H:%M"),
        "text": text,
    })
    save_log(history)

    # Write content file for slow-mode polling
    with open(CONTENT_PATH, "w") as f:
        json.dump({"text": text}, f, indent=2)
    print(f"[content] Written to {CONTENT_PATH}")

    # Send to display (non-fatal — ESP32 may be asleep in slow mode)
    try:
        resp = requests.post(
            f"http://{ESP32_IP}/display",
            json={"text": text[:2000]},
            timeout=10,
        )
        resp.raise_for_status()
        print("[display] Sent successfully")
    except Exception as e:
        print(f"[display] Could not push to ESP32 (may be asleep): {e}")


if __name__ == "__main__":
    main()
