#!/usr/bin/env python3
"""
DP104 Dashboard Tray

Important safety changes vs v0.1:
- NO automatic LCD page-switch HID commands.
- NO multi-frame upload in the first test path.
- Keeps the reference 0.320 s inter-frame pacing when multi-frame is ever used.
- Adds --diagnose mode that performs ZERO HID writes.
- Adds --test-display mode that performs exactly ONE pixel-buffer upload.
- Battery is explicitly reported as unsupported until its HID packet is mapped.

Usage:
    pip install hidapi

    # 1) Safe diagnostics; does not write to the keyboard:
    python dp104_dashboard_safe.py --diagnose

    # 2) Only after diagnostics look good:
    #    In the official TickType configurator, select CUSTOM pixel page,
    #    then CLOSE the configurator/browser tab completely.
    python dp104_dashboard_safe.py --test-display

    # 3) Test one real weather page:
    python dp104_dashboard_safe.py --test-weather

    # 4) Run rotating pages:
    python dp104_dashboard_safe.py --run

Weather configuration:
    Not included in the public source. See config.example.json.
"""

from __future__ import annotations

import argparse
import colorsys
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import ctypes
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from pathlib import Path

try:
    from pynput import keyboard as pynput_keyboard
except ImportError:
    pynput_keyboard = None

try:
    import pystray
    from pystray import MenuItem as TrayItem
    from PIL import Image, ImageDraw
except ImportError:
    pystray = None
    TrayItem = None
    Image = None
    ImageDraw = None

try:
    import hid
except ImportError as exc:
    raise SystemExit("缺少依赖：pip install hidapi") from exc


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

VID = 0xE560
PID = 0xE104
RAW_USAGE_PAGE = 0xFF60

W = 24
H = 8
FRAME_BYTES = W * H * 3

# Privacy-safe weather configuration.
# No personal location is embedded in the source repository.
# Configure these with environment variables or %APPDATA%\\DP104Dashboard\\config.json.
_APPDATA_ROOT = Path(os.getenv("APPDATA") or Path.home())
_USER_CONFIG_DIR = _APPDATA_ROOT / "DP104Dashboard"
_USER_CONFIG_FILE = _USER_CONFIG_DIR / "config.json"


