#!/usr/bin/env python3
"""
Send a prompt to Claude and display the response on an ESP32 e-ink display.

Usage:
    python claude_to_display.py "What are three fun facts about dolphins?"
    python claude_to_display.py --ip 192.168.1.100 "Explain quantum computing simply"
    python claude_to_display.py  # interactive mode

Requires:
    - ANTHROPIC_API_KEY environment variable
    - ESP32 running the e-ink display firmware on your local network
"""

import argparse
import sys

import anthropic
import requests

DEFAULT_ESP32_IP = "192.168.1.50"
ESP32_PORT = 80
MAX_DISPLAY_CHARS = 2000

SYSTEM_PROMPT = (
    "You are a helpful assistant. Your responses will be displayed on a small "
    "800x480 e-ink screen, so keep answers concise and well-structured. "
    "Use short paragraphs. Avoid markdown formatting, code blocks, or bullet "
    "points with special characters — plain text only."
)


def ask_claude(prompt: str) -> str:
    """Send a prompt to Claude and return the response text."""
    client = anthropic.Anthropic()
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def send_to_display(text: str, ip: str) -> None:
    """POST text to the ESP32 e-ink display."""
    # Truncate if too long for display
    if len(text) > MAX_DISPLAY_CHARS:
        text = text[:MAX_DISPLAY_CHARS - 3] + "..."
        print(f"[truncated to {MAX_DISPLAY_CHARS} chars]")

    url = f"http://{ip}:{ESP32_PORT}/display"
    try:
        resp = requests.post(url, json={"text": text}, timeout=10)
        resp.raise_for_status()
        print(f"\nSent to display at {ip} — refresh will take a few seconds.")
    except requests.ConnectionError:
        print(f"\nError: Could not connect to ESP32 at {ip}")
        print("Make sure the ESP32 is powered on and connected to WiFi.")
        sys.exit(1)
    except requests.Timeout:
        print(f"\nError: Connection to {ip} timed out.")
        sys.exit(1)
    except requests.HTTPError as e:
        print(f"\nError from ESP32: {e.response.status_code} {e.response.text}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Ask Claude, display on e-ink")
    parser.add_argument("prompt", nargs="?", help="The prompt to send to Claude")
    parser.add_argument(
        "--ip",
        default=DEFAULT_ESP32_IP,
        help=f"ESP32 IP address (default: {DEFAULT_ESP32_IP})",
    )
    args = parser.parse_args()

    # Get prompt
    prompt = args.prompt
    if not prompt:
        print("Enter your prompt (press Enter to send):")
        prompt = input("> ").strip()
        if not prompt:
            print("No prompt provided. Exiting.")
            sys.exit(0)

    print(f"\nAsking Claude: {prompt}\n")

    # Call Claude API
    try:
        response = ask_claude(prompt)
    except anthropic.AuthenticationError:
        print("Error: Invalid ANTHROPIC_API_KEY. Set it with:")
        print('  export ANTHROPIC_API_KEY="sk-ant-..."')
        sys.exit(1)
    except anthropic.APIError as e:
        print(f"Claude API error: {e}")
        sys.exit(1)

    # Print response locally
    print("--- Claude's response ---")
    print(response)
    print("-------------------------")

    # Send to display
    send_to_display(response, args.ip)


if __name__ == "__main__":
    main()
