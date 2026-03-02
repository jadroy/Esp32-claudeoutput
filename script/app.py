#!/usr/bin/env python3
"""
Claude E-Ink Display — Mac app with Claude chat + Ride estimates.

Usage:
    python app.py --ip ESP32_IP
    python app.py --ip ESP32_IP --browser
"""

import argparse
import json
import math
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, request, jsonify, render_template_string

import anthropic
from dotenv import load_dotenv
import requests as http_requests
import webview

load_dotenv(Path(__file__).parent / ".env")

# Ensure sibling modules are importable when run from any directory
sys.path.insert(0, str(Path(__file__).parent))
import app_registry
from ship_tracker import generate_ship_content

DEFAULT_ESP32_IP = "192.168.1.50"
MAX_DISPLAY_CHARS = 2000
ICON_PATH = str(Path(__file__).parent / "icon.png")
DAILY_LOG_PATH = str(Path(__file__).parent / "daily_log.json")
DAILY_CONTENT_PATH = str(Path(__file__).parent / "content_daily.json")

MODELS = {
    "claude-sonnet-4-20250514": {"name": "Sonnet 4", "input_cost": 3.00, "output_cost": 15.00},
    "claude-haiku-3-5-20241022": {"name": "Haiku 3.5", "input_cost": 0.80, "output_cost": 4.00},
    "claude-opus-4-20250514": {"name": "Opus 4", "input_cost": 15.00, "output_cost": 75.00},
}

SYSTEM_PROMPT = (
    "You are a helpful assistant. Your responses will be displayed on a small "
    "800x480 e-ink screen, so keep answers concise and well-structured. "
    "Use short paragraphs. Avoid markdown formatting, code blocks, or bullet "
    "points with special characters — plain text only."
)

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
    "Plain text only, no markdown. Keep it under 400 characters so it displays in a large, "
    "beautiful font on the 800x480 screen."
)

# Track what's been shown so Claude doesn't repeat
daily_history = []

