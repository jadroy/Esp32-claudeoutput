#!/usr/bin/env python3
"""Generate a compact, public-safe signal for the e-ink dashboard."""

from __future__ import annotations

import json
import os
import tempfile
import html
import re
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


# Rounded to the 50 Summit area so the public repo does not expose a doorway.
LATITUDE = 37.716
LONGITUDE = -122.453
TIMEZONE = ZoneInfo("America/Los_Angeles")
OUTPUT_PATH = Path(os.environ.get("DAILY_OUTPUT", "public/daily.json"))
USER_AGENT = "roy-eink-brief/1.0"
NEWS_FEEDS = (
    ("SF Standard", "https://sfstandard.com/feed/"),
    ("NPR", "https://feeds.npr.org/1001/rss.xml"),
    ("BBC", "https://feeds.bbci.co.uk/news/rss.xml"),
)


def fetch_json(base_url: str, params: dict[str, object]) -> dict:
    url = f"{base_url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def fetch_weather() -> dict:
    return fetch_json(
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "hourly": "temperature_2m,precipitation_probability,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
            "temperature_unit": "fahrenheit",
            "timezone": "America/Los_Angeles",
            "forecast_days": 2,
        },
    )


def fetch_air_quality() -> dict:
    return fetch_json(
        "https://air-quality-api.open-meteo.com/v1/air-quality",
        {
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "hourly": "us_aqi",
            "timezone": "America/Los_Angeles",
            "forecast_days": 2,
        },
    )


def clean_headline(value: str) -> str:
    value = html.unescape(value)
    value = value.replace("\u2018", "'").replace("\u2019", "'")
    value = value.replace("\u201c", '"').replace("\u201d", '"')
    value = value.replace("\u2013", "-").replace("\u2014", "-")
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", value).strip()


def fetch_rss(source: str, url: str) -> list[dict]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:
        root = ET.fromstring(response.read())
    stories = []
    for item in root.findall(".//item")[:6]:
        title = clean_headline(item.findtext("title", ""))
        link = (item.findtext("link", "") or "").strip()
        if len(title) >= 20:
            stories.append({"title": title[:140], "source": source, "url": link})
    return stories


