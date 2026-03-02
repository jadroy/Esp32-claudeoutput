#!/usr/bin/env python3
"""
Ship Tracker — collects AIS data from SF Bay via aisstream.io WebSocket.

Works standalone (for launchd scheduling) or as import (for app.py).

Usage:
    AISSTREAM_API_KEY=xxx python ship_tracker.py
    AISSTREAM_API_KEY=xxx python ship_tracker.py --push 192.168.1.50
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
import websockets

load_dotenv(Path(__file__).parent / ".env")

CONTENT_PATH = Path(__file__).parent / "content_ships.json"
LOG_PATH = Path(__file__).parent / "ship_log.json"

# SF Bay bounding box: Hunters Point to Port of Oakland
BOUNDING_BOX = [
    [37.82, -122.40],  # NW corner
    [37.72, -122.28],  # SE corner
]

LISTEN_SECONDS = 45

# AIS ship type codes to human-readable names
SHIP_TYPES = {
    range(20, 30): "Wing in Ground",
    range(30, 36): "Fishing",
    range(36, 37): "Sailing",
    range(37, 38): "Pleasure Craft",
    range(40, 50): "High Speed Craft",
    range(50, 51): "Pilot Vessel",
    range(51, 52): "Search & Rescue",
    range(52, 53): "Tug",
    range(53, 54): "Port Tender",
    range(55, 56): "Law Enforcement",
    range(58, 59): "Medical Transport",
    range(60, 70): "Passenger",
    range(70, 80): "Cargo",
    range(80, 90): "Tanker",
    range(90, 100): "Other",
}


def ship_type_name(type_code):
    """Convert AIS ship type code to human name."""
    if not type_code:
        return "Unknown"
    for code_range, name in SHIP_TYPES.items():
        if type_code in code_range:
            return name
    return "Unknown"


def _interest_score(ship):
    """Score a vessel for display priority. Higher = more interesting."""
    score = 0
    # Named ships are more interesting
    if ship.get("name") and ship["name"] not in ("", "Unknown"):
        score += 10
    # Larger ships are more interesting
    length = ship.get("length", 0) or 0
    score += min(length / 10, 20)
    # Moving ships are more interesting than stationary
    speed = ship.get("speed", 0) or 0
    if speed > 0.5:
        score += 5
    # Ships with destinations are more interesting
    if ship.get("destination") and ship["destination"].strip():
        score += 5
    # Prefer cargo/tanker/passenger over small craft
    type_name = ship.get("type_name", "")
    if type_name in ("Cargo", "Tanker", "Passenger"):
        score += 10
    elif type_name in ("Tug", "Pilot Vessel"):
        score += 3
    return score


async def collect_ais_data(api_key, seconds=LISTEN_SECONDS):
    """Connect to aisstream.io and collect vessel data for `seconds`."""
    ships = {}  # keyed by MMSI

    subscribe_msg = {
        "APIKey": api_key,
        "BoundingBoxes": [BOUNDING_BOX],
    }

    print(f"[ships] Connecting to aisstream.io, listening for {seconds}s...")

    try:
        async with websockets.connect("wss://stream.aisstream.io/v0/stream") as ws:
            await ws.send(json.dumps(subscribe_msg))

            async def listen():
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    msg_type = msg.get("MessageType", "")
                    meta = msg.get("MetaData", {})
                    mmsi = str(meta.get("MMSI", ""))
                    if not mmsi:
                        continue

                    # Initialize ship entry
                    if mmsi not in ships:
                        ships[mmsi] = {
                            "mmsi": mmsi,
                            "name": None,
                            "type_code": None,
                            "type_name": None,
                            "destination": None,
                            "speed": None,
                            "heading": None,
                            "length": None,
                            "draft": None,
                            "lat": None,
                            "lon": None,
                        }

                    ship = ships[mmsi]

                    # Ship name from metadata
                    ship_name = meta.get("ShipName", "").strip()
                    if ship_name:
                        ship["name"] = ship_name

                    # Position Report (types 1, 2, 3, 18, 19)
                    if msg_type == "PositionReport":
                        pos = msg.get("Message", {}).get("PositionReport", {})
                        ship["speed"] = pos.get("Sog")
                        ship["heading"] = pos.get("TrueHeading")
                        if ship["heading"] == 511:
                            ship["heading"] = None
                        ship["lat"] = pos.get("Latitude")
                        ship["lon"] = pos.get("Longitude")

                    # Static and Voyage Data (type 5)
                    elif msg_type == "ShipStaticData":
                        static = msg.get("Message", {}).get("ShipStaticData", {})
                        ship["type_code"] = static.get("Type")
                        ship["type_name"] = ship_type_name(static.get("Type"))
                        dest = static.get("Destination", "").strip()
                        if dest:
                            ship["destination"] = dest
                        dim = static.get("Dimension", {})
                        if dim:
                            a = dim.get("A", 0) or 0
                            b = dim.get("B", 0) or 0
                            length = a + b
                            if length > 0:
                                ship["length"] = length
                        draft = static.get("MaximumStaticDraught")
                        if draft and draft > 0:
                            ship["draft"] = round(draft, 1)

                    # Standard Class B Position Report
                    elif msg_type == "StandardClassBCSPositionReport":
                        pos = msg.get("Message", {}).get("StandardClassBCSPositionReport", {})
                        ship["speed"] = pos.get("Sog")
                        ship["heading"] = pos.get("TrueHeading")
                        if ship["heading"] == 511:
                            ship["heading"] = None
                        ship["lat"] = pos.get("Latitude")
                        ship["lon"] = pos.get("Longitude")

            try:
                await asyncio.wait_for(listen(), timeout=seconds)
            except asyncio.TimeoutError:
                pass

    except Exception as e:
        print(f"[ships] WebSocket error: {e}", file=sys.stderr)

    print(f"[ships] Collected {len(ships)} vessels")
    return ships


# Grid for FreeMono12pt on 800x480 e-ink (760x435 usable)
# 12pt: 14px/char = 54 cols, (24+4)px/line = 15 rows
GRID_COLS = 54
MAX_DISPLAY_LINES = 15


def _ship_symbol(length, heading, speed):
    """ASCII ship symbol sized by length, pointed by heading."""
    length = length or 20
    tiers = [30, 100, 200, 300]
    tier = sum(1 for t in tiers if length >= t)

    # Anchored / stationary
    if speed is not None and speed <= 0.5:
        return ["o", "(o)", "((o))", "(((o)))", "((((o))))"][tier]

    # Moving west
    if heading is not None and 135 < heading < 315:
        return ["<", "<=", "<==", "<===", "<===="][tier]

    # Moving east or unknown heading
    return [">", "=>", "==>", "===>", "====>"][tier]


MAP_ROWS = 7  # rows for the spatial grid area


def _pos_to_grid(lat, lon):
    """Map lat/lon to (col, row) on the radar grid."""
    lat_min, lat_max = 37.72, 37.82
    lon_min, lon_max = -122.40, -122.28
    map_cols = GRID_COLS - 4  # leave margin for border/pad

    lat = max(lat_min, min(lat_max, lat or (lat_min + lat_max) / 2))
    lon = max(lon_min, min(lon_max, lon or (lon_min + lon_max) / 2))

    col = int((lon - lon_min) / (lon_max - lon_min) * (map_cols - 1))
    row = int((lat_max - lat) / (lat_max - lat_min) * (MAP_ROWS - 1))
    return col + 2, row  # +2 for left padding


def format_ship_display(ships_dict):
    """Format vessels as a spatial radar display for monospace e-ink."""
    now = datetime.now().strftime("%b %d, %-I:%M %p")

    if not ships_dict:
        return (
            "(((o)))  SF BAY RADAR\n\n"
            "  No vessels detected.\n"
            "  The bay is quiet.\n\n"
            f"  {now}"
        )

    # Top ships by interest
    vessels = sorted(ships_dict.values(), key=_interest_score, reverse=True)
    top = vessels[:5]

    # Build the radar grid
    map_rows = MAP_ROWS
    grid = [[" "] * GRID_COLS for _ in range(map_rows)]

    # Place each ship on the grid
    placed = []  # (row, col, symbol, label) for legend
    used_cells = set()

    for ship in top:
        symbol = _ship_symbol(
            ship.get("length"), ship.get("heading"), ship.get("speed")
        )
        name = (ship.get("name") or f"MMSI {ship['mmsi']}")[:14]
        col, row = _pos_to_grid(ship.get("lat"), ship.get("lon"))

        # Resolve vertical collisions
        orig_row = row
        while row in {r for r, *_ in used_cells}:
            row += 1
            if row >= map_rows:
                row = orig_row - 1
                if row < 0:
                    row = orig_row
                    break

        # Build the ship string: "===> NAME"
        ship_str = f"{symbol} {name}"

        # Clamp col so ship_str fits on the row
        max_start = GRID_COLS - len(ship_str) - 1
        col = max(1, min(col, max_start))

        # Write onto grid row
        if 0 <= row < map_rows:
            for ci, ch in enumerate(ship_str):
                if col + ci < GRID_COLS:
                    grid[row][col + ci] = ch
            used_cells.add((row, col, symbol, name))

            # Build detail for legend
            parts = []
            type_name = ship.get("type_name") or ""
            if type_name and type_name != "Unknown":
                parts.append(type_name)
            if ship.get("length"):
                parts.append(f"{ship['length']}m")
            speed = ship.get("speed")
            if speed is not None and speed > 0.5:
                parts.append(f"{speed:.0f}kn")
            elif speed is not None:
                parts.append("anch")
            if ship.get("destination") and ship["destination"].strip():
                parts.append(f">{ship['destination'].strip()[:8]}")
            placed.append((name, " ".join(parts)))

    # Assemble output
    lines = []
    header = f"(((o)))  SF BAY RADAR"
    lines.append(f"{header}{now:>{GRID_COLS - len(header)}}")
    border = "~" * GRID_COLS
    lines.append(border)
    for row in grid:
        lines.append("".join(row).rstrip())
    lines.append(border)

    # Legend: two ships per line, capped to grid width
    for i in range(0, len(placed), 2):
        pair = placed[i:i+2]
        parts = [f"{n}: {d}" for n, d in pair]
        line = "  " + "   ".join(parts)
        lines.append(line[:GRID_COLS])

    footer = f"W  Hunters Pt"
    mid = f"{len(ships_dict)} vessels in range"
    right = "Oakland  E"
    gap = GRID_COLS - len(footer) - len(mid) - len(right)
    lines.append(f"{footer}{' ' * (gap // 2)}{mid}{' ' * (gap - gap // 2)}{right}")

    return "\n".join(lines)


def generate_ship_content(api_key=None, seconds=LISTEN_SECONDS):
    """
    Run AIS collection and return formatted text.
    Used by app.py and standalone mode.
    """
    api_key = api_key or os.environ.get("AISSTREAM_API_KEY")
    if not api_key:
        raise ValueError("AISSTREAM_API_KEY not set")

    ships = asyncio.run(collect_ais_data(api_key, seconds=seconds))
    text = format_ship_display(ships)

    # Write content file
    with open(CONTENT_PATH, "w") as f:
        json.dump({"text": text}, f, indent=2)
    print(f"[ships] Written to {CONTENT_PATH}")

    # Save raw data to log
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "vessel_count": len(ships),
        "vessels": list(ships.values()),
    }
    try:
        with open(LOG_PATH, "r") as f:
            log = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        log = []
    log.append(log_entry)
    # Keep last 50 entries
    log = log[-50:]
    with open(LOG_PATH, "w") as f:
        json.dump(log, f, indent=2)

    return text, ships


def main():
    import argparse

    parser = argparse.ArgumentParser(description="SF Bay Ship Tracker")
    parser.add_argument("--push", metavar="ESP32_IP", help="Push result to ESP32")
    parser.add_argument("--seconds", type=int, default=LISTEN_SECONDS, help="Seconds to listen")
    args = parser.parse_args()

    api_key = os.environ.get("AISSTREAM_API_KEY")
    if not api_key:
        print("ERROR: AISSTREAM_API_KEY not set", file=sys.stderr)
        print("Sign up at https://aisstream.io/ for a free API key")
        sys.exit(1)

    text, ships = generate_ship_content(api_key, seconds=args.seconds)
    print(f"\n{text}")

    if args.push:
        import requests
        try:
            resp = requests.post(
                f"http://{args.push}/display",
                json={"text": text[:2000]},
                timeout=10,
            )
            resp.raise_for_status()
            print(f"\n[display] Sent to {args.push}")
        except Exception as e:
            print(f"\n[display] Could not push: {e}")


if __name__ == "__main__":
    main()
