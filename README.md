# DP104 Dashboard

> 中文 | English below

一个面向 **TickType / 塔塔次方 DP104** 24×8 RGB 点阵屏的非官方 Windows 托盘控制器。

**v2.4 的 Release EXE 是通用版本，不内置任何用户的地理位置。** 每个用户都可以从托盘搜索地区，或手动输入经纬度；配置仅保存在自己的电脑上。

---

## 中文

### v2.4 新增：托盘天气位置设置

托盘新增：

```text
天气位置：未设置 / <你的显示名称>
天气位置设置...
```

点击 **天气位置设置...** 后，可以使用两种方式：

1. **地区搜索**
   - 输入城市、地区或邮编；
   - 从搜索结果中选择正确地点；
   - 自动填写经纬度和时区；
   - 显示名称仍可自己修改。

2. **手动坐标**
   - 手动输入纬度和经度；
   - 时区可以填写 IANA 时区名称，也可以直接使用 `auto`。

保存后不需要重启程序，天气缓存会立即失效并重新获取天气。

### 隐私

Release EXE 和公开仓库均**不包含任何人的真实位置**。

天气位置仅保存到：

```text
%APPDATA%\DP104Dashboard\config.json
```

地区搜索时，用户输入的搜索文字会发送给 Open-Meteo Geocoding API；获取天气时，会把所选经纬度发送给 Open-Meteo Weather API。DP104 Dashboard 没有自己的定位服务器。

可以随时在天气设置窗口点击 **清除位置**。

### 自动休眠

托盘支持：

- 关闭
- 5 分钟
- 15 分钟
- 30 分钟
- 1 小时
- 3 小时
- 6 小时
- 立即休眠（关闭所有 LED）
- 立即唤醒 LED

应用级自动休眠只把**真实键盘按键**视为用户活动。休眠期间停止天气、时间、WK、滚动文本和页面切换等 DP104 HID 更新。

v2.3 起加入按键事件序号保护，避免休眠前残留 hook 事件造成 `OFF -> ON`。

### 其他功能

- 自动：敲键时显示原生实时输入，停止敲击约 5 秒后恢复滚动。
- 固定滚动信息。
- 固定实时输入。
- 固定天气。
- 固定时钟。
- 固定 Codex 周额度。
- 天气 / 时钟 / WK 轮播。
- 暂停更新。
- Windows 登录自启。
- 单实例保护。
- 单文件无控制台 Windows EXE。

### 源码运行

Python 3.12+：

```bash
pip install -r requirements.txt
python src/dp104_dashboard_v24.py --tray
```

### 构建 Windows EXE

双击：

```text
build\00_BUILD_EXE.cmd
```

输出：

```text
dist\DP104Dashboard.exe
```

这个 EXE 可以直接作为 GitHub Release 的 Windows 下载版本。它**不需要在编译时写入位置**。

### DP104 已验证控制

页面：

- `1`：Real-time Typing / 实时输入
- `2`：Custom Pixel / 自定义像素
- `6`：Scrolling Message / 滚动文本

全局 LED：

```text
OFF: 07 11 01 00 ...
ON : 07 11 01 01 ...
随后: 09 11 00 ...
```

官网固件休眠设置抓包：

```text
5 分钟  -> 01
15 分钟 -> 02
30 分钟 -> 03
1 小时  -> 04
3 小时  -> 05
6 小时  -> 06
```

v2.4 的自动休眠仍使用应用自己的空闲计时 + 全局 LED OFF/ON，不依赖固件空闲计时。

### 安全

DP104 固件对并发 HID 写入比较敏感。使用 DP104 Dashboard 时请关闭官方 TickType 配置器，并避免同时运行其他 DP104 Raw HID 控制程序。

如果整个键盘停止响应，请停止程序并重新插拔 USB 一次，不要连续重复发送控制命令。

---

## English

### v2.4: tray weather-location settings

The v2.4 Release EXE is a **universal build with no embedded user location**.

Open:

```text
Weather location settings...
```

from the tray. Users can either:

- search for a city/place/postal code and choose a result, which fills latitude, longitude, and timezone automatically; or
- manually enter latitude and longitude, with timezone set to an IANA name or `auto`.

Changes apply without restarting the application.

### Privacy

No personal location is embedded in the EXE or repository.

Weather settings are stored locally at:

```text
%APPDATA%\DP104Dashboard\config.json
```

Place-name searches send the entered search text to the Open-Meteo Geocoding API. Weather requests send the configured coordinates to the Open-Meteo Weather API. DP104 Dashboard does not operate a location server.

The location can be cleared from the settings window at any time.

### Auto sleep

Tray options:

- Off
- 5 minutes
- 15 minutes
- 30 minutes
- 1 hour
- 3 hours
- 6 hours
- Sleep now (global LED off)
- Wake LEDs now

Only physical keyboard keypresses count as activity. Dashboard HID/display updates are blocked while asleep, and only a new post-sleep keypress may wake the LEDs.

### Other features

- Hybrid real-time typing / idle scrolling.
- Fixed scrolling, typing, weather, clock, and Codex weekly quota modes.
- Weather / clock / weekly-quota rotation.
- Pause updates.
- Windows sign-in auto-start.
- Single-instance protection.
- Single-file, windowless Windows EXE build.

### Run from source

```bash
pip install -r requirements.txt
python src/dp104_dashboard_v24.py --tray
```

### Build

Double-click:

```text
build\00_BUILD_EXE.cmd
```

Output:

```text
dist\DP104Dashboard.exe
```

The same universal EXE can be distributed through GitHub Releases. Location is configured after installation, not at build time.

### Credits

Protocol research was informed by community projects including:

- Mikaneroni/MMSWaM
- change-42-yhmm/quota-float

This is an unofficial community project and is not affiliated with or endorsed by TickType or OpenAI.
