# DP104 Dashboard

> 中文 | English below

一个面向 **TickType / 塔塔次方 DP104** 24×8 RGB 点阵屏的非官方 Windows 托盘控制器。项目重点是可读性、低干扰后台运行，以及尽量保守的 Raw HID 写入策略。

An unofficial Windows tray controller for the **TickType DP104** 24×8 RGB matrix. The project focuses on readability, unobtrusive background operation, and conservative Raw HID access.

---

## 中文

### 功能

- 系统托盘运行，无控制台窗口。
- 托盘内直接切换显示模式：
  - 自动：敲击键盘时切到 DP104 自带的实时输入页；停止敲击约 5 秒后恢复滚动。
  - 固定滚动信息。
  - 固定实时输入。
  - 固定天气。
  - 固定时钟。
  - 固定 Codex 周额度。
  - 天气 / 时钟 / WK 轮播。
  - 暂停更新。
- 托盘内直接开启/关闭 Windows 登录自启。
- 单实例保护，避免多个进程同时向 DP104 Raw HID 写数据。
- 支持打包为无控制台的单文件 Windows EXE。
- 天气位置**不写死在源码中**。
- Codex 配额读取使用本机已有的 Codex Desktop 登录状态；项目不会把访问令牌写入仓库或设置文件。

### 隐私设计

此仓库不包含维护者或使用者的地理位置、经纬度、Codex token、ChatGPT account ID、Windows 用户名或本地绝对路径。

天气配置属于本地私有配置。请复制：

```text
config.example.json
```

并将实际值保存到：

```text
%APPDATA%\DP104Dashboard\config.json
```

示例结构：

```json
{
  "location_label": "MYCITY",
  "weather_latitude": "YOUR_LATITUDE",
  "weather_longitude": "YOUR_LONGITUDE",
  "weather_timezone": "Etc/UTC"
}
```

`config.json` 已被 `.gitignore` 排除，不应提交到 Git。

也可以使用环境变量：

```text
DP104_LOCATION_LABEL
DP104_LAT
DP104_LON
DP104_TZ
DP104_TYPING_IDLE
DP104_PAGE_SECONDS
```

### 安装与运行

源码运行需要 Python 3.12+：

```bash
pip install -r requirements.txt
python src/dp104_dashboard.py --tray
```

Windows 用户如果想要普通 EXE，直接双击：

```text
build\00_BUILD_EXE.cmd
```

生成文件：

```text
dist\DP104Dashboard.exe
```

双击 EXE 后程序进入系统托盘。右键托盘图标即可选择模式、开关开机自启、刷新或退出。

### DP104 页面

本项目当前使用的页面编号来自实际抓包验证：

- `1`：Real-time Typing / 实时输入
- `2`：Custom Pixel / 自定义像素
- `6`：Scrolling Message / 滚动文本

Raw HID 目标为 DP104 的 `VID 0xE560 / PID 0xE104`，像素与控制通信使用 MI_01 / interface 1。

### 安全说明

DP104 固件对并发 HID 写入比较敏感。项目因此使用共享锁和单实例机制，避免自身多个线程/进程同时写入设备。

建议使用本程序时关闭官方 TickType 配置器，不要同时运行其他 DP104 Raw HID 控制程序。

原生滚动速度的控制命令目前尚未验证，因此项目不会猜测并发送未知速度指令。

### Codex 配额

Codex 配额功能读取本机 Codex Desktop 已有登录状态，并请求当前配额数据。它不会把 token、JWT、account ID 或原始授权文件写入项目目录。

该配额接口属于当前实现观察到的行为，并不是承诺稳定的公开 OpenAI API，未来可能变化。

### 致谢

DP104 Raw HID 协议研究参考了社区项目：

- Mikaneroni/MMSWaM
- change-42-yhmm/quota-float（Codex Desktop 配额读取实现思路）

本项目是非官方社区工具，与 TickType 或 OpenAI 无隶属或背书关系。

---

## English

### Features

- Runs as a Windows system-tray application with no console window.
- Switch display modes directly from the tray:
  - Hybrid: switch to the DP104 firmware's real-time typing page on keypress, then return to scrolling after about 5 seconds of inactivity.
  - Fixed scrolling information.
  - Fixed real-time typing.
  - Fixed weather.
  - Fixed clock.
  - Fixed Codex weekly quota.
  - Weather / clock / weekly-quota rotation.
  - Pause updates.
- Enable or disable Windows sign-in auto-start from the tray menu.
- Single-instance protection to reduce the risk of concurrent Raw HID writes.
- Can be packaged as a single-file, windowless Windows EXE.
- No personal weather location is embedded in source code.
- Codex quota support uses the existing local Codex Desktop session and does not persist access tokens in the repository or application settings.

### Privacy

This repository intentionally contains no maintainer/user coordinates, precise location, Codex token, ChatGPT account ID, Windows username, or machine-specific absolute path.

Weather configuration is local/private. Copy:

```text
config.example.json
```

and save your real values to:

```text
%APPDATA%\DP104Dashboard\config.json
```

Example:

```json
{
  "location_label": "MYCITY",
  "weather_latitude": "YOUR_LATITUDE",
  "weather_longitude": "YOUR_LONGITUDE",
  "weather_timezone": "Etc/UTC"
}
```

`config.json` is ignored by Git and should never be committed.

Environment-variable configuration is also supported:

```text
DP104_LOCATION_LABEL
DP104_LAT
DP104_LON
DP104_TZ
DP104_TYPING_IDLE
DP104_PAGE_SECONDS
```

### Install and run

Python 3.12+ is recommended:

```bash
pip install -r requirements.txt
python src/dp104_dashboard.py --tray
```

For a normal Windows executable, double-click:

```text
build\00_BUILD_EXE.cmd
```

The output is:

```text
dist\DP104Dashboard.exe
```

Double-click the EXE to start the tray application. Right-click the tray icon to choose a display mode, toggle auto-start, refresh, or exit.

### DP104 pages

The currently used page IDs were verified from actual HID captures:

- `1`: Real-time Typing
- `2`: Custom Pixel
- `6`: Scrolling Message

The target device is `VID 0xE560 / PID 0xE104`; pixel/control traffic uses MI_01 / interface 1.

### Safety

The DP104 firmware appears sensitive to concurrent HID writers. This project therefore uses a shared HID lock and single-instance protection.

Close the official TickType configurator while this application is controlling the keyboard, and avoid running multiple DP104 Raw HID controllers simultaneously.

The native scrolling-speed command has not been verified, so the project deliberately does not send guessed speed-control packets.

### Codex quota

The Codex quota feature reads the existing local Codex Desktop login state and queries current quota information. It does not write access tokens, JWTs, account IDs, or raw auth files into the project directory.

The quota endpoint is an observed implementation detail, not a guaranteed stable public OpenAI API, and may change.

### Credits

DP104 Raw HID protocol research was informed by community projects including:

- Mikaneroni/MMSWaM
- change-42-yhmm/quota-float (Codex Desktop quota approach)

This is an unofficial community project and is not affiliated with or endorsed by TickType or OpenAI.