def headline_words(title: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", title.lower()) if len(word) > 2}


def select_headlines(stories: list[dict], limit: int = 4) -> list[dict]:
    selected = []
    for story in stories:
        words = headline_words(story["title"])
        duplicate = False
        for existing in selected:
            other = headline_words(existing["title"])
            union = words | other
            if union and len(words & other) / len(union) >= 0.45:
                duplicate = True
                break
        if not duplicate:
            selected.append(story)
        if len(selected) == limit:
            break
    return selected


def fetch_news() -> list[dict]:
    by_source = []
    for source, url in NEWS_FEEDS:
        try:
            by_source.append((source, fetch_rss(source, url)))
        except Exception:
            continue
    interleaved = []
    for index in range(4):
        for _, stories in by_source:
            if index < len(stories):
                interleaved.append(stories[index])
    return select_headlines(interleaved)


def parse_local(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=TIMEZONE)


def compact_hour(value: datetime) -> str:
    hour = value.strftime("%I").lstrip("0") or "12"
    return f"{hour}{value.strftime('%p').lower()}"


def today_hours(weather: dict, now: datetime) -> list[dict]:
    hourly = weather.get("hourly", {})
    rows = []
    for stamp, temp, rain, code in zip(
        hourly.get("time", []),
        hourly.get("temperature_2m", []),
        hourly.get("precipitation_probability", []),
        hourly.get("weather_code", []),
    ):
        moment = parse_local(stamp)
        if moment.date() == now.date() and moment >= now.replace(minute=0, second=0, microsecond=0):
            rows.append({"time": moment, "temp": temp, "rain": rain or 0, "code": code})
    return rows


def aqi_now(air: dict, now: datetime) -> int | None:
    hourly = air.get("hourly", {})
    candidates = []
    for stamp, value in zip(hourly.get("time", []), hourly.get("us_aqi", [])):
        if value is not None:
            candidates.append((abs((parse_local(stamp) - now).total_seconds()), round(value)))
    return min(candidates)[1] if candidates else None


def best_outdoor_window(hours: list[dict]) -> tuple[datetime, datetime] | None:
    good = [row for row in hours if 50 <= row["temp"] <= 72 and row["rain"] < 25]
    if not good:
        return None

    runs: list[list[dict]] = []
    for row in good:
        if not runs or row["time"] - runs[-1][-1]["time"] != timedelta(hours=1):
            runs.append([row])
        else:
            runs[-1].append(row)
    run = max(runs, key=len)
    if len(run) < 2:
        return None
    return run[0]["time"], run[-1]["time"] + timedelta(hours=1)


def warmest_window(hours: list[dict]) -> tuple[datetime, datetime] | None:
    dry = [row for row in hours if row["rain"] < 25]
    if not dry:
        return None

    warmest = max(row["temp"] for row in dry)
    near_peak = [row for row in dry if row["temp"] >= warmest - 2]
    runs: list[list[dict]] = []
    for row in near_peak:
        if not runs or row["time"] - runs[-1][-1]["time"] != timedelta(hours=1):
            runs.append([row])
        else:
            runs[-1].append(row)
    run = max(runs, key=len)
    return run[0]["time"], run[-1]["time"] + timedelta(hours=1)


def build_signal(weather: dict, air: dict, now: datetime) -> tuple[str, str]:
    hours = today_hours(weather, now)
    daily = weather.get("daily", {})
    high = round(daily.get("temperature_2m_max", [0])[0])
    low = round(daily.get("temperature_2m_min", [0])[0])

    rain_hours = [row for row in hours if row["rain"] >= 45]
    if rain_hours:
        start = rain_hours[0]["time"]
        window = best_outdoor_window([row for row in hours if row["time"] < start])
        if window:
            return (
                f"rain starts around {compact_hour(start)}. best walk window: "
                f"{compact_hour(window[0])} to {compact_hour(window[1])}",
                "weather",
            )
        return f"rain becomes likely around {compact_hour(start)}. umbrella day.", "weather"

    current_aqi = aqi_now(air, now)
    if current_aqi is not None and current_aqi <= 30:
        return f"air quality is unusually good ({current_aqi}). open the windows.", "air-quality"
    if current_aqi is not None and current_aqi >= 101:
        return f"air quality is rough today ({current_aqi}). keep hard exercise indoors.", "air-quality"

    if high >= 82:
        return f"sf reaches {high} today. do the outdoor part before noon.", "weather"
    if high <= 58:
        window = warmest_window(hours)
        if window:
            return (
                f"today stays cool: {low} to {high}. warmest: "
                f"{compact_hour(window[0])} to {compact_hour(window[1])}",
                "weather",
            )
        return f"today stays cool: {low} to {high}. bring a second layer.", "weather"

    window = best_outdoor_window(hours)
    if window:
        return (
            f"high {high}, low {low}. best outside window: "
            f"{compact_hour(window[0])} to {compact_hour(window[1])}",
            "weather",
        )

    return f"ingleside: high {high}, low {low}. no weather drama scheduled.", "weather"


def write_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> None:
    now = datetime.now(TIMEZONE)
    errors = []
    try:
        weather = fetch_weather()
    except Exception as exc:  # The existing file remains useful if a provider has a bad hour.
        weather = {}
        errors.append(f"weather: {exc}")
    try:
        air = fetch_air_quality()
    except Exception as exc:
        air = {}
        errors.append(f"air: {exc}")
    try:
        headlines = fetch_news()
    except Exception as exc:
        headlines = []
        errors.append(f"news: {exc}")

    if weather:
        text, source = build_signal(weather, air, now)
    else:
        text, source = "", "fallback"

    generated = datetime.now(TIMEZONE)
    payload = {
        "text": text[:140],
        "source": source,
        "generated_at": generated.isoformat(timespec="seconds"),
        "valid_until_epoch": int((generated + timedelta(hours=8)).timestamp()),
        "location": "Ingleside",
        "attribution": "Weather data by Open-Meteo.com",
        "headlines": headlines,
        "news_attribution": "Headlines from SF Standard, NPR and BBC",
        "version": 1,
    }
    write_atomic(OUTPUT_PATH, payload)
    print(json.dumps(payload))
    if errors:
        print("; ".join(errors))


if __name__ == "__main__":
    main()
