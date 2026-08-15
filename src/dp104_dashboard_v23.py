#!/usr/bin/env python3
"""
DP104 Dashboard v2.3 auto-sleep extension.

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
"""

from __future__ import annotations

import json
import threading
import time

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
        print("[tray] v2.3 auto-sleep guard enabled")
        self.icon.run()


# `base.run_tray_app()` resolves the global TrayController name at runtime.
# Replacing it here means base.main() and --tray both use the extension.
base.TrayController = SleepAwareTrayController


if __name__ == "__main__":
    raise SystemExit(base.main())
