#!/usr/bin/env python3
"""
DP104 Dashboard v2.4 auto-sleep + weather-location settings extension.

This module extends the privacy-safe public `dp104_dashboard.py` without
embedding any user location or credentials.

New behavior:
- Tray-configurable app-controlled auto sleep: off / 5 / 15 / 30 min / 1 / 3 / 6 h.
- Sleep uses the verified global LED power OFF command.
- Only a physical key press resets the app idle timer.
- While sleeping, dashboard refresh/page HID writes are blocked.
- A key press after the sleep transition turns LED power back on and restores
  the selected display mode.
- Stale pre-sleep keyboard-hook events cannot immediately wake the device.
- Tray weather settings support place-name search or manual coordinates.
- No location is embedded in the executable or public repository.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request

import dp104_dashboard as base


AUTO_SLEEP_OPTIONS = {
    0: "关闭",
    5: "5 分钟",
    15: "15 分钟",
    30: "30 分钟",
    60: "1 小时",
    180: "3 小时",
    360: "6 小时",
}

# Official configurator values captured from the device. These are kept for
# documentation/reference. The tray feature deliberately uses its own idle
# timer + verified global LED OFF/ON because periodic dashboard writes can
# defeat the keyboard firmware's own idle timer.
FIRMWARE_SLEEP_CODES = {
    5: 0x01,
    15: 0x02,
    30: 0x03,
    60: 0x04,
    180: 0x05,
    360: 0x06,
}

_SETTINGS_LOCK = threading.Lock()


def _load_settings():
    try:
        raw = json.loads(base.TRAY_SETTINGS_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _update_settings(**changes):
    try:
        with _SETTINGS_LOCK:
            raw = _load_settings()
            raw.update(changes)
            base.TRAY_SETTINGS_FILE.write_text(
                json.dumps(raw, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    except Exception as exc:
        print(f"[tray] 保存设置失败：{exc}")


def _save_mode_preserving_settings(mode):
    """Preserve auto_sleep_minutes when the base tray saves display mode."""
    _update_settings(mode=mode)


# The original base saver wrote a one-key JSON object. Replace it so switching
# display modes no longer discards the auto-sleep preference.
base._save_tray_mode = _save_mode_preserving_settings


def _load_auto_sleep_minutes():
    try:
        value = int(_load_settings().get("auto_sleep_minutes", 0))
    except Exception:
        value = 0
    return value if value in AUTO_SLEEP_OPTIONS else 0


def set_led_power_safe(enabled: bool):
    """
    Set DP104 global LED power with packets captured from the official UI.

    Report ID 0 payloads:
      OFF: 07 11 01 00 + zero padding
      ON : 07 11 01 01 + zero padding
      then 09 11 00 + zero padding

    The same shared HID lock used by the dashboard is used here too.
    """
    info = base.find_pixel_interface()
    if not info:
        raise RuntimeError("找不到 DP104 MI_01 / Raw HID 接口")

    state = 0x01 if enabled else 0x00

    with base._hid_bus_lock:
        dev = base.hid.device()
        try:
            dev.open_path(info["path"])

            pkt1 = [0x00, 0x07, 0x11, 0x01, state] + [0x00] * 28
            pkt2 = [0x00, 0x09, 0x11, 0x00] + [0x00] * 29
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


GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
GEOCODING_RESULT_COUNT = 10


def _read_private_weather_config():
    """Read the local-only config while preserving unrelated keys."""
    try:
        if base._USER_CONFIG_FILE.exists():
            raw = json.loads(base._USER_CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
    except Exception:
        pass
    return {}


def _write_private_weather_config(label, latitude, longitude, timezone_name):
    """
    Persist weather location outside the repository/executable.

    File:
      %APPDATA%\\DP104Dashboard\\config.json
    """
    base._USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    raw = _read_private_weather_config()
    raw.update(
        {
            "location_label": str(label or "DP104").strip() or "DP104",
            "weather_latitude": str(latitude),
            "weather_longitude": str(longitude),
            "weather_timezone": str(timezone_name or "auto").strip() or "auto",
        }
    )

    tmp = base._USER_CONFIG_FILE.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(base._USER_CONFIG_FILE)


def _clear_private_weather_config():
    """Remove weather fields only; preserve unrelated local settings."""
    raw = _read_private_weather_config()
    for key in (
        "location_label",
        "weather_latitude",
        "weather_longitude",
        "weather_timezone",
    ):
        raw.pop(key, None)

    base._USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if raw:
        tmp = base._USER_CONFIG_FILE.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(base._USER_CONFIG_FILE)
    else:
        try:
            base._USER_CONFIG_FILE.unlink()
        except FileNotFoundError:
            pass


def _apply_weather_config_to_runtime(label, latitude, longitude, timezone_name):
    """Update the already-running base module without restarting the EXE."""
    base.LOCATION_NAME = str(label or "DP104").strip() or "DP104"
    base.LAT = None if latitude in (None, "") else str(latitude)
    base.LON = None if longitude in (None, "") else str(longitude)
    base.WEATHER_TZ = str(timezone_name or "auto").strip() or "auto"

    # Keep the in-memory config mirror consistent too.
    try:
        base._USER_CONFIG = _read_private_weather_config()
    except Exception:
        pass


def _validate_coordinates(latitude, longitude):
    lat = float(str(latitude).strip())
    lon = float(str(longitude).strip())
    if not (-90.0 <= lat <= 90.0):
        raise ValueError("纬度必须在 -90 到 90 之间")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError("经度必须在 -180 到 180 之间")
    return lat, lon


def search_weather_locations(query, language="zh"):
    """
    Resolve a place name via Open-Meteo Geocoding API.

    Only the user-entered search text is sent to the geocoding service.
    """
    query = str(query or "").strip()
    if len(query) < 2:
        raise ValueError("地区名称至少输入 2 个字符")

    params = {
        "name": query,
        "count": GEOCODING_RESULT_COUNT,
        "language": language,
        "format": "json",
    }
    url = GEOCODING_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "DP104-Dashboard/2.4"},
    )

    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = json.load(resp)

    if raw.get("error"):
        raise RuntimeError(str(raw.get("reason") or "地点搜索失败"))

    results = raw.get("results")
    if not isinstance(results, list):
        return []

    cleaned = []
    for item in results:
        if not isinstance(item, dict):
            continue
        try:
            lat = float(item["latitude"])
            lon = float(item["longitude"])
        except Exception:
            continue

        name = str(item.get("name") or "").strip()
        admin1 = str(item.get("admin1") or "").strip()
        admin2 = str(item.get("admin2") or "").strip()
        country = str(item.get("country") or item.get("country_code") or "").strip()
        timezone_name = str(item.get("timezone") or "auto").strip() or "auto"

        pieces = []
        for value in (name, admin2, admin1, country):
            if value and value not in pieces:
                pieces.append(value)

        cleaned.append(
            {
                "label": name or "DP104",
                "display": " / ".join(pieces) or f"{lat:.4f}, {lon:.4f}",
                "latitude": lat,
                "longitude": lon,
                "timezone": timezone_name,
            }
        )
    return cleaned


def open_weather_settings_window(controller):
    """
    Open a small local configuration window.

    The UI runs in its own Tk thread so the pystray message loop and DP104
    worker remain responsive.
    """
    def ui_thread():
        try:
            import tkinter as tk
            from tkinter import messagebox, ttk
        except Exception as exc:
            base._show_windows_message(
                base.APP_NAME,
                f"无法打开天气设置窗口：{exc}",
                0x10,
            )
            return

        root = tk.Tk()
        root.title("DP104 Dashboard - 天气位置设置")
        root.resizable(False, False)

        try:
            root.iconbitmap(default=str(base._Path(base.__file__).resolve().parent.parent / "assets" / "dp104.ico"))
        except Exception:
            pass

        main = ttk.Frame(root, padding=14)
        main.grid(row=0, column=0, sticky="nsew")

        current_text = tk.StringVar()
        search_var = tk.StringVar()
        label_var = tk.StringVar(value=str(base.LOCATION_NAME or "DP104"))
        lat_var = tk.StringVar(value="" if base.LAT in (None, "") else str(base.LAT))
        lon_var = tk.StringVar(value="" if base.LON in (None, "") else str(base.LON))
        tz_var = tk.StringVar(value=str(base.WEATHER_TZ or "auto"))
        status_var = tk.StringVar(value="")

        results_data = []

        def update_current_text():
            if base.weather_configured():
                current_text.set(
                    f"当前：{base.LOCATION_NAME or 'DP104'}"
                )
            else:
                current_text.set("当前：未设置天气位置")

        update_current_text()

        ttk.Label(
            main,
            textvariable=current_text,
            font=("", 10, "bold"),
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 10))

        ttk.Label(main, text="地区搜索").grid(row=1, column=0, sticky="w")
        search_entry = ttk.Entry(main, textvariable=search_var, width=34)
        search_entry.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(8, 8))

        search_button = ttk.Button(main, text="搜索")
        search_button.grid(row=1, column=3, sticky="e")

        ttk.Label(
            main,
            text="搜索结果（选择一项会自动填写经纬度和时区）",
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(10, 4))

        result_list = tk.Listbox(main, width=66, height=7, exportselection=False)
        result_list.grid(row=3, column=0, columnspan=4, sticky="ew")

        ttk.Separator(main, orient="horizontal").grid(
            row=4, column=0, columnspan=4, sticky="ew", pady=12
        )

        ttk.Label(main, text="显示名称").grid(row=5, column=0, sticky="w")
        ttk.Entry(main, textvariable=label_var, width=24).grid(
            row=5, column=1, sticky="w", padx=(8, 16)
        )

        ttk.Label(main, text="时区").grid(row=5, column=2, sticky="e")
        ttk.Entry(main, textvariable=tz_var, width=20).grid(
            row=5, column=3, sticky="e", padx=(8, 0)
        )

        ttk.Label(main, text="纬度").grid(row=6, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(main, textvariable=lat_var, width=24).grid(
            row=6, column=1, sticky="w", padx=(8, 16), pady=(8, 0)
        )

        ttk.Label(main, text="经度").grid(row=6, column=2, sticky="e", pady=(8, 0))
        ttk.Entry(main, textvariable=lon_var, width=20).grid(
            row=6, column=3, sticky="e", padx=(8, 0), pady=(8, 0)
        )

        ttk.Label(
            main,
            text="可直接手动输入经纬度；时区留空时使用 auto。",
        ).grid(row=7, column=0, columnspan=4, sticky="w", pady=(6, 0))

        ttk.Label(
            main,
            text=(
                "隐私：地区搜索会把搜索文字发送给 Open-Meteo；"
                "天气请求会发送所选经纬度。配置只保存在本机。"
            ),
            wraplength=520,
        ).grid(row=8, column=0, columnspan=4, sticky="w", pady=(12, 4))

        ttk.Label(main, textvariable=status_var).grid(
            row=9, column=0, columnspan=4, sticky="w", pady=(4, 8)
        )

        button_bar = ttk.Frame(main)
        button_bar.grid(row=10, column=0, columnspan=4, sticky="e")

        def apply_result(_event=None):
            sel = result_list.curselection()
            if not sel:
                return
            idx = int(sel[0])
            if idx < 0 or idx >= len(results_data):
                return
            item = results_data[idx]
            label_var.set(item["label"])
            lat_var.set(f'{item["latitude"]:.6f}')
            lon_var.set(f'{item["longitude"]:.6f}')
            tz_var.set(item["timezone"])

        result_list.bind("<<ListboxSelect>>", apply_result)

        def finish_search(items=None, error=None):
            search_button.config(state="normal")
            result_list.delete(0, tk.END)
            results_data.clear()

            if error:
                status_var.set(f"搜索失败：{error}")
                return

            if not items:
                status_var.set("没有找到匹配地区，可改用手动经纬度。")
                return

            results_data.extend(items)
            for item in items:
                result_list.insert(
                    tk.END,
                    f'{item["display"]}  ({item["latitude"]:.4f}, {item["longitude"]:.4f})'
                )
            status_var.set(f"找到 {len(items)} 个候选位置。")

        def do_search():
            query = search_var.get().strip()
            if len(query) < 2:
                messagebox.showwarning("DP104 Dashboard", "地区名称至少输入 2 个字符。")
                return

            search_button.config(state="disabled")
            status_var.set("正在搜索…")

            def worker():
                try:
                    items = search_weather_locations(query)
                except Exception as exc:
                    root.after(0, lambda e=str(exc): finish_search(error=e))
                else:
                    root.after(0, lambda r=items: finish_search(items=r))

            threading.Thread(target=worker, daemon=True).start()

        search_button.config(command=do_search)
        search_entry.bind("<Return>", lambda _event: do_search())

        def save_location():
            try:
                lat, lon = _validate_coordinates(lat_var.get(), lon_var.get())
            except Exception as exc:
                messagebox.showerror("DP104 Dashboard", str(exc))
                return

            label = label_var.get().strip() or "DP104"
            timezone_name = tz_var.get().strip() or "auto"

            try:
                _write_private_weather_config(
                    label,
                    f"{lat:.6f}",
                    f"{lon:.6f}",
                    timezone_name,
                )
                _apply_weather_config_to_runtime(
                    label,
                    f"{lat:.6f}",
                    f"{lon:.6f}",
                    timezone_name,
                )
                controller.weather_config_changed()
            except Exception as exc:
                messagebox.showerror(
                    "DP104 Dashboard",
                    f"保存天气位置失败：{exc}",
                )
                return

            update_current_text()
            status_var.set("已保存到本机并请求刷新天气。")
            try:
                if controller.icon:
                    controller.icon.update_menu()
            except Exception:
                pass

        def clear_location():
            if not messagebox.askyesno(
                "DP104 Dashboard",
                "清除本机天气位置？\n\n时钟、WK、实时输入等其他功能不会受影响。",
            ):
                return

            try:
                _clear_private_weather_config()
                _apply_weather_config_to_runtime("DP104", None, None, "auto")
                controller.weather_config_changed()
            except Exception as exc:
                messagebox.showerror(
                    "DP104 Dashboard",
                    f"清除天气位置失败：{exc}",
                )
                return

            label_var.set("DP104")
            lat_var.set("")
            lon_var.set("")
            tz_var.set("auto")
            update_current_text()
            status_var.set("天气位置已清除。")
            try:
                if controller.icon:
                    controller.icon.update_menu()
            except Exception:
                pass

        ttk.Button(
            button_bar,
            text="清除位置",
            command=clear_location,
        ).grid(row=0, column=0, padx=(0, 8))

        ttk.Button(
            button_bar,
            text="保存并刷新",
            command=save_location,
        ).grid(row=0, column=1, padx=(0, 8))

        ttk.Button(
            button_bar,
            text="关闭",
            command=root.destroy,
        ).grid(row=0, column=2)

        root.protocol("WM_DELETE_WINDOW", root.destroy)
        search_entry.focus_set()
        root.mainloop()

    threading.Thread(
        target=ui_thread,
        name="DP104WeatherSettings",
        daemon=True,
    ).start()




class SleepAwareTrayController(base.TrayController):
    """Tray controller with app-owned idle sleep and guarded wake-up."""

    def __init__(self):
        super().__init__()
        self._auto_sleep_minutes = _load_auto_sleep_minutes()

        # Only real key-down callbacks update these values. Display refreshes,
        # time changes and quota/weather network calls do not count as activity.
        self._last_key_time = time.monotonic()
        self._key_seq = 0
        self._sleep_key_seq = 0
        self._sleep_started_at = 0.0

        self._sleeping = False
        self._force_sleep_event = threading.Event()
        self._force_wake_event = threading.Event()

    def weather_config_changed(self):
        """Invalidate weather/scroll caches after a local location change."""
        self._wx = None
        self._wx_at = 0.0
        self._last_scroll_message = None
        self._wake.set()

    def get_auto_sleep_minutes(self):
        with self._lock:
            return self._auto_sleep_minutes

    def set_auto_sleep_minutes(self, minutes):
        if minutes not in AUTO_SLEEP_OPTIONS:
            return

        with self._lock:
            self._auto_sleep_minutes = minutes

        _update_settings(auto_sleep_minutes=int(minutes))
        print(f"[tray] 自动休眠 -> {AUTO_SLEEP_OPTIONS[minutes]}")

        if minutes == 0 and self._sleeping:
            self._force_wake_event.set()

        self._wake.set()
        if self.icon:
            try:
                self.icon.update_menu()
            except Exception:
                pass

    def request_sleep_now(self):
        self._force_sleep_event.set()
        self._wake.set()

    def request_wake_now(self):
        self._force_wake_event.set()
        self._wake.set()

    def _on_key(self, _key):
        now = time.monotonic()
        with self._lock:
            self._last_key_time = now
            self._key_seq += 1
        self._key_event.set()
        self._wake.set()

    def _enter_led_sleep(self, reason):
        if self._sleeping:
            return

        print(f"[sleep] LED OFF ({reason})")

        # Discard pre-existing hook state before the OFF transition.
        self._key_event.clear()
        set_led_power_safe(False)

        # Snapshot AFTER the OFF write. Only a newer physical key event may
        # wake the keyboard, which prevents OFF -> immediate ON races.
        with self._lock:
            self._sleep_key_seq = self._key_seq
            self._sleep_started_at = time.monotonic()

        self._sleeping = True
        self._active_page = None
        self._key_event.clear()

        if self.icon:
            try:
                self.icon.update_menu()
            except Exception:
                pass

    def _wake_leds(self, reason):
        if not self._sleeping:
            return

        print(f"[sleep] LED ON ({reason})")
        set_led_power_safe(True)

        # Keep page/control traffic away from the power transition. The DP104
        # firmware has previously shown sensitivity to aggressive HID traffic.
        time.sleep(0.20)

        self._sleeping = False
        self._active_page = None
        self._last_clock_minute = None
        self._last_rotate_at = 0.0
        self._key_event.clear()

        # A real key that woke the device should restore hybrid typing view
        # only after global LED power is stable.
        if reason == "keypress" and self.get_mode() == base.MODE_HYBRID:
            try:
                self._ensure_page(base.PAGE_TYPING)
            except Exception as exc:
                print(f"[sleep] 唤醒后切实时输入失败：{exc}")

        if self.icon:
            try:
                self.icon.update_menu()
            except Exception:
                pass

    def worker(self):
        try:
            self._ensure_listener()
        except Exception as exc:
            print(f"[tray] 键盘监听不可用：{exc}")

        first = True
        try:
            while not self._stop.is_set():
                mode = self.get_mode()

                try:
                    # Execute manual sleep/wake requests in this worker so
                    # tray UI callbacks never write HID directly.
                    if self._force_wake_event.is_set():
                        self._force_wake_event.clear()
                        self._wake_leds("manual")

                    if self._force_sleep_event.is_set():
                        self._force_sleep_event.clear()
                        self._enter_led_sleep("manual")
                        self._wake.wait(timeout=0.10)
                        self._wake.clear()
                        continue

                    if self._sleeping and self._key_event.is_set():
                        now_mono = time.monotonic()
                        with self._lock:
                            key_seq = self._key_seq
                            sleep_key_seq = self._sleep_key_seq
                            sleep_started_at = self._sleep_started_at

                        # Both conditions are required:
                        # 1) the key event happened after LED OFF;
                        # 2) the sleep transition guard has elapsed.
                        if (
                            key_seq > sleep_key_seq
                            and now_mono - sleep_started_at >= 1.5
                        ):
                            self._wake_leds("keypress")
                        else:
                            self._key_event.clear()

                    sleep_minutes = self.get_auto_sleep_minutes()

                    if self._sleeping and sleep_minutes == 0:
                        self._wake_leds("auto-sleep disabled")

                    # This is the key behavior: once sleeping, do not refresh
                    # weather/quota/text/pages and do not issue any other HID
                    # writes until an explicit wake condition occurs.
                    if self._sleeping:
                        self._wake.wait(timeout=0.10)
                        self._wake.clear()
                        continue

                    if sleep_minutes > 0:
                        with self._lock:
                            idle_seconds = time.monotonic() - self._last_key_time
                        if idle_seconds >= sleep_minutes * 60:
                            self._enter_led_sleep(f"idle {sleep_minutes} min")
                            self._wake.wait(timeout=0.10)
                            self._wake.clear()
                            continue

                    if mode == base.MODE_HYBRID:
                        self._run_hybrid_step()
                    elif mode == base.MODE_SCROLL:
                        self._key_event.clear()
                        self._show_scroll()
                    elif mode == base.MODE_TYPING:
                        self._key_event.clear()
                        self._ensure_page(base.PAGE_TYPING)
                    elif mode == base.MODE_WEATHER:
                        self._key_event.clear()
                        if (
                            first
                            or self._wx is None
                            or time.time() - self._wx_at >= 15 * 60
                        ):
                            self._show_weather()
                    elif mode == base.MODE_CLOCK:
                        self._key_event.clear()
                        self._show_clock()
                    elif mode == base.MODE_CODEX:
                        self._key_event.clear()
                        if (
                            first
                            or self._cx is None
                            or time.time() - self._cx_at >= 2 * 60
                        ):
                            self._show_codex()
                    elif mode == base.MODE_ROTATE:
                        self._key_event.clear()
                        self._run_rotate_step()
                    elif mode == base.MODE_PAUSE:
                        self._key_event.clear()

                except Exception as exc:
                    print(
                        f"[tray] 模式执行失败 ({mode})："
                        f"{type(exc).__name__}: {exc}"
                    )

                first = False
                self._wake.wait(
                    timeout=0.10 if mode == base.MODE_HYBRID else 0.50
                )
                self._wake.clear()
        finally:
            # Do not intentionally leave the keyboard globally dark if the
            # application itself is exiting while it owns the sleep state.
            if self._sleeping:
                try:
                    self._wake_leds("application exit")
                except Exception as exc:
                    print(f"[sleep] 退出时恢复 LED 失败：{exc}")

            if self._listener is not None:
                try:
                    self._listener.stop()
                except Exception:
                    pass

    def run_tray(self):
        if base.pystray is None or base.Image is None:
            raise RuntimeError("缺少托盘依赖：pip install pystray pillow")

        worker = threading.Thread(target=self.worker, daemon=True)
        worker.start()

        def is_checked(mode):
            return lambda _item: self.get_mode() == mode

        def choose(mode):
            return lambda _icon, _item: self.set_mode(mode)

        def status_text(_item):
            return "当前：" + base.MODE_LABELS[self.get_mode()]

        def refresh_action(_icon, _item):
            self.refresh_now()

        def sleep_checked(minutes):
            return lambda _item: self.get_auto_sleep_minutes() == minutes

        def choose_sleep(minutes):
            return lambda _icon, _item: self.set_auto_sleep_minutes(minutes)

        def sleep_status_text(_item):
            return "LED 状态：休眠" if self._sleeping else "LED 状态：运行"

        def sleep_now_action(_icon, _item):
            self.request_sleep_now()

        def wake_now_action(_icon, _item):
            self.request_wake_now()

        def weather_status_text(_item):
            if base.weather_configured():
                return "天气位置：" + str(base.LOCATION_NAME or "已设置")
            return "天气位置：未设置"

        def open_weather_settings(_icon, _item):
            open_weather_settings_window(self)

        def startup_checked(_item):
            return base._startup_is_enabled()

        def toggle_startup(_icon, _item):
            try:
                new_state = not base._startup_is_enabled()
                base._set_startup_enabled(new_state)
                print(f"[tray] 开机自启 -> {'ON' if new_state else 'OFF'}")
                if self.icon:
                    self.icon.update_menu()
            except Exception as exc:
                base._show_windows_message(
                    base.APP_NAME,
                    f"开机自启设置失败：{exc}",
                    0x10,
                )

        def quit_action(icon, _item):
            self.stop()
            time.sleep(0.15)
            icon.stop()

        menu = base.pystray.Menu(
            base.TrayItem(status_text, None, enabled=False),
            base.pystray.Menu.SEPARATOR,
            base.TrayItem(
                base.MODE_LABELS[base.MODE_HYBRID],
                choose(base.MODE_HYBRID),
                checked=is_checked(base.MODE_HYBRID),
                radio=True,
            ),
            base.TrayItem(
                base.MODE_LABELS[base.MODE_SCROLL],
                choose(base.MODE_SCROLL),
                checked=is_checked(base.MODE_SCROLL),
                radio=True,
            ),
            base.TrayItem(
                base.MODE_LABELS[base.MODE_TYPING],
                choose(base.MODE_TYPING),
                checked=is_checked(base.MODE_TYPING),
                radio=True,
            ),
            base.pystray.Menu.SEPARATOR,
            base.TrayItem(
                base.MODE_LABELS[base.MODE_WEATHER],
                choose(base.MODE_WEATHER),
                checked=is_checked(base.MODE_WEATHER),
                radio=True,
            ),
            base.TrayItem(
                base.MODE_LABELS[base.MODE_CLOCK],
                choose(base.MODE_CLOCK),
                checked=is_checked(base.MODE_CLOCK),
                radio=True,
            ),
            base.TrayItem(
                base.MODE_LABELS[base.MODE_CODEX],
                choose(base.MODE_CODEX),
                checked=is_checked(base.MODE_CODEX),
                radio=True,
            ),
            base.TrayItem(
                base.MODE_LABELS[base.MODE_ROTATE],
                choose(base.MODE_ROTATE),
                checked=is_checked(base.MODE_ROTATE),
                radio=True,
            ),
            base.pystray.Menu.SEPARATOR,
            base.TrayItem(
                base.MODE_LABELS[base.MODE_PAUSE],
                choose(base.MODE_PAUSE),
                checked=is_checked(base.MODE_PAUSE),
                radio=True,
            ),
            base.pystray.Menu.SEPARATOR,
            base.TrayItem(weather_status_text, None, enabled=False),
            base.TrayItem("天气位置设置...", open_weather_settings),
            base.pystray.Menu.SEPARATOR,
            base.TrayItem(
                "自动休眠",
                base.pystray.Menu(
                    base.TrayItem(sleep_status_text, None, enabled=False),
                    base.pystray.Menu.SEPARATOR,
                    base.TrayItem(
                        "关闭",
                        choose_sleep(0),
                        checked=sleep_checked(0),
                        radio=True,
                    ),
                    base.TrayItem(
                        "5 分钟",
                        choose_sleep(5),
                        checked=sleep_checked(5),
                        radio=True,
                    ),
                    base.TrayItem(
                        "15 分钟",
                        choose_sleep(15),
                        checked=sleep_checked(15),
                        radio=True,
                    ),
                    base.TrayItem(
                        "30 分钟",
                        choose_sleep(30),
                        checked=sleep_checked(30),
                        radio=True,
                    ),
                    base.TrayItem(
                        "1 小时",
                        choose_sleep(60),
                        checked=sleep_checked(60),
                        radio=True,
                    ),
                    base.TrayItem(
                        "3 小时",
                        choose_sleep(180),
                        checked=sleep_checked(180),
                        radio=True,
                    ),
                    base.TrayItem(
                        "6 小时",
                        choose_sleep(360),
                        checked=sleep_checked(360),
                        radio=True,
                    ),
                    base.pystray.Menu.SEPARATOR,
                    base.TrayItem(
                        "立即休眠（关闭所有 LED）",
                        sleep_now_action,
                    ),
                    base.TrayItem("立即唤醒 LED", wake_now_action),
                ),
            ),
            base.TrayItem(
                "开机自启",
                toggle_startup,
                checked=startup_checked,
            ),
            base.TrayItem("立即刷新数据", refresh_action),
            base.TrayItem("退出", quit_action),
        )

        image = base._make_tray_icon_image()
        self.icon = base.pystray.Icon(
            "dp104_dashboard",
            image,
            "DP104 Dashboard",
            menu,
        )
        print(f"[tray] 启动，当前模式：{base.MODE_LABELS[self.get_mode()]}")
        print("[tray] v2.4 auto-sleep + weather settings enabled")
        self.icon.run()


# `base.run_tray_app()` resolves the global TrayController name at runtime.
# Replacing it here means base.main() and --tray both use the extension.
base.TrayController = SleepAwareTrayController


if __name__ == "__main__":
    raise SystemExit(base.main())