# Uber-style fare estimation constants (SF market rates, approximate)
UBER_PRODUCTS = {
    "UberX": {"base": 2.55, "per_mile": 1.60, "per_min": 0.35, "booking": 2.55, "min_fare": 8.00},
    "Comfort": {"base": 3.85, "per_mile": 2.00, "per_min": 0.45, "booking": 2.55, "min_fare": 12.00},
    "UberXL": {"base": 3.85, "per_mile": 2.50, "per_min": 0.50, "booking": 2.55, "min_fare": 14.00},
    "Black": {"base": 8.00, "per_mile": 4.50, "per_min": 0.65, "booking": 0.00, "min_fare": 25.00},
}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Claude E-Ink</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: #FAF6F1;
            color: #3D3029;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }

        /* ── Top bar ── */
        .topbar {
            display: flex;
            align-items: center;
            padding: 16px 24px;
            border-bottom: 1px solid #EDE8E3;
            background: #FFFFFF;
            gap: 16px;
            -webkit-app-region: drag;
        }

        .topbar svg { width: 22px; height: 22px; flex-shrink: 0; }

        .topbar-title {
            font-size: 14px;
            font-weight: 600;
            color: #D97757;
            margin-right: auto;
        }

        .tab-bar {
            display: flex;
            gap: 0;
            background: #F5F0EB;
            border-radius: 8px;
            padding: 3px;
            -webkit-app-region: no-drag;
        }

        .tab-bar button {
            background: transparent;
            border: none;
            border-radius: 6px;
            padding: 6px 16px;
            font-family: inherit;
            font-size: 12px;
            font-weight: 500;
            color: #9B8578;
            cursor: pointer;
            transition: all 0.15s;
            letter-spacing: 0.2px;
        }

        .tab-bar button:hover { color: #3D3029; }
        .tab-bar button.active { background: #FFFFFF; color: #D97757; box-shadow: 0 1px 2px rgba(0,0,0,0.06); }

        .session-usage {
            font-size: 11px;
            color: #B8ADA5;
            -webkit-app-region: no-drag;
        }
        .session-usage strong { color: #9B8578; font-weight: 600; }

        .app-switcher {
            display: flex; align-items: center; gap: 6px;
            -webkit-app-region: no-drag;
        }
        .app-switcher .label {
            font-size: 11px; color: #B8ADA5; white-space: nowrap;
        }
        .app-switcher select {
            border: 1px solid #EDE8E3; border-radius: 6px; padding: 4px 8px;
            font-family: inherit; font-size: 11px; color: #3D3029;
            background: #FAFAF8; outline: none; cursor: pointer;
        }
        .app-switcher select:focus { border-color: #D97757; }

        /* ── Views ── */
        .view { display: none; flex: 1; flex-direction: column; overflow: hidden; }
        .view.active { display: flex; }

        /* ── Claude view ── */
        .claude-view { padding: 0 24px 20px; }

        .model-row {
            display: flex;
            align-items: center;
            padding: 16px 0 12px;
            gap: 0;
        }

        .model-switcher {
            display: flex;
            background: #F5F0EB;
            border-radius: 8px;
            padding: 3px;
        }

        .model-switcher label {
            padding: 5px 12px;
            font-size: 11px;
            font-weight: 500;
            color: #9B8578;
            cursor: pointer;
            transition: all 0.15s;
            border-radius: 6px;
            user-select: none;
        }
        .model-switcher label:hover { color: #3D3029; }
        .model-switcher input { display: none; }
        .model-switcher input:checked + label { background: #FFFFFF; color: #D97757; box-shadow: 0 1px 2px rgba(0,0,0,0.06); }

        .history {
            flex: 1;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 16px;
            padding-bottom: 8px;
            scrollbar-width: thin;
            scrollbar-color: #DDD5CD transparent;
        }
        .history::-webkit-scrollbar { width: 4px; }
        .history::-webkit-scrollbar-track { background: transparent; }
        .history::-webkit-scrollbar-thumb { background: #DDD5CD; border-radius: 2px; }

        .entry {
            background: #FFFFFF;
            border: 1px solid #EDE8E3;
            border-radius: 14px;
            padding: 16px 18px;
            box-shadow: 0 1px 3px rgba(61, 48, 41, 0.04);
        }
        .entry .prompt { font-size: 13px; color: #9B8578; margin-bottom: 10px; }
        .entry .prompt strong { color: #D97757; font-weight: 600; }
        .entry .response { font-size: 14px; line-height: 1.7; white-space: pre-wrap; color: #3D3029; }
        .entry .meta {
            display: flex; justify-content: space-between; align-items: center;
            font-size: 11px; color: #B8ADA5; margin-top: 12px; padding-top: 10px;
            border-top: 1px solid #F0EBE6;
        }
        .entry .meta .display-status.sent { color: #7BA68A; }
        .entry .meta .display-status.error { color: #C47158; }

        .input-area {
            display: flex; gap: 8px;
            background: #FFFFFF; border: 1px solid #EDE8E3; border-radius: 12px;
            padding: 5px 5px 5px 0;
            box-shadow: 0 1px 4px rgba(61, 48, 41, 0.06);
            transition: border-color 0.2s, box-shadow 0.2s;
        }
        .input-area:focus-within {
            border-color: #D97757;
            box-shadow: 0 1px 4px rgba(61, 48, 41, 0.06), 0 0 0 3px rgba(217, 119, 87, 0.1);
        }

        textarea {
            flex: 1; background: transparent; border: none; color: #3D3029;
            font-family: inherit; font-size: 14px; padding: 9px 14px;
            resize: none; outline: none; min-height: 40px; max-height: 120px;
        }
        textarea::placeholder { color: #C4B8AE; }

        .send-btn {
            background: #D97757; color: #FFF; border: none; border-radius: 9px;
            padding: 0 20px; font-family: inherit; font-size: 13px; font-weight: 600;
            cursor: pointer; transition: background 0.15s; white-space: nowrap;
        }
        .send-btn:hover { background: #C4684A; }
        .send-btn:disabled { background: #E5DDD6; color: #B8ADA5; cursor: not-allowed; }

        .spinner {
            display: inline-block; width: 13px; height: 13px;
            border: 2px solid #EDE8E3; border-top-color: #D97757;
            border-radius: 50%; animation: spin 0.8s linear infinite;
            vertical-align: middle; margin-right: 5px;
        }
        @keyframes spin { to { transform: rotate(360deg); } }

        /* ── Rides view ── */
        .rides-view { padding: 24px; overflow-y: auto; }

        .rides-card {
            background: #FFFFFF; border: 1px solid #EDE8E3; border-radius: 14px;
            padding: 20px; box-shadow: 0 1px 3px rgba(61, 48, 41, 0.04);
            margin-bottom: 16px;
        }

        .rides-card h2 {
            font-size: 14px; font-weight: 600; color: #3D3029;
            margin-bottom: 16px;
        }

        .route-fields { display: flex; flex-direction: column; gap: 10px; margin-bottom: 16px; }

        .route-field {
            display: flex; align-items: center; gap: 10px;
        }
        .route-field .dot {
            width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0;
        }
        .route-field .dot.origin { background: #7BA68A; }
        .route-field .dot.dest { background: #D97757; }

        .route-field input {
            flex: 1; border: 1px solid #EDE8E3; border-radius: 8px;
            padding: 10px 12px; font-family: inherit; font-size: 13px;
            color: #3D3029; outline: none; background: #FAFAF8;
            transition: border-color 0.15s;
        }
        .route-field input:focus { border-color: #D97757; }
        .route-field input::placeholder { color: #C4B8AE; }

        .estimate-btn {
            width: 100%; background: #3D3029; color: #FFF; border: none;
            border-radius: 10px; padding: 11px; font-family: inherit;
            font-size: 13px; font-weight: 600; cursor: pointer;
            transition: background 0.15s;
        }
        .estimate-btn:hover { background: #2A201A; }
        .estimate-btn:disabled { background: #E5DDD6; color: #B8ADA5; cursor: not-allowed; }

        .ride-options { display: flex; flex-direction: column; gap: 10px; }

        .ride-option {
            display: flex; align-items: center; padding: 14px 16px;
            background: #FAFAF8; border: 1px solid #EDE8E3; border-radius: 10px;
            cursor: pointer; transition: all 0.15s; gap: 14px;
        }
        .ride-option:hover { border-color: #D97757; background: #FFF; }
        .ride-option.selected { border-color: #D97757; background: #FFF; box-shadow: 0 0 0 3px rgba(217,119,87,0.1); }

        .ride-option .ride-icon {
            width: 36px; height: 36px; background: #F5F0EB; border-radius: 8px;
            display: flex; align-items: center; justify-content: center;
            font-size: 18px; flex-shrink: 0;
        }
        .ride-option .ride-info { flex: 1; }
        .ride-option .ride-name { font-size: 13px; font-weight: 600; color: #3D3029; }
        .ride-option .ride-time { font-size: 11px; color: #9B8578; margin-top: 2px; }
        .ride-option .ride-price { font-size: 15px; font-weight: 700; color: #3D3029; }

        .send-to-display-btn {
            width: 100%; background: #D97757; color: #FFF; border: none;
            border-radius: 10px; padding: 11px; font-family: inherit;
            font-size: 13px; font-weight: 600; cursor: pointer;
            transition: background 0.15s; margin-top: 16px;
        }
        .send-to-display-btn:hover { background: #C4684A; }
        .send-to-display-btn:disabled { background: #E5DDD6; color: #B8ADA5; cursor: not-allowed; }

        .ride-status {
            text-align: center; font-size: 12px; margin-top: 10px; min-height: 18px;
        }
        .ride-status.sent { color: #7BA68A; }
        .ride-status.error { color: #C47158; }

        .route-info {
            text-align: center; font-size: 12px; color: #9B8578;
            margin-bottom: 14px; padding: 8px 0;
        }

        /* ── Daily view ── */
        .daily-view { padding: 24px; overflow-y: auto; }

        .daily-card {
            background: #FFFFFF; border: 1px solid #EDE8E3; border-radius: 14px;
            padding: 24px; box-shadow: 0 1px 3px rgba(61, 48, 41, 0.04);
            margin-bottom: 16px; text-align: center;
        }

        .daily-card h2 {
            font-size: 14px; font-weight: 600; color: #3D3029;
            margin-bottom: 6px;
        }

        .daily-card .daily-sub {
            font-size: 12px; color: #B8ADA5; margin-bottom: 20px;
        }

        .daily-content {
            font-size: 17px; line-height: 1.8; color: #3D3029;
            white-space: pre-wrap; padding: 20px 8px;
            min-height: 80px;
        }

        .daily-content.empty {
            color: #C4B8AE; font-style: italic; font-size: 14px;
        }

        .daily-meta {
            font-size: 11px; color: #B8ADA5; margin-top: 16px;
            padding-top: 14px; border-top: 1px solid #F0EBE6;
        }
        .daily-meta .sent { color: #7BA68A; }
        .daily-meta .error { color: #C47158; }

        .daily-actions {
            display: flex; gap: 10px; justify-content: center;
        }

        .daily-btn {
            background: #D97757; color: #FFF; border: none; border-radius: 10px;
            padding: 11px 28px; font-family: inherit; font-size: 13px; font-weight: 600;
            cursor: pointer; transition: background 0.15s;
        }
        .daily-btn:hover { background: #C4684A; }
        .daily-btn:disabled { background: #E5DDD6; color: #B8ADA5; cursor: not-allowed; }

        .daily-btn.secondary {
            background: #F5F0EB; color: #9B8578;
        }
        .daily-btn.secondary:hover { background: #EDE8E3; }

        .daily-schedule {
            background: #FFFFFF; border: 1px solid #EDE8E3; border-radius: 14px;
            padding: 18px 24px; box-shadow: 0 1px 3px rgba(61, 48, 41, 0.04);
            display: flex; align-items: center; gap: 14px;
        }

        .daily-schedule .schedule-label {
            font-size: 13px; color: #3D3029; font-weight: 500;
        }

        .daily-schedule .schedule-desc {
            font-size: 11px; color: #B8ADA5; margin-top: 2px;
        }

        .daily-schedule select, .daily-schedule input[type="time"] {
            border: 1px solid #EDE8E3; border-radius: 8px; padding: 7px 10px;
            font-family: inherit; font-size: 12px; color: #3D3029;
            background: #FAFAF8; outline: none;
        }
        .daily-schedule select:focus, .daily-schedule input[type="time"]:focus { border-color: #D97757; }

        .toggle {
            position: relative; width: 40px; height: 22px; flex-shrink: 0; margin-left: auto;
        }
        .toggle input { opacity: 0; width: 0; height: 0; }
        .toggle .slider {
            position: absolute; cursor: pointer; inset: 0;
            background: #E5DDD6; border-radius: 22px; transition: 0.2s;
        }
        .toggle .slider:before {
            content: ""; position: absolute; height: 16px; width: 16px;
            left: 3px; bottom: 3px; background: #FFF; border-radius: 50%;
            transition: 0.2s;
        }
        .toggle input:checked + .slider { background: #D97757; }
        .toggle input:checked + .slider:before { transform: translateX(18px); }

        .daily-history-list {
            background: #FFFFFF; border: 1px solid #EDE8E3; border-radius: 14px;
            padding: 18px 24px; box-shadow: 0 1px 3px rgba(61, 48, 41, 0.04);
            margin-top: 16px;
        }

        .daily-history-list h3 {
            font-size: 12px; font-weight: 600; color: #9B8578;
            margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.5px;
        }

        .daily-history-item {
            padding: 10px 0; border-bottom: 1px solid #F0EBE6;
            font-size: 13px; line-height: 1.5; color: #3D3029;
        }
        .daily-history-item:last-child { border-bottom: none; }
        .daily-history-item .date {
            font-size: 11px; color: #B8ADA5; margin-bottom: 4px;
        }

        /* ── Ships view ── */
        .ships-view { padding: 24px; overflow-y: auto; }

        .ships-card {
            background: #FFFFFF; border: 1px solid #EDE8E3; border-radius: 14px;
            padding: 24px; box-shadow: 0 1px 3px rgba(61, 48, 41, 0.04);
            margin-bottom: 16px; text-align: center;
        }

        .ships-card h2 {
            font-size: 14px; font-weight: 600; color: #3D3029;
            margin-bottom: 6px;
        }

        .ships-card .ships-sub {
            font-size: 12px; color: #B8ADA5; margin-bottom: 20px;
        }

        .ships-content {
            font-size: 14px; line-height: 1.7; color: #3D3029;
            white-space: pre-wrap; padding: 16px 8px;
            min-height: 80px; text-align: left;
            font-family: 'SF Mono', 'Menlo', 'Monaco', monospace;
            font-size: 12px;
        }

        .ships-content.empty {
            color: #C4B8AE; font-style: italic; font-size: 14px;
            text-align: center; font-family: inherit;
        }

        .ships-meta {
            font-size: 11px; color: #B8ADA5; margin-top: 16px;
            padding-top: 14px; border-top: 1px solid #F0EBE6;
        }
        .ships-meta .sent { color: #7BA68A; }
        .ships-meta .error { color: #C47158; }

        .ships-actions {
            display: flex; gap: 10px; justify-content: center;
        }

        .ships-btn {
            background: #3D3029; color: #FFF; border: none; border-radius: 10px;
            padding: 11px 28px; font-family: inherit; font-size: 13px; font-weight: 600;
            cursor: pointer; transition: background 0.15s;
        }
        .ships-btn:hover { background: #2A201A; }
        .ships-btn:disabled { background: #E5DDD6; color: #B8ADA5; cursor: not-allowed; }

        .footer {
            text-align: center; padding: 12px; font-size: 11px; color: #C4B8AE;
        }
        .footer span { color: #9B8578; }
    </style>
</head>
<body>
    <div class="topbar">
        <svg viewBox="0 0 24 24" fill="none">
            <rect x="3" y="3" width="18" height="18" rx="4" fill="#D97757" opacity="0.15"/>
            <rect x="6" y="8" width="12" height="1.5" rx="0.75" fill="#D97757"/>
            <rect x="6" y="11.25" width="12" height="1.5" rx="0.75" fill="#D97757"/>
            <rect x="6" y="14.5" width="8" height="1.5" rx="0.75" fill="#D97757" opacity="0.5"/>
        </svg>
        <span class="topbar-title">E-Ink Display</span>

        <div class="tab-bar">
            <button class="active" onclick="switchTab('daily')">Daily</button>
            <button onclick="switchTab('ships')">Ships</button>
            <button onclick="switchTab('claude')">Claude</button>
            <button onclick="switchTab('rides')">Rides</button>
        </div>

        <div class="app-switcher">
            <span class="label">Display:</span>
            <select id="activeApp" onchange="setActiveApp(this.value)">
            </select>
        </div>

        <div class="session-usage"><span id="sessionTokens"></span></div>
    </div>

    <!-- ── Daily View ── -->
    <div class="view daily-view active" id="view-daily">
        <div class="daily-card">
            <h2>Today's Display</h2>
            <div class="daily-sub">Claude picks something for your wall each day</div>
            <div class="daily-content empty" id="dailyContent">Nothing yet — hit Generate</div>
            <div class="daily-meta" id="dailyMeta"></div>
        </div>

        <div class="daily-actions">
            <button class="daily-btn" id="generateBtn" onclick="generateDaily()">Generate</button>
            <button class="daily-btn secondary" id="reshuffleBtn" onclick="generateDaily()" style="display:none;">Reshuffle</button>
        </div>

        <div class="daily-schedule" style="margin-top: 16px;">
            <div>
                <div class="schedule-label">Auto-generate daily</div>
                <div class="schedule-desc">Sends a new pick to your display each morning</div>
            </div>
            <input type="time" id="dailyTime" value="08:00">
            <label class="toggle">
                <input type="checkbox" id="dailyToggle" onchange="toggleSchedule()">
                <span class="slider"></span>
            </label>
        </div>

        <div class="daily-history-list" id="dailyHistorySection" style="display:none;">
            <h3>Recent</h3>
            <div id="dailyHistoryList"></div>
        </div>
    </div>

    <!-- ── Ships View ── -->
    <div class="view ships-view" id="view-ships">
        <div class="ships-card">
            <h2>SF Bay Vessels</h2>
            <div class="ships-sub">Live AIS data from aisstream.io</div>
            <div class="ships-content empty" id="shipsContent">No data yet — hit Scan Bay</div>
            <div class="ships-meta" id="shipsMeta"></div>
        </div>

        <div class="ships-actions">
            <button class="ships-btn" id="scanBtn" onclick="scanBay()">Scan Bay</button>
        </div>
    </div>

    <!-- ── Claude View ── -->
    <div class="view claude-view" id="view-claude">
        <div class="model-row">
            <div class="model-switcher">
                <input type="radio" name="model" id="m-haiku" value="claude-haiku-3-5-20241022">
                <label for="m-haiku">Haiku 3.5</label>
                <input type="radio" name="model" id="m-sonnet" value="claude-sonnet-4-20250514" checked>
                <label for="m-sonnet">Sonnet 4</label>
                <input type="radio" name="model" id="m-opus" value="claude-opus-4-20250514">
                <label for="m-opus">Opus 4</label>
            </div>
        </div>

        <div class="history" id="history"></div>

        <div class="input-area">
            <textarea id="prompt" placeholder="Ask Claude something..." rows="1" autofocus></textarea>
            <button class="send-btn" id="send" onclick="sendClaude()">Send</button>
        </div>
    </div>

    <!-- ── Rides View ── -->
    <div class="view rides-view" id="view-rides">
        <div class="rides-card">
            <h2>Route</h2>
            <div class="route-fields">
                <div class="route-field">
                    <div class="dot origin"></div>
                    <input type="text" id="origin" placeholder="Pickup address" value="{{ default_origin }}">
                </div>
                <div class="route-field">
                    <div class="dot dest"></div>
                    <input type="text" id="destination" placeholder="Destination" value="{{ default_dest }}">
                </div>
            </div>
            <button class="estimate-btn" id="estimateBtn" onclick="getEstimate()">Get Estimate</button>
        </div>

        <div id="routeInfo" class="route-info" style="display:none;"></div>

        <div id="rideResults" style="display:none;">
            <div class="rides-card">
                <h2>Choose a ride</h2>
                <div class="ride-options" id="rideOptions"></div>
            </div>
            <button class="send-to-display-btn" id="sendDisplayBtn" onclick="sendRideToDisplay()">Send to Display</button>
            <div class="ride-status" id="rideStatus"></div>
        </div>
    </div>

    <div class="footer">
        ESP32: <span id="espIp">{{ esp32_ip }}</span>
    </div>

    <script>
        /* ── Tabs ── */
        function switchTab(name) {
            document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
            document.querySelectorAll('.tab-bar button').forEach(b => b.classList.remove('active'));
            document.getElementById('view-' + name).classList.add('active');
            event.target.classList.add('active');
        }

        /* ── Claude chat ── */
        const promptEl = document.getElementById('prompt');
        const sendBtn = document.getElementById('send');
        const historyEl = document.getElementById('history');
        const sessionTokensEl = document.getElementById('sessionTokens');
        let totalInput = 0, totalOutput = 0, totalCost = 0;

        function getModel() { return document.querySelector('input[name="model"]:checked').value; }

        function updateSessionUsage() {
            if (totalInput === 0) { sessionTokensEl.textContent = ''; return; }
            sessionTokensEl.innerHTML =
                `<strong>${(totalInput + totalOutput).toLocaleString()}</strong> tok · <strong>$${totalCost.toFixed(4)}</strong>`;
        }

        promptEl.addEventListener('input', () => {
            promptEl.style.height = 'auto';
            promptEl.style.height = Math.min(promptEl.scrollHeight, 120) + 'px';
        });
        promptEl.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendClaude(); }
        });

        async function sendClaude() {
            const prompt = promptEl.value.trim();
            if (!prompt) return;
            const model = getModel();
            promptEl.value = ''; promptEl.style.height = 'auto'; sendBtn.disabled = true;

            const entry = document.createElement('div');
            entry.className = 'entry';
            entry.innerHTML = `
                <div class="prompt"><strong>You:</strong> ${esc(prompt)}</div>
                <div class="response"><span class="spinner"></span>Thinking...</div>`;
            historyEl.appendChild(entry);
            historyEl.scrollTop = historyEl.scrollHeight;

            try {
                const res = await fetch('/ask', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ prompt, model })
                });
                const data = await res.json();
                if (data.error) {
                    entry.querySelector('.response').textContent = 'Error: ' + data.error;
                    entry.innerHTML += `<div class="meta"><span class="display-status error">Failed</span></div>`;
                } else {
                    entry.querySelector('.response').textContent = data.response;
                    const u = data.usage || {};
                    totalInput += u.input_tokens || 0;
                    totalOutput += u.output_tokens || 0;
                    totalCost += u.cost || 0;
                    updateSessionUsage();
                    const tok = u.input_tokens ? `${u.input_tokens.toLocaleString()} in · ${u.output_tokens.toLocaleString()} out · $${u.cost.toFixed(4)}` : '';
                    const dc = data.display_sent ? 'sent' : 'error';
                    const dt = data.display_sent ? 'Sent to display' : 'Display: ' + (data.display_error || 'error');
                    entry.innerHTML += `<div class="meta"><span class="display-status ${dc}">${esc(dt)}</span><span class="usage" style="color:#C4B8AE">${tok}</span></div>`;
                }
            } catch (err) {
                entry.querySelector('.response').textContent = 'Network error: ' + err.message;
                entry.innerHTML += `<div class="meta"><span class="display-status error">Failed</span></div>`;
            }
            sendBtn.disabled = false; promptEl.focus();
            historyEl.scrollTop = historyEl.scrollHeight;
        }

        /* ── Rides ── */
        let selectedRide = null;
        let rideData = null;

        async function getEstimate() {
            const origin = document.getElementById('origin').value.trim();
            const dest = document.getElementById('destination').value.trim();
            if (!origin || !dest) return;

            document.getElementById('estimateBtn').disabled = true;
            document.getElementById('estimateBtn').textContent = 'Calculating...';
            document.getElementById('rideResults').style.display = 'none';

            try {
                const res = await fetch('/rides/estimate', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ origin, destination: dest })
                });
                const data = await res.json();
                if (data.error) { alert('Error: ' + data.error); return; }

                rideData = data;
                document.getElementById('routeInfo').style.display = 'block';
                document.getElementById('routeInfo').textContent =
                    `${data.distance_mi.toFixed(1)} mi · ~${data.duration_min} min drive`;

                const container = document.getElementById('rideOptions');
                container.innerHTML = '';
                const icons = { UberX: '🚗', Comfort: '✨', UberXL: '🚙', Black: '🖤' };
                data.estimates.forEach((e, i) => {
                    const div = document.createElement('div');
                    div.className = 'ride-option' + (i === 0 ? ' selected' : '');
                    div.onclick = () => selectRide(div, e.product);
                    div.innerHTML = `
                        <div class="ride-icon">${icons[e.product] || '🚗'}</div>
                        <div class="ride-info">
                            <div class="ride-name">${e.product}</div>
                            <div class="ride-time">${data.duration_min} min</div>
                        </div>
                        <div class="ride-price">$${e.low.toFixed(0)}–${e.high.toFixed(0)}</div>`;
                    container.appendChild(div);
                });
                if (data.estimates.length > 0) selectedRide = data.estimates[0].product;
                document.getElementById('rideResults').style.display = 'block';
            } catch (err) {
                alert('Error: ' + err.message);
            } finally {
                document.getElementById('estimateBtn').disabled = false;
                document.getElementById('estimateBtn').textContent = 'Get Estimate';
            }
        }

        function selectRide(el, product) {
            document.querySelectorAll('.ride-option').forEach(o => o.classList.remove('selected'));
            el.classList.add('selected');
            selectedRide = product;
        }

        async function sendRideToDisplay() {
            if (!rideData || !selectedRide) return;
            const btn = document.getElementById('sendDisplayBtn');
            const status = document.getElementById('rideStatus');
            btn.disabled = true;

            const est = rideData.estimates.find(e => e.product === selectedRide);
            const origin = document.getElementById('origin').value.trim();
            const dest = document.getElementById('destination').value.trim();
            const text = `${selectedRide} Estimate\\n\\n` +
                `${origin}  -->  ${dest}\\n\\n` +
                `Distance: ${rideData.distance_mi.toFixed(1)} mi\\n` +
                `Drive time: ~${rideData.duration_min} min\\n\\n` +
                `Estimated fare: $${est.low.toFixed(0)} - $${est.high.toFixed(0)}`;

            try {
                const res = await fetch('/display/send', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ text })
                });
                const data = await res.json();
                status.className = 'ride-status ' + (data.sent ? 'sent' : 'error');
                status.textContent = data.sent ? 'Sent to display' : 'Display: ' + data.error;
            } catch (err) {
                status.className = 'ride-status error';
                status.textContent = err.message;
            }
            btn.disabled = false;
        }

        /* ── Daily ── */
        async function generateDaily() {
            const btn = document.getElementById('generateBtn');
            const reshuffle = document.getElementById('reshuffleBtn');
            const content = document.getElementById('dailyContent');
            const meta = document.getElementById('dailyMeta');
            btn.disabled = true; btn.textContent = 'Generating...';
            content.className = 'daily-content'; content.textContent = '';
            content.innerHTML = '<span class="spinner"></span>Claude is choosing...';
            meta.textContent = '';

            try {
                const res = await fetch('/daily/generate', { method: 'POST' });
                const data = await res.json();
                if (data.error) {
                    content.className = 'daily-content empty';
                    content.textContent = 'Error: ' + data.error;
                } else {
                    content.className = 'daily-content';
                    content.textContent = data.text;
                    const dc = data.display_sent ? 'sent' : 'error';
                    const dt = data.display_sent ? 'Sent to display' : (data.display_error || 'Display error');
                    meta.innerHTML = `<span class="${dc}">${esc(dt)}</span>`;
                    reshuffle.style.display = 'inline-block';
                    btn.style.display = 'none';
                    loadDailyHistory();
                }
            } catch (err) {
                content.className = 'daily-content empty';
                content.textContent = 'Error: ' + err.message;
            }
            btn.disabled = false; btn.textContent = 'Generate';
        }

        async function loadDailyHistory() {
            try {
                const res = await fetch('/daily/history');
                const data = await res.json();
                if (data.history && data.history.length > 0) {
                    const section = document.getElementById('dailyHistorySection');
                    const list = document.getElementById('dailyHistoryList');
                    section.style.display = 'block';
                    list.innerHTML = data.history.slice(0, 7).map(h =>
                        `<div class="daily-history-item">
                            <div class="date">${h.date}</div>
                            <div>${esc(h.text.substring(0, 120))}${h.text.length > 120 ? '...' : ''}</div>
                        </div>`
                    ).join('');

                    // If we already have today's entry, show it
                    const today = new Date().toISOString().split('T')[0];
                    const todayEntry = data.history.find(h => h.date === today);
                    if (todayEntry) {
                        document.getElementById('dailyContent').className = 'daily-content';
                        document.getElementById('dailyContent').textContent = todayEntry.text;
                        document.getElementById('reshuffleBtn').style.display = 'inline-block';
                        document.getElementById('generateBtn').style.display = 'none';
                    }
                }
            } catch (e) {}
        }

        let scheduleInterval = null;
        function toggleSchedule() {
            const on = document.getElementById('dailyToggle').checked;
            const timeEl = document.getElementById('dailyTime');
            if (on) {
                checkSchedule();
                scheduleInterval = setInterval(checkSchedule, 60000); // check every minute
            } else if (scheduleInterval) {
                clearInterval(scheduleInterval);
                scheduleInterval = null;
            }
        }

        function checkSchedule() {
            const timeEl = document.getElementById('dailyTime');
            const [h, m] = timeEl.value.split(':').map(Number);
            const now = new Date();
            if (now.getHours() === h && now.getMinutes() === m) {
                const today = new Date().toISOString().split('T')[0];
                if (!document.getElementById('dailyContent').dataset.date ||
                    document.getElementById('dailyContent').dataset.date !== today) {
                    generateDaily();
                    document.getElementById('dailyContent').dataset.date = today;
                }
            }
        }

        // Load history on startup
        loadDailyHistory();

        /* ── Ships ── */
        async function scanBay() {
            const btn = document.getElementById('scanBtn');
            const content = document.getElementById('shipsContent');
            const meta = document.getElementById('shipsMeta');
            btn.disabled = true; btn.textContent = 'Scanning (~45s)...';
            content.className = 'ships-content';
            content.innerHTML = '<span class="spinner"></span>Listening for AIS signals...';
            meta.textContent = '';

            try {
                const res = await fetch('/ships/generate', { method: 'POST' });
                const data = await res.json();
                if (data.error) {
                    content.className = 'ships-content empty';
                    content.textContent = 'Error: ' + data.error;
                } else {
                    content.className = 'ships-content';
                    content.textContent = data.text;
                    const dc = data.display_sent ? 'sent' : 'error';
                    const dt = data.display_sent ? 'Sent to display' : (data.display_error || 'Display not updated');
                    meta.innerHTML = `<span class="${dc}">${esc(dt)}</span> · ${data.vessel_count} vessels detected`;
                }
            } catch (err) {
                content.className = 'ships-content empty';
                content.textContent = 'Error: ' + err.message;
            }
            btn.disabled = false; btn.textContent = 'Scan Bay';
        }

        // Load latest ship data on startup
        async function loadLatestShips() {
            try {
                const res = await fetch('/ships/latest');
                const data = await res.json();
                if (data.text) {
                    document.getElementById('shipsContent').className = 'ships-content';
                    document.getElementById('shipsContent').textContent = data.text;
                }
            } catch (e) {}
        }
        loadLatestShips();

        /* ── App Switcher ── */
        async function loadApps() {
            try {
                const res = await fetch('/api/apps');
                const data = await res.json();
                const select = document.getElementById('activeApp');
                select.innerHTML = '';
                for (const [name, info] of Object.entries(data.apps)) {
                    const opt = document.createElement('option');
                    opt.value = name;
                    opt.textContent = info.display_name;
                    if (name === data.active) opt.selected = true;
                    select.appendChild(opt);
                }
            } catch (e) {}
        }
        loadApps();

        async function setActiveApp(name) {
            try {
                await fetch('/api/apps/active', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ app: name })
                });
            } catch (e) {}
        }

        function esc(t) { const d = document.createElement('div'); d.textContent = t; return d.innerHTML; }
    </script>
</body>
</html>
"""

app = Flask(__name__)
esp32_ip = DEFAULT_ESP32_IP
default_origin = "Your Address, City"
default_dest = "Joe DiMaggio Playground, North Beach, SF"


@app.route("/")
def index():
    return render_template_string(
        HTML_TEMPLATE, esp32_ip=esp32_ip,
        default_origin=default_origin, default_dest=default_dest,
    )


@app.route("/ask", methods=["POST"])
def ask():
    data = request.get_json()
    prompt = data.get("prompt", "").strip()
    model = data.get("model", "claude-sonnet-4-20250514")
    if not prompt:
        return jsonify({"error": "empty prompt"}), 400
    if model not in MODELS:
        return jsonify({"error": f"unknown model: {model}"}), 400

    if not os.environ.get("ANTHROPIC_API_KEY"):
        return jsonify({"error": "ANTHROPIC_API_KEY not set"}), 401
    try:
        client = anthropic.Anthropic()
        message = client.messages.create(
            model=model, max_tokens=1024, system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        response_text = message.content[0].text
    except anthropic.AuthenticationError:
        return jsonify({"error": "Invalid ANTHROPIC_API_KEY"}), 401
    except anthropic.APIError as e:
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    usage_data = {}
    if message.usage:
        inp, out = message.usage.input_tokens, message.usage.output_tokens
        mi = MODELS[model]
        cost = (inp / 1e6) * mi["input_cost"] + (out / 1e6) * mi["output_cost"]
        usage_data = {"input_tokens": inp, "output_tokens": out, "cost": round(cost, 6)}

    display_sent, display_error = _send_to_esp32(response_text)

    return jsonify({
        "response": response_text,
        "display_sent": display_sent, "display_error": display_error,
        "usage": usage_data,
    })


@app.route("/rides/estimate", methods=["POST"])
def rides_estimate():
    data = request.get_json()
    origin = data.get("origin", "").strip()
    destination = data.get("destination", "").strip()
    if not origin or not destination:
        return jsonify({"error": "origin and destination required"}), 400

    # Geocode both addresses
    try:
        o_coords = _geocode(origin)
        d_coords = _geocode(destination)
    except Exception as e:
        return jsonify({"error": f"Geocoding failed: {e}"}), 400

    # Get route from OSRM
    try:
        route_url = (
            f"http://router.project-osrm.org/route/v1/driving/"
            f"{o_coords[1]},{o_coords[0]};{d_coords[1]},{d_coords[0]}"
            f"?overview=false"
        )
        r = http_requests.get(route_url, timeout=10)
        r.raise_for_status()
        route = r.json()
        if route.get("code") != "Ok":
            return jsonify({"error": "Could not calculate route"}), 400
        leg = route["routes"][0]["legs"][0]
        distance_m = leg["distance"]
        duration_s = leg["duration"]
    except Exception as e:
        return jsonify({"error": f"Routing failed: {e}"}), 400

    distance_mi = distance_m / 1609.344
    duration_min = round(duration_s / 60)

    # Calculate fare estimates
    estimates = []
    for product, rates in UBER_PRODUCTS.items():
        fare = rates["base"] + rates["per_mile"] * distance_mi + rates["per_min"] * duration_min + rates["booking"]
        fare = max(fare, rates["min_fare"])
        # Surge range: low = 0.9x, high = 1.3x
        estimates.append({
            "product": product,
            "low": round(fare * 0.9, 2),
            "high": round(fare * 1.3, 2),
        })

    return jsonify({
        "distance_mi": round(distance_mi, 2),
        "duration_min": duration_min,
        "estimates": estimates,
    })


@app.route("/daily/generate", methods=["POST"])
def daily_generate():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return jsonify({"error": "ANTHROPIC_API_KEY not set"}), 401

    # Build context of recent picks so Claude doesn't repeat
    _load_daily_log()
    recent = "\n".join([f"- {h['text'][:80]}" for h in daily_history[-10:]])
    user_msg = f"Today is {datetime.now().strftime('%A, %B %d, %Y')}. Pick something for the display."
    if recent:
        user_msg += f"\n\nHere are your recent picks (do NOT repeat any of these):\n{recent}"

    try:
        client = anthropic.Anthropic()
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            system=DAILY_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = message.content[0].text.strip()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # Save to log
    entry = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time": datetime.now().strftime("%H:%M"),
        "text": text,
    }
    daily_history.append(entry)
    _save_daily_log()

    # Write content file for slow-mode polling
    with open(DAILY_CONTENT_PATH, "w") as f:
        json.dump({"text": text}, f, indent=2)

    # Send to display
    sent, error = _send_to_esp32(text)

    return jsonify({
        "text": text,
        "display_sent": sent,
        "display_error": error,
    })


@app.route("/daily/history")
def daily_history_endpoint():
    _load_daily_log()
    return jsonify({"history": list(reversed(daily_history[-14:]))})


@app.route("/api/content")
def api_content():
    """Serve the active app's content for slow-mode ESP32 polling."""
    data = app_registry.get_active_content()
    if data:
        return jsonify(data)
    return "", 204


@app.route("/api/apps")
def api_apps():
    """List all apps and which is active."""
    return jsonify({
        "apps": app_registry.list_apps(),
        "active": app_registry.get_active_app(),
    })


@app.route("/api/apps/active", methods=["POST"])
def api_set_active():
    """Set the active app."""
    data = request.get_json()
    name = data.get("app", "")
    try:
        app_registry.set_active_app(name)
        return jsonify({"ok": True, "active": name})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/display/send", methods=["POST"])
def display_send():
    data = request.get_json()
    text = data.get("text", "")
    if not text:
        return jsonify({"sent": False, "error": "empty text"}), 400
    sent, error = _send_to_esp32(text)
    return jsonify({"sent": sent, "error": error})


@app.route("/ships/generate", methods=["POST"])
def ships_generate():
    """Run AIS collection and write ship content."""
    api_key = os.environ.get("AISSTREAM_API_KEY")
    if not api_key:
        return jsonify({"error": "AISSTREAM_API_KEY not set"}), 401
    try:
        text, ships = generate_ship_content(api_key)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    sent, error = _send_to_esp32(text)

    return jsonify({
        "text": text,
        "vessel_count": len(ships),
        "display_sent": sent,
        "display_error": error,
    })


@app.route("/ships/latest")
def ships_latest():
    """Serve the last generated ship data."""
    path = app_registry.get_app_content_path("ships")
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return jsonify(data)
    except (FileNotFoundError, json.JSONDecodeError):
        return jsonify({})


def _geocode(address):
    """Geocode an address using Nominatim. Returns (lat, lon)."""
    r = http_requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": address, "format": "json", "limit": 1},
        headers={"User-Agent": "claude-eink-display/1.0"},
        timeout=10,
    )
    r.raise_for_status()
    results = r.json()
    if not results:
        raise ValueError(f"Could not find: {address}")
    return float(results[0]["lat"]), float(results[0]["lon"])


def _send_to_esp32(text):
    """Send text to ESP32 display. Returns (sent: bool, error: str|None)."""
    try:
        t = text[:MAX_DISPLAY_CHARS]
        if len(text) > MAX_DISPLAY_CHARS:
            t = t[:MAX_DISPLAY_CHARS - 3] + "..."
        resp = http_requests.post(
            f"http://{esp32_ip}/display", json={"text": t}, timeout=10,
        )
        resp.raise_for_status()
        return True, None
    except http_requests.ConnectionError:
        return False, f"Could not connect to ESP32 at {esp32_ip}"
    except http_requests.Timeout:
        return False, f"Connection to {esp32_ip} timed out"
    except http_requests.HTTPError as e:
        return False, f"{e.response.status_code}: {e.response.text}"


def _load_daily_log():
    """Load daily history from disk."""
    global daily_history
    try:
        with open(DAILY_LOG_PATH, "r") as f:
            daily_history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        daily_history = []


def _save_daily_log():
    """Save daily history to disk."""
    with open(DAILY_LOG_PATH, "w") as f:
        json.dump(daily_history, f, indent=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Claude E-Ink Display")
    parser.add_argument("--ip", default=DEFAULT_ESP32_IP, help="ESP32 IP address")
    parser.add_argument("--port", type=int, default=8080, help="Server port")
    parser.add_argument("--browser", action="store_true", help="Open in browser instead of native window")
    parser.add_argument("--origin", default=default_origin, help="Default pickup address")
    parser.add_argument("--dest", default=default_dest, help="Default destination")
    args = parser.parse_args()

    esp32_ip = args.ip
    default_origin = args.origin
    default_dest = args.dest

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Warning: ANTHROPIC_API_KEY not set. Set it with:")
        print('  export ANTHROPIC_API_KEY="sk-ant-..."')

    if args.browser:
        print(f"\nClaude E-Ink Display")
        print(f"ESP32: {esp32_ip}")
        print(f"Open: http://localhost:{args.port}\n")
        app.run(host="0.0.0.0", port=args.port, debug=False)
    else:
        def start_server():
            app.run(host="0.0.0.0", port=args.port, debug=False, use_reloader=False)

        server_thread = threading.Thread(target=start_server, daemon=True)
        server_thread.start()

        # Print phone access URL
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            print(f"\nPhone access: http://{local_ip}:{args.port}")
        except Exception:
            pass

        # Set dock icon on macOS
        try:
            from AppKit import NSApplication, NSImage
            ns_app = NSApplication.sharedApplication()
            icon = NSImage.alloc().initWithContentsOfFile_(ICON_PATH)
            if icon:
                ns_app.setApplicationIconImage_(icon)
        except Exception:
            pass

        webview.create_window(
            "Claude E-Ink",
            f"http://127.0.0.1:{args.port}",
            width=680,
            height=760,
            min_size=(480, 400),
        )
        webview.start()