def _load_user_config():
    try:
        if _USER_CONFIG_FILE.exists():
            raw = json.loads(_USER_CONFIG_FILE.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
    except Exception:
        pass
    return {}


_USER_CONFIG = _load_user_config()

LAT = os.getenv("DP104_LAT") or _USER_CONFIG.get("weather_latitude")
LON = os.getenv("DP104_LON") or _USER_CONFIG.get("weather_longitude")
WEATHER_TZ = os.getenv("DP104_TZ") or _USER_CONFIG.get("weather_timezone") or "UTC"
LOCATION_NAME = (
    os.getenv("DP104_LOCATION_LABEL")
    or _USER_CONFIG.get("location_label")
    or "DP104"
)


def weather_configured():
    return LAT not in (None, "") and LON not in (None, "")

PAGE_SECONDS = float(os.getenv("DP104_PAGE_SECONDS", "8"))
MIN_SEND_GAP = 5.0

BLACK = (0, 0, 0)
WHITE = (240, 240, 240)
DIM = (70, 80, 95)
BLUE = (70, 150, 255)
CYAN = (60, 220, 230)
GREEN = (70, 220, 110)
YELLOW = (255, 220, 70)
ORANGE = (255, 150, 40)
RED = (255, 70, 70)


# ---------------------------------------------------------------------------
# Tiny font
# ---------------------------------------------------------------------------

FONT_3X5 = {
    "0": ["###", "#.#", "#.#", "#.#", "###"],
    "1": [".#.", "##.", ".#.", ".#.", "###"],
    "2": ["###", "..#", "###", "#..", "###"],
    "3": ["###", "..#", ".##", "..#", "###"],
    "4": ["#.#", "#.#", "###", "..#", "..#"],
    "5": ["###", "#..", "###", "..#", "###"],
    "6": ["###", "#..", "###", "#.#", "###"],
    "7": ["###", "..#", ".#.", ".#.", ".#."],
    "8": ["###", "#.#", "###", "#.#", "###"],
    "9": ["###", "#.#", "###", "..#", "###"],
    "A": [".#.", "#.#", "###", "#.#", "#.#"],
    "B": ["##.", "#.#", "##.", "#.#", "##."],
    "C": [".##", "#..", "#..", "#..", ".##"],
    "D": ["##.", "#.#", "#.#", "#.#", "##."],
    "E": ["###", "#..", "##.", "#..", "###"],
    "H": ["#.#", "#.#", "###", "#.#", "#.#"],
    "K": ["#.#", "##.", "#..", "##.", "#.#"],
    "M": ["#.#", "###", "###", "#.#", "#.#"],
    "P": ["##.", "#.#", "##.", "#..", "#.."],
    "T": ["###", ".#.", ".#.", ".#.", ".#."],
    "W": ["#.#", "#.#", "###", "###", "#.#"],
    "?": ["###", "..#", ".#.", "...", ".#."],
    "-": ["...", "...", "###", "...", "..."],
    " ": ["...", "...", "...", "...", "..."],
}

FONT_3X3 = {
    "0": ["###", "#.#", "###"],
    "1": [".#.", ".#.", ".#."],
    "2": ["##.", ".#.", "###"],
    "3": ["##.", ".##", "##."],
    "4": ["#.#", "###", "..#"],
    "5": ["###", "##.", ".##"],
    "6": ["#..", "###", "###"],
    "7": ["###", "..#", "..#"],
    "8": ["###", "###", "###"],
    "9": ["###", "###", "..#"],
    "G": [".##", "#..", ".##"],
    "P": ["##.", "###", "#.."],
    "T": ["###", ".#.", ".#."],
    "H": ["#.#", "###", "#.#"],
    # V-shaped bottom makes W visually distinct from H/N on a 3x3 matrix.
    "W": ["#.#", "#.#", ".#."],
    "K": ["#.#", "##.", "#.#"],
    "C": [".##", "#..", ".##"],
    "B": ["##.", "###", "##."],
    "?": ["##.", ".#.", ".#."],
    " ": ["...", "...", "..."],
}

BIG5X7 = {
    "0": [
        ".###.",
        "#...#",
        "#..##",
        "#.#.#",
        "##..#",
        "#...#",
        ".###.",
    ],
    "1": [
        "..#..",
        ".##..",
        "..#..",
        "..#..",
        "..#..",
        "..#..",
        ".###.",
    ],
    "2": [
        ".###.",
        "#...#",
        "....#",
        "...#.",
        "..#..",
        ".#...",
        "#####",
    ],
    "3": [
        "####.",
        "....#",
        "....#",
        ".###.",
        "....#",
        "....#",
        "####.",
    ],
    "4": [
        "...#.",
        "..##.",
        ".#.#.",
        "#..#.",
        "#####",
        "...#.",
        "...#.",
    ],
    "5": [
        "#####",
        "#....",
        "#....",
        "####.",
        "....#",
        "....#",
        "####.",
    ],
    "6": [
        ".###.",
        "#....",
        "#....",
        "####.",
        "#...#",
        "#...#",
        ".###.",
    ],
    "7": [
        "#####",
        "....#",
        "...#.",
        "..#..",
        ".#...",
        ".#...",
        ".#...",
    ],
    "8": [
        ".###.",
        "#...#",
        "#...#",
        ".###.",
        "#...#",
        "#...#",
        ".###.",
    ],
    "9": [
        ".###.",
        "#...#",
        "#...#",
        ".####",
        "....#",
        "....#",
        ".###.",
    ],
    "-": [
        ".....",
        ".....",
        ".....",
        "#####",
        ".....",
        ".....",
        ".....",
    ],
}


LABEL5X7 = {
    "W": [
        "#...#",
        "#...#",
        "#...#",
        "#.#.#",
        "#.#.#",
        "##.##",
        ".#.#.",
    ],
    "K": [
        "#...#",
        "#..#.",
        "#.#..",
        "##...",
        "#.#..",
        "#..#.",
        "#...#",
    ],
}

def draw_label5x7(frame, text, x, y, color=CYAN, spacing=1):
    cur = x
    for ch in str(text).upper():
        pat = LABEL5X7.get(ch)
        if not pat:
            continue
        for yy, row in enumerate(pat):
            for xx, bit in enumerate(row):
                if bit == "#":
                    px(frame, cur + xx, y + yy, color)
        cur += 5 + spacing
    return cur

def draw_big_number(frame, text, x, y, color=WHITE, spacing=1):
    cur = x
    for ch in str(text):
        pat = BIG5X7.get(ch)
        if not pat:
            continue
        for yy, row in enumerate(pat):
            for xx, bit in enumerate(row):
                if bit == "#":
                    px(frame, cur + xx, y + yy, color)
        cur += 5 + spacing
    return cur


def blank():
    return [BLACK] * (W * H)


def px(frame, x, y, color):
    if 0 <= x < W and 0 <= y < H:
        frame[y * W + x] = color


def draw_text(frame, text, x, y, color=WHITE, tiny=False, spacing=1):
    font = FONT_3X3 if tiny else FONT_3X5
    height = 3 if tiny else 5
    cur = x
    for ch in str(text).upper():
        pat = font.get(ch, font["?"])
        for yy in range(height):
            for xx in range(3):
                if pat[yy][xx] == "#":
                    px(frame, cur + xx, y + yy, color)
        cur += 3 + spacing
    return cur


def draw_bar(frame, x, y, width, percent, color):
    percent = max(0, min(100, float(percent)))
    fill = round(width * percent / 100)
    for i in range(width):
        px(frame, x + i, y, color if i < fill else DIM)


def remaining_color(p):
    if p <= 15:
        return RED
    if p <= 35:
        return ORANGE
    return GREEN


# ---------------------------------------------------------------------------
# HID: diagnostics and SAFE send
# ---------------------------------------------------------------------------

def dp104_interfaces():
    out = []
    for info in hid.enumerate():
        if info.get("vendor_id") == VID and info.get("product_id") == PID:
            out.append(info)
    return out


def find_pixel_interface():
    devs = dp104_interfaces()
    for info in devs:
        if info.get("interface_number") == 1:
            return info
    for info in devs:
        if info.get("usage_page") == RAW_USAGE_PAGE:
            return info
    return None


def rgb_to_hsv_bytes(rgb):
    r, g, b = rgb
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    hh = int(h * 255)
    ss = int(s * 255)
    vv = int(v * 255)
    # DP104 firmware quirk documented by the community project:
    if 0 < vv < 20 and ss > 30:
        vv = 20
    return hh, ss, vv


def frame_to_hsv(frame):
    data = []
    for rgb in frame:
        data.extend(rgb_to_hsv_bytes(rgb))
    return data


def be32(n):
    return [(n >> 24) & 0xFF, (n >> 16) & 0xFF, (n >> 8) & 0xFF, n & 0xFF]


_last_send = 0.0
_hid_bus_lock = threading.Lock()


def send_frames_safe(frames, fps=1):
    """
    Mirrors the community project's proven pixel upload sequence.
    Deliberately does NOT issue any LCD page-switch command.
    """
    global _last_send

    if not frames:
        raise ValueError("No frames")
    if len(frames) > 255:
        raise ValueError("Too many frames")

    info = find_pixel_interface()
    if not info:
        raise RuntimeError("找不到 DP104 MI_01 / Raw HID 点阵接口")

    with _hid_bus_lock:
        gap = time.monotonic() - _last_send
        if _last_send and gap < MIN_SEND_GAP:
            time.sleep(MIN_SEND_GAP - gap)

        dev = hid.device()
        try:
            dev.open_path(info["path"])
            dev.set_nonblocking(False)

            encoded = [frame_to_hsv(f) for f in frames]

            # Allocate animation buffer.
            hdr = [0xD1, 0x30, len(encoded), fps, H, W] + [0] * 26
            assert len(hdr) == 32
            dev.write([0x00] + hdr)

            ack = dev.read(32, timeout_ms=2000)
            if not ack:
                raise RuntimeError("0xD1/0x30 后未收到 ACK；停止发送，避免继续冲击固件")

            # The reference implementation waits before frame chunks.
            time.sleep(1.0)

            for fi, frame_data in enumerate(encoded):
                offset = 0
                while offset < FRAME_BYTES:
                    chunk = frame_data[offset : offset + 25]
                    global_offset = fi * FRAME_BYTES + offset
                    off = be32(global_offset)
                    pkt = [0xD1, 0x31, *off, len(chunk), *chunk]
                    pkt += [0] * (32 - len(pkt))
                    assert len(pkt) == 32
                    dev.write([0x00] + pkt)
                    offset += len(chunk)
                    time.sleep(0.002)

                # Critical pacing used by MMSWaM between frames.
                if fi < len(encoded) - 1:
                    time.sleep(0.320)

            _last_send = time.monotonic()
        finally:
            try:
                dev.close()
            except Exception:
                pass



# ---------------------------------------------------------------------------
# Native DP104 scrolling-text protocol
#
# This follows the scrolling-text packet shape used by MMSWaM.
# Safety choice: this script NEVER switches the LCD page automatically.
# Manually select Scrolling Message / 滚动文本 in the official configurator,
# close the configurator, then run --test-scroll or --scroll.
# ---------------------------------------------------------------------------

MAX_SCROLL_TEXT_LEN = 30


def make_scroll_text_packet(block, offset, text_bytes):
    payload = bytearray(32)
    payload[0] = 0x07
    payload[1] = 0x1A
    payload[2] = 0x05
    payload[3] = block
    payload[4] = offset
    payload[5] = len(text_bytes)
    payload[6:6 + len(text_bytes)] = text_bytes
    return bytes(payload)


def sanitize_scroll_text(text):
    """
    DP104 native scrolling text is safest with plain ASCII.
    Keep the message short and readable on the 24x8 display.
    """
    replacements = {
        "—": "-", "–": "-", "…": "",
        "°": "", "℃": "C",
    }
    for src_ch, dst_ch in replacements.items():
        text = text.replace(src_ch, dst_ch)
    text = text.encode("ascii", errors="ignore").decode("ascii")
    text = " ".join(text.split())
    return text.upper()[:MAX_SCROLL_TEXT_LEN]




def send_scroll_text_safe(message):
    """
    Send ONE native scrolling-text update.

    Important:
    - No pixel-buffer allocation.
    - No LCD page-switch command.
    - Uses only the already-confirmed DP104 Raw HID interface (MI_01).
    - Writes block 0 and clears blocks 1..4.
    """
    info = find_pixel_interface()
    if not info:
        raise RuntimeError("找不到 DP104 MI_01 / Raw HID 接口")

    message = sanitize_scroll_text(message)
    if not message:
        raise ValueError("滚动文本为空")

    with _hid_bus_lock:
        dev = hid.device()
        try:
            dev.open_path(info["path"])

            def send_block(block, value):
                enc = sanitize_scroll_text(value).encode("ascii", errors="replace")
                enc = enc[:MAX_SCROLL_TEXT_LEN]
                pad = enc + b"\x00" * (MAX_SCROLL_TEXT_LEN - len(enc))

                # First 26 bytes.
                dev.write(
                    [0x00]
                    + list(make_scroll_text_packet(block, 0x00, pad[0:26]))
                )
                time.sleep(0.03)

                # Remaining 4 bytes.
                dev.write(
                    [0x00]
                    + list(make_scroll_text_packet(block, 0x1A, pad[26:30]))
                )
                time.sleep(0.03)

            send_block(0, message)
            for block in (1, 2, 3, 4):
                send_block(block, "")

        finally:
            try:
                dev.close()
            except Exception:
                pass


PAGE_TYPING = 1
PAGE_SCROLL = 6
PAGE_CUSTOM = 2
TYPING_IDLE_SECONDS = float(os.getenv("DP104_TYPING_IDLE", "5.0"))


def switch_display_page_safe(page):
    """
    Switch DP104 display page using packets captured from the official configurator.

    Captured:
      scroll page = 6
      realtime typing page = 1

    Two-packet sequence:
      00 07 1A 02 <page> 00...
      00 09 1A 00 00...

    Uses the same lock as scrolling-text writes so the keyboard never sees
    overlapping HID control traffic from this script.
    """
    info = find_pixel_interface()
    if not info:
        raise RuntimeError("找不到 DP104 MI_01 / Raw HID 接口")

    if page not in (PAGE_TYPING, PAGE_SCROLL, 2):
        raise ValueError(f"Unsupported page: {page}")

    with _hid_bus_lock:
        dev = hid.device()
        try:
            dev.open_path(info["path"])

            pkt1 = [0x00, 0x07, 0x1A, 0x02, page] + [0x00] * 28
            pkt2 = [0x00, 0x09, 0x1A, 0x00] + [0x00] * 29
            assert len(pkt1) == 33
            assert len(pkt2) == 33

            dev.write(pkt1)
            time.sleep(0.05)
            dev.write(pkt2)
            time.sleep(0.05)
        finally:
            try:
                dev.close()
            except Exception:
                pass


def run_typing_scroll():
    """
    Hybrid mode:
      idle        -> native Scrolling Message page
      any keypress -> Real-time Typing page
      no keypress for N seconds -> back to Scrolling Message page

    Important:
    - Python does NOT render or send individual keys.
    - The DP104 firmware handles real-time key display on page 1.
    - Key listener only changes a timestamp/event.
    - HID page switching happens in this main loop, never in the listener callback.
    """
    if pynput_keyboard is None:
        raise RuntimeError("缺少 pynput：请运行 pip install pynput")

    print("=== DP104 TYPING + SCROLL v2.0 ===")
    print("已确认页面编号：实时输入=1，滚动文本=6")
    print(f"停止敲击 {TYPING_IDLE_SECONDS:.1f} 秒后自动回到滚动文本。")
    print("Ctrl+C 停止。")
    print()

    wx = None
    wx_at = 0.0
    cx = None
    cx_at = 0.0
    last_scroll_message = None

    key_event = threading.Event()
    key_state_lock = threading.Lock()
    last_key_time = 0.0

    def on_press(_key):
        nonlocal last_key_time
        with key_state_lock:
            last_key_time = time.monotonic()
        key_event.set()

    listener = pynput_keyboard.Listener(on_press=on_press)
    listener.start()

    mode = "scroll"
    next_refresh_check = 0.0

    try:
        # Prime data and scrolling text before switching to scroll page.
        now_ts = time.time()

        new_wx = fetch_weather()
        if new_wx.error:
            print(f"[weather] 不可用，本轮省略温度：{new_wx.error}")
            wx = None
            wx_at = now_ts
        else:
            wx = new_wx
            wx_at = now_ts

        new_cx = fetch_codex_desktop_limits()
        if not new_cx.error:
            cx = new_cx
            cx_at = now_ts
        else:
            print(f"[codex] 首次读取失败，先显示 ?：{new_cx.error}")

        message = build_scroll_message(wx, cx)
        print(f"[scroll] {message}")
        send_scroll_text_safe(message)
        last_scroll_message = message

        print("[page] -> SCROLL(6)")
        switch_display_page_safe(PAGE_SCROLL)

        while True:
            now_mono = time.monotonic()

            # Any keypress switches to firmware's real-time typing page.
            if key_event.is_set():
                key_event.clear()
                if mode != "typing":
                    print("[page] keypress -> TYPING(1)")
                    switch_display_page_safe(PAGE_TYPING)
                    mode = "typing"

            # After idle timeout, return to native scrolling page.
            if mode == "typing":
                with key_state_lock:
                    idle_for = now_mono - last_key_time
                if idle_for >= TYPING_IDLE_SECONDS:
                    print(f"[page] idle {idle_for:.1f}s -> SCROLL(6)")
                    switch_display_page_safe(PAGE_SCROLL)
                    mode = "scroll"

            # Refresh data conservatively. Only write scroll text while scroll page
            # is active, so typing is never interrupted by background text writes.
            if now_mono >= next_refresh_check:
                next_refresh_check = now_mono + 1.0
                now_ts = time.time()

                if wx is None or now_ts - wx_at >= 15 * 60:
                    new_wx = fetch_weather()
                    if not new_wx.error:
                        wx = new_wx
                        wx_at = now_ts
                        print(f"[weather] {wx.temp}C code={wx.code}")
                    else:
                        print(f"[weather] 刷新失败，继续旧数据：{new_wx.error}")

                if cx is None or now_ts - cx_at >= 2 * 60:
                    new_cx = fetch_codex_desktop_limits()
                    if not new_cx.error:
                        cx = new_cx
                        cx_at = now_ts
                        if cx.long is not None:
                            print(f"[codex] WK {pct(cx.long)}%")
                    else:
                        print(f"[codex] 刷新失败：{new_cx.error}")

                if mode == "scroll":
                    message = build_scroll_message(wx, cx)
                    if message != last_scroll_message:
                        print(f"[scroll] update {message}")
                        send_scroll_text_safe(message)
                        last_scroll_message = message

            time.sleep(0.05)

    finally:
        try:
            listener.stop()
        except Exception:
            pass

def build_scroll_message(wx, cx):
    """
    Example:
        DP104 29C 16:43 WK63

    The location label is user-configurable and is never hard-coded in the repository.
    Fits under the native 30-character limit.
    """
    now = datetime.now().strftime("%H:%M")

    temp = "?"
    if wx is not None and wx.temp is not None:
        temp = str(int(wx.temp))

    wk = "?"
    if cx is not None and cx.long is not None:
        value = pct(cx.long)
        if value is not None:
            wk = str(int(value))

    parts = [sanitize_scroll_text(LOCATION_NAME)]
    if wx is not None and wx.temp is not None:
        parts.append(f"{temp}C")
    parts.append(now)
    parts.append(f"WK{wk}")
    return " ".join(p for p in parts if p)[:MAX_SCROLL_TEXT_LEN]


def test_native_scroll():
    print("=== DP104 NATIVE SCROLL TEST ===")
    print("注意：本模式不会自动切换 LCD 页面。")
    print("请先在官方 TickType 配置器中切到 Scrolling Message / 滚动文本页面，")
    print("然后完全关闭配置器网页，再运行本测试。")
    print()

    wx = fetch_weather()
    if wx.error:
        print(f"天气不可用，本次滚动将省略温度：{wx.error}")
        wx = None

    cx = fetch_codex_desktop_limits()
    if cx.error:
        print(f"Codex 读取失败，本次用 ? 代替：{cx.error}")
        cx = None

    message = build_scroll_message(wx, cx)
    print(f"发送滚动文本：{message!r}")
    send_scroll_text_safe(message)
    print("已发送一次。键盘应由自身固件持续滚动该文本。")
    print("如果显示正常且键盘按键正常，再使用 --scroll 持续刷新。")
    return 0


def run_native_scroll():
    """
    Continuous native scrolling mode.

    Firmware handles the actual scrolling continuously.
    Python only refreshes the text once per minute:
      - clock changes every minute
      - weather refreshes every 15 min
      - Codex weekly quota refreshes every 2 min

    This is much lighter than repeatedly uploading pixel animation frames.
    """
    print("=== DP104 NATIVE SCROLL v2.0 ===")
    print("内容：自定义标签 + 可选温度 + 时间 + WK周额度")
    print("每 60 秒仅更新一次文本；滚动动画由键盘固件自己持续执行。")
    print("不会自动切换 LCD 页面。Ctrl+C 停止。")
    print()

    wx = None
    wx_at = 0.0
    cx = None
    cx_at = 0.0
    last_message = None

    while True:
        now_ts = time.time()

        if wx is None or now_ts - wx_at >= 15 * 60:
            new_wx = fetch_weather()
            if not new_wx.error:
                wx = new_wx
                wx_at = now_ts
                print(f"[weather] {wx.temp}C code={wx.code}")
            elif wx is None:
                print(f"[weather] 不可用，本轮省略温度：{new_wx.error}")
                wx_at = now_ts
            else:
                print(f"[weather] 刷新失败，继续旧数据：{new_wx.error}")

        if cx is None or now_ts - cx_at >= 2 * 60:
            new_cx = fetch_codex_desktop_limits()
            if not new_cx.error:
                cx = new_cx
                cx_at = now_ts
                if cx.long is not None:
                    print(f"[codex] WK {pct(cx.long)}%")
                else:
                    print("[codex] 没有周额度窗口")
            elif cx is None:
                print(f"[codex] 首次读取失败，先显示 ?：{new_cx.error}")
            else:
                print(f"[codex] 刷新失败，继续旧数据：{new_cx.error}")

        message = build_scroll_message(wx, cx)
        if message != last_message:
            print(f"[scroll] {message}")
            send_scroll_text_safe(message)
            last_message = message

        # Align roughly with minute updates but keep it simple and conservative.
        time.sleep(60)

# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------

@dataclass
class Weather:
    temp: Optional[int] = None
    high: Optional[int] = None
    low: Optional[int] = None
    code: Optional[int] = None
    is_day: Optional[bool] = None
    error: Optional[str] = None


def fetch_weather():
    if not weather_configured():
        return Weather(
            error=(
                "Weather location is not configured. "
                "Set weather_latitude/weather_longitude in "
                "%APPDATA%\\DP104Dashboard\\config.json or DP104_LAT/DP104_LON."
            )
        )

    params = {
        "latitude": LAT,
        "longitude": LON,
        "current": "temperature_2m,weather_code,is_day",
        "daily": "temperature_2m_max,temperature_2m_min",
        "forecast_days": 1,
        "timezone": WEATHER_TZ,
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "DP104-Dashboard/0.2"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = json.load(resp)
        cur = raw["current"]
        daily = raw["daily"]
        return Weather(
            temp=round(float(cur["temperature_2m"])),
            high=round(float(daily["temperature_2m_max"][0])),
            low=round(float(daily["temperature_2m_min"][0])),
            code=int(cur["weather_code"]),
            is_day=bool(cur.get("is_day", 1)),
        )
    except Exception as exc:
        return Weather(error=f"{type(exc).__name__}: {exc}")


def weather_kind(code):
    if code == 0:
        return "sun"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (95, 96, 99):
        return "storm"
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return "rain"
    return "cloud"


def weather_icon(frame, kind):
    if kind == "sun":
        for x, y in [(3,1),(3,5),(1,3),(5,3),(2,2),(4,2),(2,4),(4,4)]:
            px(frame, x, y, YELLOW)
        for y in range(2,5):
            for x in range(2,5):
                px(frame, x, y, YELLOW)
    else:
        cloud = [(1,3),(2,2),(3,2),(4,2),(5,3),(1,4),(2,4),(3,4),(4,4),(5,4)]
        for p in cloud:
            px(frame, *p, WHITE)
        if kind == "rain":
            for p in [(2,6),(4,6),(6,6),(3,7),(5,7)]:
                px(frame, *p, BLUE)
        elif kind == "snow":
            for p in [(2,6),(5,6),(3,7),(6,7)]:
                px(frame, *p, CYAN)
        elif kind == "storm":
            for p in [(4,4),(3,5),(4,5),(3,6),(2,7)]:
                px(frame, *p, YELLOW)


def weather_frame(wx):
    """
    Readability-first weather test:
      left 8 cols  = weather icon
      right 16 cols = large 5x7 current temperature

    No tiny 'C', no H/L on this frame. A 2x2 degree marker is used instead.
    High/low will become a separate frame/page after current-temp readability
    is confirmed.
    """
    f = blank()
    if wx.temp is None:
        draw_text(f, "W?", 2, 1, ORANGE)
        return f

    weather_icon(f, weather_kind(wx.code))

    # Move the left weather icon up by 2 pixels for better vertical balance.
    # Only touch cols 0-7; temperature area on the right is unchanged.
    shift = 2
    for y in range(shift, H):
        for x in range(0, 8):
            f[(y - shift) * W + x] = f[y * W + x]
    for y in range(H - shift, H):
        for x in range(0, 8):
            f[y * W + x] = BLACK

    temp = max(-9, min(99, wx.temp))
    s = str(temp)

    # 1 digit => 5 px, 2 digits => 11 px incl. spacing.
    digit_width = 5 if len(s) == 1 else 11
    x0 = 8 + max(0, (14 - digit_width) // 2)
    draw_big_number(f, s, x0, 0, WHITE, spacing=1)

    # Degree marker: 2x2 cyan square.
    # Add a tiny "C" directly below it for clearer Celsius labeling.
    degree_x = 22 if len(s) >= 2 else min(22, x0 + 6)
    px(f, degree_x, 0, CYAN)
    px(f, degree_x + 1, 0, CYAN)
    px(f, degree_x, 1, CYAN)
    px(f, degree_x + 1, 1, CYAN)

    c_x = max(0, min(W - 3, degree_x - 1))
    draw_text(f, "C", c_x, 3, CYAN, tiny=True, spacing=0)

    return f


def highlow_frame(wx):
    """
    High / low page:
      left  = today's HIGH, red, large 5x7
      right = today's LOW,  blue, large 5x7

    Two two-digit values fit exactly in 24 columns:
      high x=0..10, gap x=11..12, low x=13..23
    """
    f = blank()
    if wx.high is None or wx.low is None:
        draw_text(f, "H?", 1, 1, RED)
        draw_text(f, "L?", 13, 1, BLUE)
        return f

    high = max(0, min(99, int(wx.high)))
    low = max(0, min(99, int(wx.low)))

    draw_big_number(f, f"{high:02d}", 0, 0, RED, spacing=1)
    draw_big_number(f, f"{low:02d}", 13, 0, BLUE, spacing=1)

    # Tiny center divider so the two numbers read as a pair.
    px(f, 11, 2, DIM)
    px(f, 11, 4, DIM)
    px(f, 12, 2, DIM)
    px(f, 12, 4, DIM)
    return f


# ---------------------------------------------------------------------------
# Codex Desktop quota
# Ported from the open-source quota-float approach:
#   - reads local Codex Desktop auth from CODEX_HOME/auth.json or ~/.codex/auth.json
#   - queries ChatGPT quota usage with that existing session
#   - never logs or stores the access token
# ---------------------------------------------------------------------------

import base64
from pathlib import Path as _Path

CODEX_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
MAX_CODEX_AUTH_BYTES = 256 * 1024
MAX_CODEX_RESPONSE_BYTES = 1024 * 1024


@dataclass
class RateWindow:
    used: Optional[float] = None
    duration: Optional[int] = None
    resets_at: object = None

    @property
    def remaining(self):
        if self.used is None:
            return None
        return max(0.0, min(100.0, 100.0 - self.used))


@dataclass
class CodexLimits:
    short: Optional[RateWindow] = None
    long: Optional[RateWindow] = None
    error: Optional[str] = None
    plan: Optional[str] = None
    auth_path: Optional[str] = None


def _codex_auth_path():
    home = os.getenv("CODEX_HOME")
    if home:
        return _Path(home) / "auth.json"
    return _Path.home() / ".codex" / "auth.json"


def _pick_string(obj, keys):
    if not isinstance(obj, dict):
        return None
    for key in keys:
        value = obj.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _b64url_json(segment):
    pad = "=" * ((4 - len(segment) % 4) % 4)
    raw = base64.urlsafe_b64decode((segment + pad).encode("ascii"))
    return json.loads(raw.decode("utf-8"))


def _account_id_from_jwt(token):
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload = _b64url_json(parts[1])
        return _pick_string(
            payload,
            [
                "https://api.openai.com/auth.chatgpt_account_id",
                "chatgpt_account_id",
            ],
        )
    except Exception:
        return None


def _load_codex_desktop_auth():
    path = _codex_auth_path()
    if not path.is_file():
        raise RuntimeError(f"找不到 Codex Desktop 登录文件：{path}")
    size = path.stat().st_size
    if size <= 0 or size > MAX_CODEX_AUTH_BYTES:
        raise RuntimeError("Codex 登录文件大小异常")

    value = json.loads(path.read_text(encoding="utf-8"))
    tokens = value.get("tokens") if isinstance(value, dict) else None
    if not isinstance(tokens, dict):
        tokens = value

    access_token = _pick_string(tokens, ["access_token", "accessToken"])
    if not access_token:
        raise RuntimeError("auth.json 中没有 access_token；可能需要重新登录 Codex Desktop")

    account_id = _pick_string(tokens, ["account_id", "accountId"])
    if not account_id:
        account_id = _account_id_from_jwt(access_token)

    return path, access_token, account_id


def _number_with_key(value, keys):
    if not isinstance(value, dict):
        return None, None
    for key in keys:
        item = value.get(key)
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            return key, float(item)
    return None, None


def _integer(value, keys):
    if not isinstance(value, dict):
        return None
    for key in keys:
        item = value.get(key)
        if isinstance(item, int) and not isinstance(item, bool) and item >= 0:
            return item
        if isinstance(item, float) and item >= 0 and item.is_integer():
            return int(item)
    return None


def _timestamp(value, keys):
    if not isinstance(value, dict):
        return None
    for key in keys:
        item = value.get(key)
        if isinstance(item, str) and item:
            return item
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            return int(item)
    return None


def _scale_ratio_field(key, value):
    return (
        key in {
            "remaining_ratio",
            "remainingRatio",
            "used_ratio",
            "usedRatio",
            "utilization",
        }
        or ("percent" not in key and "pct" not in key and value <= 1.0)
    )


def _parse_quota_window(value):
    if not isinstance(value, dict):
        return None

    key, remaining = _number_with_key(
        value,
        [
            "remaining_percent",
            "remainingPercent",
            "remaining_pct",
            "remainingPct",
            "remaining_ratio",
            "remainingRatio",
            "remaining",
        ],
    )

    if remaining is not None:
        if _scale_ratio_field(key, remaining):
            remaining *= 100.0
        remaining = max(0.0, min(100.0, remaining))
        used = 100.0 - remaining
    else:
        key, used = _number_with_key(
            value,
            [
                "used_percent",
                "usedPercent",
                "used_pct",
                "usedPct",
                "used_ratio",
                "usedRatio",
                "utilization",
                "used",
            ],
        )
        if used is None:
            return None
        if _scale_ratio_field(key, used):
            used *= 100.0
        used = max(0.0, min(100.0, used))

    seconds = _integer(
        value,
        [
            "limit_window_seconds",
            "limitWindowSeconds",
            "window_seconds",
            "windowSeconds",
            "duration_seconds",
            "durationSeconds",
            "period_seconds",
            "periodSeconds",
        ],
    ) or 0

    resets_at = _timestamp(
        value,
        [
            "reset_at",
            "resetAt",
            "resets_at",
            "resetsAt",
            "reset_time",
            "resetTime",
        ],
    )

    return RateWindow(
        used=used,
        duration=round(seconds / 60) if seconds else None,
        resets_at=resets_at,
    )


def _find_quota_window(rate_limit, names, expected_seconds):
    if not isinstance(rate_limit, dict):
        return None

    for name in names:
        candidate = rate_limit.get(name)
        parsed = _parse_quota_window(candidate)
        if parsed:
            seconds = (parsed.duration or 0) * 60
            if seconds == 0 or abs(seconds - expected_seconds) <= 60:
                return parsed

    for key in ["windows", "limit_windows", "limitWindows", "limits", "buckets"]:
        items = rate_limit.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            parsed = _parse_quota_window(item)
            if not parsed:
                continue

            seconds = (parsed.duration or 0) * 60
            matches_duration = (
                expected_seconds > 0 and abs(seconds - expected_seconds) <= 60
            )

            label = _pick_string(item, ["name", "type", "id", "window", "label"])
            label_lower = label.lower() if label else ""
            matches_name = any(name.lower() in label_lower for name in names)

            if matches_duration or matches_name:
                return parsed

    return None


def fetch_codex_desktop_limits():
    try:
        auth_path, access_token, account_id = _load_codex_desktop_auth()

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "originator": "Codex Desktop",
            "OAI-Product-Sku": "CODEX",
            "User-Agent": "DP104-Dashboard/1.1",
        }
        if account_id:
            headers["ChatGPT-Account-Id"] = account_id

        req = urllib.request.Request(
            CODEX_USAGE_URL,
            headers=headers,
            method="GET",
        )

        with urllib.request.urlopen(req, timeout=10) as resp:
            content_length = resp.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_CODEX_RESPONSE_BYTES:
                raise RuntimeError("Codex quota 响应过大，已拒绝读取")
            raw = resp.read(MAX_CODEX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_CODEX_RESPONSE_BYTES:
                raise RuntimeError("Codex quota 响应超过 1 MiB，已拒绝读取")

        usage = json.loads(raw.decode("utf-8"))
        if not isinstance(usage, dict):
            raise RuntimeError("Codex quota 响应不是 JSON 对象")

        rate_limit = usage.get("rate_limit") or usage.get("rateLimit") or usage

        short = _find_quota_window(
            rate_limit,
            [
                "primary_window",
                "primaryWindow",
                "short_window",
                "shortWindow",
                "five_hour_window",
                "fiveHourWindow",
                "5h",
                "primary",
            ],
            18_000,
        )

        weekly = _find_quota_window(
            rate_limit,
            [
                "secondary_window",
                "secondaryWindow",
                "weekly_window",
                "weeklyWindow",
                "week_window",
                "weekWindow",
                "weekly",
                "secondary",
                "primary_window",
                "primaryWindow",
                "primary",
            ],
            604_800,
        )

        if short is None and weekly is None:
            raise RuntimeError("quota 响应里没有识别到 5 小时或周额度窗口")

        plan = _pick_string(usage, ["plan_type", "planType"])
        if plan:
            plan = plan.upper()

        return CodexLimits(
            short=short,
            long=weekly,
            plan=plan,
            auth_path=str(auth_path),
        )

    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            msg = "Codex Desktop 登录已失效，请重新登录"
        elif exc.code == 429:
            msg = "Codex quota 服务限流（HTTP 429）"
        else:
            msg = f"Codex quota HTTP {exc.code}"
        return CodexLimits(error=msg)
    except Exception as exc:
        return CodexLimits(error=f"{type(exc).__name__}: {exc}")


def pct(window):
    if not window or window.remaining is None:
        return None
    return round(window.remaining)


def codex_quota_frame(window, label):
    """
    Codex quota page optimized for the DP104 24x8 matrix.

    Left:
      dedicated large 5x7 "WK"

    Right:
      large 5x7 remaining percentage NUMBER ONLY

    No GPT label and no percent symbol/dots.
    The number color alone indicates quota state.
    """
    f = blank()
    value = pct(window)
    if value is None:
        draw_text(f, "C?", 1, 1, ORANGE)
        return f

    value = max(0, min(99, value))
    color = remaining_color(value)

    # Large, distinct W/K glyphs.
    draw_label5x7(f, "WK", 0, 0, CYAN, spacing=1)

    # Two large digits. No "%" marker because it is unreadable at 24x8.
    digits = f"{value:02d}"
    draw_big_number(f, digits, 13, 0, color, spacing=1)

    return f



def codex_desktop_check():
    """
    Zero-HID-write diagnostic for Codex Desktop quota.
    """
    print("=== CODEX DESKTOP QUOTA CHECK ===")
    print("此模式不会写入 DP104。")
    print(f"auth path: {_codex_auth_path()}")

    limits = fetch_codex_desktop_limits()
    if limits.error:
        print(f"FAIL: {limits.error}")
        return 3

    print(f"OK: plan={limits.plan or '?'}")
    if limits.short:
        print(
            f"5h: remaining={pct(limits.short)}% "
            f"duration={limits.short.duration} min "
            f"reset={limits.short.resets_at}"
        )
    else:
        print("5h: unavailable")

    if limits.long:
        print(
            f"week: remaining={pct(limits.long)}% "
            f"duration={limits.long.duration} min "
            f"reset={limits.long.resets_at}"
        )
    else:
        print("week: unavailable")

    print("没有打印 access token / account id。")
    return 0


# ---------------------------------------------------------------------------
# Battery: explicit unsupported state
# ---------------------------------------------------------------------------

def battery_frame():
    f = blank()
    draw_text(f, "B?", 1, 1, ORANGE)
    draw_bar(f, 1, 7, 22, 0, DIM)
    return f


# ---------------------------------------------------------------------------
# Clock / test
# ---------------------------------------------------------------------------

def clock_frame():
    """
    Large 5x7 clock.

    Layout fits exactly in 24 columns:
      digit1 x=0..4
      gap    x=5
      digit2 x=6..10
      colon  x=11..12
      digit3 x=13..17
      gap    x=18
      digit4 x=19..23
    """
    f = blank()
    hhmm = datetime.now().strftime("%H%M")

    draw_big_number(f, hhmm[0], 0, 0, WHITE, spacing=0)
    draw_big_number(f, hhmm[1], 6, 0, WHITE, spacing=0)
    draw_big_number(f, hhmm[2], 13, 0, WHITE, spacing=0)
    draw_big_number(f, hhmm[3], 19, 0, WHITE, spacing=0)

    # Single-column cyan colon: exactly two blue dots.
    px(f, 12, 2, CYAN)
    px(f, 12, 4, CYAN)
    return f



def test_frame():
    f = blank()
    draw_text(f, "DP", 1, 1, GREEN)
    draw_text(f, "104", 10, 1, CYAN)
    return f


# ---------------------------------------------------------------------------
# System tray mode controller
# ---------------------------------------------------------------------------

APP_NAME = "DP104 Dashboard"
APP_REG_VALUE = "DP104Dashboard"
APP_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _app_data_dir():
    """Persistent per-user storage that also works inside a PyInstaller one-file EXE."""
    if sys.platform == "win32":
        root = os.getenv("APPDATA")
        if root:
            p = _Path(root) / "DP104Dashboard"
        else:
            p = _Path.home() / "AppData" / "Roaming" / "DP104Dashboard"
    else:
        p = _Path.home() / ".dp104_dashboard"
    p.mkdir(parents=True, exist_ok=True)
    return p


TRAY_SETTINGS_FILE = _app_data_dir() / "settings.json"

MODE_HYBRID = "hybrid"
MODE_SCROLL = "scroll"
MODE_TYPING = "typing"
MODE_WEATHER = "weather"
MODE_CLOCK = "clock"
MODE_CODEX = "codex"
MODE_ROTATE = "rotate"
MODE_PAUSE = "pause"

MODE_LABELS = {
    MODE_HYBRID: "自动：敲键实时输入 / 空闲滚动",
    MODE_SCROLL: "固定：滚动信息",
    MODE_TYPING: "固定：实时输入",
    MODE_WEATHER: "固定：天气",
    MODE_CLOCK: "固定：时钟",
    MODE_CODEX: "固定：Codex 周额度",
    MODE_ROTATE: "轮播：天气 / 时钟 / WK",
    MODE_PAUSE: "暂停更新",
}



_SINGLE_INSTANCE_HANDLE = None


def _is_frozen_exe():
    return bool(getattr(sys, "frozen", False))


def _app_launch_command():
    """
    Command saved to HKCU Run.
    Packaged EXE: launch the EXE directly.
    Source mode: launch pythonw.exe + this script.
    """
    if _is_frozen_exe():
        return f'"{_Path(sys.executable).resolve()}" --tray'

    py = _Path(sys.executable).resolve()
    if sys.platform == "win32":
        pyw = py.with_name("pythonw.exe")
        if pyw.exists():
            py = pyw
    script = _Path(__file__).resolve()
    return f'"{py}" "{script}" --tray'


def _startup_is_enabled():
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            APP_REG_PATH,
            0,
            winreg.KEY_READ,
        ) as key:
            value, _kind = winreg.QueryValueEx(key, APP_REG_VALUE)
        return bool(value)
    except Exception:
        return False


def _set_startup_enabled(enabled):
    """
    Per-user Windows login auto-start.
    Uses HKCU Run, so no administrator privileges are required.
    """
    if sys.platform != "win32":
        raise RuntimeError("开机自启仅支持 Windows")

    import winreg

    if enabled:
        cmd = _app_launch_command()
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, APP_REG_PATH) as key:
            winreg.SetValueEx(key, APP_REG_VALUE, 0, winreg.REG_SZ, cmd)
        return True

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            APP_REG_PATH,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, APP_REG_VALUE)
    except FileNotFoundError:
        pass
    return False


