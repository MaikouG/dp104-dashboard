# DP104 Dashboard v2.4.0

## 中文

v2.4 把天气位置配置正式移到托盘界面，因此 Release 中的 `DP104Dashboard.exe` 是通用版本，不再需要针对某个地区单独编译。

### 新功能

- 托盘新增“天气位置设置...”
- 支持输入城市/地区搜索地点
- 支持从多个候选地点中选择
- 自动填写经纬度和时区
- 支持手动输入经纬度
- 支持自定义点阵滚动中的位置显示名称
- 支持清除天气位置
- 保存后无需重启，立即刷新天气
- 继续支持 5 / 15 / 30 分钟、1 / 3 / 6 小时应用级自动休眠

### 隐私

EXE 不包含开发者或用户的定位信息。位置仅保存在本机 `%APPDATA%\DP104Dashboard\config.json`。

地区搜索和天气服务由 Open-Meteo 提供。

## English

v2.4 moves weather-location setup into the tray UI, so the Release `DP104Dashboard.exe` is now a universal build with no embedded user location.

### New

- Tray weather-location settings
- Place-name search with selectable results
- Automatic latitude/longitude/timezone filling
- Manual coordinate input
- Editable location label
- Clear-location action
- Changes apply without restart
- Guarded application-controlled auto sleep retained

### Privacy

No user location is embedded in the executable. Weather configuration is stored locally under `%APPDATA%\DP104Dashboard\config.json`.
