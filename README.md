# DP104 Dashboard

> 中文 | English below

一个面向 **TickType / 塔塔次方 DP104** 24×8 RGB 点阵屏的非官方 Windows 托盘控制器。项目重点是可读性、低干扰后台运行，以及尽量保守的 Raw HID 写入策略。

An unofficial Windows tray controller for the **TickType DP104** 24×8 RGB matrix. The project focuses on readability, unobtrusive background operation, and conservative Raw HID access.

## 中文

### v2.3 新增：应用级自动休眠

托盘新增 **自动休眠**：

- 关闭
- 5 分钟
- 15 分钟
- 30 分钟
- 1 小时
- 3 小时
- 6 小时
- 立即休眠（关闭所有 LED）
- 立即唤醒 LED

自动休眠不依赖键盘固件自己的空闲计时器，因为天气、时间、Codex WK 等后台 HID 更新可能会重置固件空闲时间。

v2.3 只把**真实键盘按键**视为用户活动：

1. 超过设定时间没有按键；
2. 程序发送已实机验证的全局 LED OFF 指令；
3. 休眠期间暂停天气、时间、WK、滚动文本和页面切换等 DP104 HID 写入；
4. LED OFF 之后发生的新按键才允许唤醒；
5. 唤醒后恢复之前选择的显示模式。

为避免休眠瞬间出现 `OFF -> ON`，v2.3 增加了按键事件序号和休眠转换保护，休眠前的残留 hook 事件不能触发唤醒。

### 主要功能

- 系统托盘运行，无控制台窗口。
- 托盘内直接切换：
  - 自动：敲键实时输入 / 空闲滚动。
  - 固定滚动。
  - 固定实时输入。
  - 固定天气。
  - 固定时钟。
  - 固定 Codex 周额度。
  - 天气 / 时钟 / WK 轮播。
  - 暂停更新。
- 托盘内开启/关闭 Windows 登录自启。
- 单实例保护，降低多个进程同时写 DP104 Raw HID 的风险。
- 支持打包为单文件 Windows EXE。
- 天气位置不写死在公开源码中。

### 隐私

此仓库不包含维护者/使用者的真实地理位置、经纬度、Codex token、ChatGPT account ID、Windows 用户名或用户机器绝对路径。

天气配置保存在本机：

```text
%APPDATA%\DP104Dashboard\config.json
```

参考 `config.example.json`：

```json
{
  "location_label": "MYCITY",
  "weather_latitude": "YOUR_LATITUDE",
  "weather_longitude": "YOUR_LONGITUDE",
  "weather_timezone": "Etc/UTC"
}
```

也可以使用：

```text
DP104_LOCATION_LABEL
DP104_LAT
DP104_LON
DP104_TZ
DP104_TYPING_IDLE
DP104_PAGE_SECONDS
```

### 源码运行

Python 3.12+：

```bash
pip install -r requirements.txt
python src/dp104_dashboard_v23.py --tray
```

`src/dp104_dashboard_v23.py` 是 v2.3 的托盘/休眠扩展，会复用隐私安全的 `src/dp104_dashboard.py` 基础实现。

### 构建 EXE

Windows 下双击：

```text
build\00_BUILD_EXE.cmd
```

生成：

```text
dist\DP104Dashboard.exe
```

### 已验证的 DP104 指令

页面：

- `1`：Real-time Typing / 实时输入
- `2`：Custom Pixel / 自定义像素
- `6`：Scrolling Message / 滚动文本

全局 LED 供电：

```text
OFF: 07 11 01 00 ...
ON : 07 11 01 01 ...
随后: 09 11 00 ...
```

官网固件休眠设置抓包：

```text
5 分钟  -> 07 11 02 01 ...
15 分钟 -> 07 11 02 02 ...
30 分钟 -> 07 11 02 03 ...
1 小时  -> code 04
3 小时  -> code 05
6 小时  -> code 06
```

v2.3 的自动休眠使用应用自己的空闲计时 + 全局 LED OFF/ON，而不是依赖上述固件空闲计时。

### 安全

DP104 固件对并发 HID 写入比较敏感。使用本程序时建议关闭官方 TickType 配置器，并避免同时运行其他 DP104 Raw HID 控制程序。

如果键盘整体无响应，请停止程序、重新插拔 USB 一次，不要连续重复发送控制命令。

---

## English

### v2.3: application-controlled auto sleep

The tray now includes an **Auto Sleep** submenu with:

- Off
- 5 minutes
- 15 minutes
- 30 minutes
- 1 hour
- 3 hours
- 6 hours
- Sleep now (global LED off)
- Wake LEDs now

The dashboard does not rely on the keyboard firmware's own inactivity timer because periodic weather, clock, quota, scrolling-text, or other HID updates can reset that timer.

v2.3 treats **physical keyboard keypresses only** as user activity:

1. no keypress occurs for the configured interval;
2. the app sends the verified global LED OFF command;
3. while asleep, dashboard display/HID updates are blocked;
4. only a new keypress that occurs after LED OFF can wake the device;
5. the previously selected display mode is restored after wake.

A key-event sequence guard prevents stale/pre-sleep hook events from producing an immediate `OFF -> ON` race.

### Features

- Windows system-tray application with no console window.
- Tray-selectable display modes:
  - Hybrid typing / idle scrolling.
  - Fixed scrolling.
  - Fixed real-time typing.
  - Fixed weather.
  - Fixed clock.
  - Fixed Codex weekly quota.
  - Weather / clock / weekly-quota rotation.
  - Pause.
- Windows sign-in auto-start toggle in the tray.
- Single-instance protection.
- Single-file Windows EXE build support.
- No personal weather location embedded in public source.

### Privacy

The public repository intentionally contains no real user coordinates, precise location, Codex token, ChatGPT account ID, Windows username, or user-specific absolute path.

Private weather settings belong in:

```text
%APPDATA%\DP104Dashboard\config.json
```

See `config.example.json`.

### Run from source

Python 3.12+:

```bash
pip install -r requirements.txt
python src/dp104_dashboard_v23.py --tray
```

`src/dp104_dashboard_v23.py` extends the privacy-safe base implementation in `src/dp104_dashboard.py`.

### Build EXE

On Windows, double-click:

```text
build\00_BUILD_EXE.cmd
```

Output:

```text
dist\DP104Dashboard.exe
```

### Verified DP104 commands

Display pages:

- `1`: Real-time Typing
- `2`: Custom Pixel
- `6`: Scrolling Message

Global LED power:

```text
OFF: 07 11 01 00 ...
ON : 07 11 01 01 ...
then: 09 11 00 ...
```

Captured firmware sleep settings:

```text
5 min  -> 07 11 02 01 ...
15 min -> 07 11 02 02 ...
30 min -> 07 11 02 03 ...
1 h    -> code 04
3 h    -> code 05
6 h    -> code 06
```

v2.3 intentionally uses its own inactivity timer plus global LED OFF/ON instead of relying on the firmware inactivity timer.

### Safety

The DP104 firmware appears sensitive to concurrent HID writers. Close the official TickType configurator while this application controls the keyboard and avoid running multiple DP104 Raw HID controllers at the same time.

If the whole keyboard becomes unresponsive, stop the application, reconnect USB once, and do not repeatedly retry control commands.

### Credits

Protocol research was informed by community projects including:

- Mikaneroni/MMSWaM
- change-42-yhmm/quota-float

This project is unofficial and is not affiliated with or endorsed by TickType or OpenAI.