def _show_windows_message(title, message, flags=0x40):
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.MessageBoxW(None, str(message), str(title), flags)
            return
        except Exception:
            pass
    print(f"{title}: {message}")


def _acquire_single_instance():
    """
    Prevent two tray controllers from writing Raw HID at the same time.
    This is especially important for the DP104 firmware.
    """
    global _SINGLE_INSTANCE_HANDLE

    if sys.platform != "win32":
        return True

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, "Local\\DP104DashboardSingleton")
    if not handle:
        return True

    ERROR_ALREADY_EXISTS = 183
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        try:
            kernel32.CloseHandle(handle)
        except Exception:
            pass
        _show_windows_message(
            APP_NAME,
            "DP104 Dashboard 已经在后台运行。\\n\\n请在系统托盘中找到它。",
            0x40,
        )
        return False

    _SINGLE_INSTANCE_HANDLE = handle
    return True

def _load_tray_mode():
    try:
        raw = json.loads(TRAY_SETTINGS_FILE.read_text(encoding="utf-8"))
        mode = raw.get("mode")
        if mode in MODE_LABELS:
            return mode
    except Exception:
        pass
    return MODE_HYBRID


def _save_tray_mode(mode):
    try:
        TRAY_SETTINGS_FILE.write_text(
            json.dumps({"mode": mode}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"[tray] 保存设置失败：{exc}")


def _make_tray_icon_image():
    if Image is None or ImageDraw is None:
        return None
    img = Image.new("RGB", (64, 64), (18, 20, 30))
    d = ImageDraw.Draw(img)
    # 24x8-like matrix motif
    for y in range(8):
        for x in range(8):
            if (x + y) % 3 == 0:
                x0 = 8 + x * 6
                y0 = 8 + y * 6
                d.rectangle([x0, y0, x0 + 3, y0 + 3], fill=(80, 220, 200))
    d.rectangle([5, 5, 58, 58], outline=(210, 220, 235), width=2)
    return img


class TrayController:
    def __init__(self):
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._mode = _load_tray_mode()
        self._active_page = None

        self._last_key_time = 0.0
        self._key_event = threading.Event()
        self._listener = None

        self._wx = None
        self._wx_at = 0.0
        self._cx = None
        self._cx_at = 0.0
        self._last_scroll_message = None
        self._last_clock_minute = None
        self._last_rotate_at = 0.0
        self._rotate_index = 0

        self.icon = None

    def get_mode(self):
        with self._lock:
            return self._mode

    def set_mode(self, mode):
        if mode not in MODE_LABELS:
            return
        with self._lock:
            self._mode = mode
        _save_tray_mode(mode)
        print(f"[tray] 模式 -> {MODE_LABELS[mode]}")
        self._wake.set()
        if self.icon:
            try:
                self.icon.update_menu()
            except Exception:
                pass

    def refresh_now(self):
        self._wx_at = 0.0
        self._cx_at = 0.0
        self._last_scroll_message = None
        self._last_clock_minute = None
        self._wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def _on_key(self, _key):
        self._last_key_time = time.monotonic()
        self._key_event.set()
        self._wake.set()

    def _ensure_listener(self):
        if self._listener is not None:
            return
        if pynput_keyboard is None:
            raise RuntimeError("缺少 pynput：pip install pynput")
        self._listener = pynput_keyboard.Listener(on_press=self._on_key)
        self._listener.start()

    def _refresh_data(self):
        now = time.time()
        if self._wx is None or now - self._wx_at >= 15 * 60:
            wx = fetch_weather()
            if not wx.error:
                self._wx = wx
                self._wx_at = now
                print(f"[weather] {wx.temp}C code={wx.code}")
            elif self._wx is None:
                self._wx_at = now
                print(f"[weather] 不可用：{wx.error}")

        if self._cx is None or now - self._cx_at >= 2 * 60:
            cx = fetch_codex_desktop_limits()
            if not cx.error:
                self._cx = cx
                self._cx_at = now
                if cx.long is not None:
                    print(f"[codex] WK {pct(cx.long)}%")
            elif self._cx is None:
                print(f"[codex] 首次读取失败：{cx.error}")

    def _ensure_page(self, page):
        if self._active_page == page:
            return
        switch_display_page_safe(page)
        self._active_page = page

    def _show_scroll(self):
        self._refresh_data()
        msg = build_scroll_message(self._wx, self._cx)
        if msg != self._last_scroll_message:
            send_scroll_text_safe(msg)
            self._last_scroll_message = msg
        self._ensure_page(PAGE_SCROLL)

    def _show_weather(self):
        self._refresh_data()
        if self._wx is None:
            print("[weather] 未配置位置，固定天气模式无法显示天气。")
            return
        self._ensure_page(PAGE_CUSTOM)
        send_frames_safe([weather_frame(self._wx)], fps=1)

    def _show_clock(self):
        minute = datetime.now().strftime("%Y%m%d%H%M")
        if minute == self._last_clock_minute and self._active_page == PAGE_CUSTOM:
            return
        self._ensure_page(PAGE_CUSTOM)
        send_frames_safe([clock_frame()], fps=1)
        self._last_clock_minute = minute

    def _show_codex(self):
        self._refresh_data()
        if self._cx is None or self._cx.long is None:
            return
        self._ensure_page(PAGE_CUSTOM)
        send_frames_safe([codex_quota_frame(self._cx.long, "WK")], fps=1)

    def _run_hybrid_step(self):
        self._ensure_listener()
        now = time.monotonic()

        if self._key_event.is_set():
            self._key_event.clear()
            self._ensure_page(PAGE_TYPING)
            return

        if self._active_page == PAGE_TYPING:
            if now - self._last_key_time >= TYPING_IDLE_SECONDS:
                self._show_scroll()
        else:
            self._show_scroll()

    def _run_rotate_step(self):
        now = time.monotonic()
        if self._last_rotate_at and now - self._last_rotate_at < PAGE_SECONDS:
            return

        pages = [MODE_WEATHER, MODE_CLOCK, MODE_CODEX]
        mode = pages[self._rotate_index % len(pages)]
        self._rotate_index += 1
        self._last_rotate_at = now

        if mode == MODE_WEATHER:
            self._show_weather()
        elif mode == MODE_CLOCK:
            self._show_clock()
        elif mode == MODE_CODEX:
            self._show_codex()

    def worker(self):
        # Listener is cheap and lets switching into hybrid feel instant.
        try:
            self._ensure_listener()
        except Exception as exc:
            print(f"[tray] 键盘监听不可用：{exc}")

        first = True
        while not self._stop.is_set():
            mode = self.get_mode()

            try:
                if mode == MODE_HYBRID:
                    self._run_hybrid_step()
                elif mode == MODE_SCROLL:
                    self._show_scroll()
                elif mode == MODE_TYPING:
                    self._ensure_page(PAGE_TYPING)
                elif mode == MODE_WEATHER:
                    if first or self._wx is None or time.time() - self._wx_at >= 15 * 60:
                        self._show_weather()
                elif mode == MODE_CLOCK:
                    self._show_clock()
                elif mode == MODE_CODEX:
                    if first or self._cx is None or time.time() - self._cx_at >= 2 * 60:
                        self._show_codex()
                elif mode == MODE_ROTATE:
                    self._run_rotate_step()
                elif mode == MODE_PAUSE:
                    pass
            except Exception as exc:
                print(f"[tray] 模式执行失败 ({mode})：{type(exc).__name__}: {exc}")

            first = False
            self._wake.wait(timeout=0.10 if mode == MODE_HYBRID else 0.50)
            self._wake.clear()

        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass

    def run_tray(self):
        if pystray is None or Image is None:
            raise RuntimeError("缺少托盘依赖：pip install pystray pillow")

        worker = threading.Thread(target=self.worker, daemon=True)
        worker.start()

        def is_checked(mode):
            return lambda _item: self.get_mode() == mode

        def choose(mode):
            return lambda _icon, _item: self.set_mode(mode)

        def status_text(_item):
            return "当前：" + MODE_LABELS[self.get_mode()]

        def refresh_action(_icon, _item):
            self.refresh_now()

        def startup_checked(_item):
            return _startup_is_enabled()

        def toggle_startup(_icon, _item):
            try:
                new_state = not _startup_is_enabled()
                _set_startup_enabled(new_state)
                print(f"[tray] 开机自启 -> {'ON' if new_state else 'OFF'}")
                if self.icon:
                    self.icon.update_menu()
            except Exception as exc:
                _show_windows_message(APP_NAME, f"开机自启设置失败：{exc}", 0x10)

        def quit_action(icon, _item):
            self.stop()
            icon.stop()

        menu = pystray.Menu(
            TrayItem(status_text, None, enabled=False),
            pystray.Menu.SEPARATOR,
            TrayItem(MODE_LABELS[MODE_HYBRID], choose(MODE_HYBRID),
                     checked=is_checked(MODE_HYBRID), radio=True),
            TrayItem(MODE_LABELS[MODE_SCROLL], choose(MODE_SCROLL),
                     checked=is_checked(MODE_SCROLL), radio=True),
            TrayItem(MODE_LABELS[MODE_TYPING], choose(MODE_TYPING),
                     checked=is_checked(MODE_TYPING), radio=True),
            pystray.Menu.SEPARATOR,
            TrayItem(MODE_LABELS[MODE_WEATHER], choose(MODE_WEATHER),
                     checked=is_checked(MODE_WEATHER), radio=True),
            TrayItem(MODE_LABELS[MODE_CLOCK], choose(MODE_CLOCK),
                     checked=is_checked(MODE_CLOCK), radio=True),
            TrayItem(MODE_LABELS[MODE_CODEX], choose(MODE_CODEX),
                     checked=is_checked(MODE_CODEX), radio=True),
            TrayItem(MODE_LABELS[MODE_ROTATE], choose(MODE_ROTATE),
                     checked=is_checked(MODE_ROTATE), radio=True),
            pystray.Menu.SEPARATOR,
            TrayItem(MODE_LABELS[MODE_PAUSE], choose(MODE_PAUSE),
                     checked=is_checked(MODE_PAUSE), radio=True),
            pystray.Menu.SEPARATOR,
            TrayItem("开机自启", toggle_startup, checked=startup_checked),
            TrayItem("立即刷新数据", refresh_action),
            TrayItem("退出", quit_action),
        )

        image = _make_tray_icon_image()
        self.icon = pystray.Icon(
            "dp104_dashboard",
            image,
            "DP104 Dashboard",
            menu,
        )
        print(f"[tray] 启动，当前模式：{MODE_LABELS[self.get_mode()]}")
        self.icon.run()


def run_tray_app():
    if not _acquire_single_instance():
        return 0
    controller = TrayController()
    controller.run_tray()
    return 0

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def diagnose():
    print("=== DP104 SAFE DIAGNOSE v2.2 ===")
    print("此模式不会向键盘写任何 HID 数据。")
    print()

    print("[1] DP104 HID interfaces")
    devs = dp104_interfaces()
    if not devs:
        print("  FAIL: 未枚举到 VID=E560 PID=E104")
    else:
        for i, d in enumerate(devs, 1):
            print(
                f"  #{i}: interface={d.get('interface_number')} "
                f"usage_page=0x{int(d.get('usage_page') or 0):04X} "
                f"usage=0x{int(d.get('usage') or 0):04X} "
                f"manufacturer={d.get('manufacturer_string')!r} "
                f"product={d.get('product_string')!r}"
            )
        p = find_pixel_interface()
        if p:
            print(f"  OK: pixel candidate interface={p.get('interface_number')}")
        else:
            print("  FAIL: 找不到 MI_01 / Raw HID 候选接口")
    print()

    print(f"[2] Weather: label={LOCATION_NAME!r}; configured={weather_configured()}; timezone={WEATHER_TZ}")
    wx = fetch_weather()
    if wx.error:
        print(f"  FAIL: {wx.error}")
    else:
        print(
            f"  OK: temp={wx.temp}C high={wx.high}C low={wx.low}C "
            f"code={wx.code} is_day={wx.is_day}"
        )
    print()

    print("[3] Codex Desktop quota")
    cx = fetch_codex_desktop_limits()
    if cx.error:
        print(f"  FAIL: {cx.error}")
    else:
        print(
            f"  OK: plan={cx.plan or '?'}; "
            f"5h remaining={pct(cx.short) if cx.short else '?'}%; "
            f"week remaining={pct(cx.long) if cx.long else '?'}%"
        )
    print()

    print("[4] DP104 battery")
    print("  UNSUPPORTED: 目前还没有确认真实电量的 HID 查询/响应字节。")
    print("  v0.1 显示 ? 是因为这个功能实际上没有接通，不是读取成功后丢值。")
    print()

    print("诊断结束。请把这一整段输出发给我。")
    return 0


def run_one_rotation():
    """
    One safe cycle only:
      Weather -> Clock -> Codex weekly quota

    Every page is still a single-frame upload.
    No LCD page-switch command is sent.
    """
    print(f"读取天气：{LOCATION_NAME}")
    wx = fetch_weather()
    if wx.error:
        raise RuntimeError(f"天气读取失败：{wx.error}")

    print("读取 Codex Desktop 周额度...")
    cx = fetch_codex_desktop_limits()

    pages = [
        ("weather", weather_frame(wx)),
        ("clock", clock_frame()),
    ]

    if cx.error:
        print(f"Codex 额度读取失败，本轮跳过：{cx.error}")
    elif cx.long is not None:
        print(f"Codex 周额度剩余：{pct(cx.long)}%")
        pages.append(("codex-week", codex_quota_frame(cx.long, "WK")))
    else:
        print("Codex 当前没有可识别的周额度窗口，本轮跳过。")

    print(f"天气数据：当前 {wx.temp}C / code={wx.code}")

    total = len(pages)
    for i, (name, frame) in enumerate(pages, 1):
        print(f"[{i}/{total}] 发送 {name}")
        send_frames_safe([frame], fps=1)
        if i < total:
            print(f"    保持 {PAGE_SECONDS:.0f} 秒...")
            time.sleep(max(PAGE_SECONDS, MIN_SEND_GAP))

    print("单次轮播完成。")
    return 0


def run_dashboard():
    """
    Conservative continuous rotation:
      Weather -> Clock -> Codex weekly quota

    Refresh cadence:
      weather: every 15 minutes
      Codex quota: every 2 minutes

    If a refresh fails, the last successful value is kept.
    If Codex has never succeeded, the Codex page is skipped.
    """
    print("=== DP104 SAFE RUN v1.7 ===")
    print("轮播：天气 -> 时钟 -> Codex 周额度")
    print("每页单帧上传；不发送 LCD page-switch 命令。Ctrl+C 停止。")

    wx = None
    wx_at = 0.0

    cx = None
    cx_at = 0.0

    while True:
        now = time.time()

        # Weather refresh.
        if wx is None or now - wx_at >= 15 * 60:
            new_wx = fetch_weather()
            if not new_wx.error:
                wx = new_wx
                wx_at = now
                print(f"[weather] 当前 {wx.temp}C / code={wx.code}")
            elif wx is None:
                raise RuntimeError(f"天气读取失败：{new_wx.error}")
            else:
                print(f"[weather] 刷新失败，继续使用旧数据：{new_wx.error}")

        # Codex quota refresh.
        if cx is None or now - cx_at >= 2 * 60:
            new_cx = fetch_codex_desktop_limits()
            if not new_cx.error:
                cx = new_cx
                cx_at = now
                if cx.long is not None:
                    print(f"[codex] 周额度剩余 {pct(cx.long)}%")
                else:
                    print("[codex] 当前没有周额度窗口")
            else:
                if cx is None:
                    print(f"[codex] 首次读取失败，暂时跳过 Codex 页：{new_cx.error}")
                else:
                    print(f"[codex] 刷新失败，继续使用旧数据：{new_cx.error}")

        pages = [
            ("weather", weather_frame(wx)),
            ("clock", clock_frame()),
        ]

        if cx is not None and cx.long is not None:
            pages.append(("codex-week", codex_quota_frame(cx.long, "WK")))

        for name, frame in pages:
            print(f"[send] {name}")
            send_frames_safe([frame], fps=1)
            time.sleep(max(PAGE_SECONDS, MIN_SEND_GAP))


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--diagnose", action="store_true", help="零 HID 写入，只诊断")
    group.add_argument("--test-display", action="store_true", help="只发送一个静态测试画面")
    group.add_argument("--test-weather", action="store_true", help="读取实时天气并只发送一个天气画面")
    group.add_argument("--test-rotate", action="store_true", help="安全测试一次：天气 -> 时钟 -> Codex周额度")
    group.add_argument("--codex-desktop-check", action="store_true", help="读取 Codex Desktop 额度；零 HID 写入")
    group.add_argument("--test-codex", action="store_true", help="发送一帧当前可用的 Codex 剩余额度（优先周额度）")
    group.add_argument("--test-scroll", action="store_true", help="发送一次原生滚动文本；不自动切LCD页面")
    group.add_argument("--scroll", action="store_true", help="持续原生滚动：温度 + 时间 + WK周额度")
    group.add_argument("--typing-scroll", action="store_true", help="空闲滚动；敲键时切实时输入；停止后回滚动")
    group.add_argument("--tray", action="store_true", help="后台系统托盘模式控制器")
    group.add_argument("--run", action="store_true", help="持续轮播：天气 -> 时钟 -> Codex周额度")
    args = parser.parse_args()

    # A packaged EXE should behave like a normal desktop app:
    # double-click with no arguments -> open the tray controller.
    if not any(vars(args).values()):
        return run_tray_app()

    if args.diagnose:
        return diagnose()

    if args.test_display:
        print("只会发送 1 个静态画面，不会发送 LCD page-switch 命令。")
        print("请先在官方配置器切到 CUSTOM 页面，然后完全关闭配置器。")
        send_frames_safe([test_frame()], fps=1)
        print("已发送 DP104 测试画面。若点阵未显示，请不要重复运行，先把现象告诉我。")
        return 0

    if args.test_weather:
        print(f"正在读取天气：label={LOCATION_NAME!r}; timezone={WEATHER_TZ}")
        wx = fetch_weather()
        if wx.error:
            print(f"天气读取失败：{wx.error}")
            return 3

        print(
            f"读取成功：temp={wx.temp}C high={wx.high}C low={wx.low}C "
            f"code={wx.code} is_day={wx.is_day}"
        )
        print("现在只发送 1 个静态天气画面；不会切换 LCD 页面，也不会连续轮播。")
        print("请确认官方 TickType 配置器已经完全关闭，并且点阵当前处于 CUSTOM/自定义像素页。")
        send_frames_safe([weather_frame(wx)], fps=1)
        print("天气画面已发送。请观察点阵是否正确，以及键盘按键是否仍然正常。")
        return 0

    if args.test_rotate:
        print("DP104 Dashboard Tray v2.2")
        print("只执行一轮：天气 -> 时钟 -> Codex周额度。")
        print("每次都是单帧上传，不发送 LCD page-switch 命令。")
        print("请确认官方 TickType 配置器已经完全关闭，且点阵处于 CUSTOM/自定义像素页。")
        return run_one_rotation()

    if args.codex_desktop_check:
        return codex_desktop_check()

    if args.test_codex:
        print("DP104 Dashboard Tray v2.2")
        print("读取 Codex Desktop 额度，并自动选择当前可用的额度窗口。")
        limits = fetch_codex_desktop_limits()
        if limits.error:
            print(f"Codex 额度读取失败：{limits.error}")
            return 4

        if limits.long is not None:
            window = limits.long
            label = "WK"
            print(f"读取成功：weekly remaining={pct(window)}%")
        elif limits.short is not None:
            window = limits.short
            label = "5H"
            print(f"读取成功：5h remaining={pct(window)}%")
        else:
            print("Codex 响应中没有可识别的额度窗口；本次不写键盘。")
            return 5

        print("请确认 TickType 配置器已完全关闭，点阵处于 CUSTOM 页面。")
        send_frames_safe([codex_quota_frame(window, label)], fps=1)
        print(f"已发送一帧 Codex {label} 剩余额度。")
        return 0

    if args.test_scroll:
        return test_native_scroll()

    if args.scroll:
        try:
            run_native_scroll()
        except KeyboardInterrupt:
            print("\nStopped.")
            return 0

    if args.typing_scroll:
        try:
            run_typing_scroll()
        except KeyboardInterrupt:
            print("\nStopped.")
            return 0

    if args.tray:
        return run_tray_app()

    if args.run:
        try:
            run_dashboard()
        except KeyboardInterrupt:
            print("\nStopped.")
            return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
