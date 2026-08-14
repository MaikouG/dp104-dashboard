# Privacy Audit / 隐私审计

## 中文

公开版本已执行以下清理：

- 移除源码中原先硬编码的城市/地区名称。
- 移除源码中原先硬编码的经纬度。
- 天气位置改为本地 `config.json` 或环境变量配置。
- 未提交 Codex `auth.json`、access token、JWT、account ID、cookie。
- 未提交 Windows 用户名或用户目录绝对路径。
- `.gitignore` 排除了本地配置、认证文件、日志和构建产物。
- 对仓库文本执行了已知地理字符串与常见 token 格式扫描，未发现匹配。

代码中出现的 `account_id`、`access_token` 等名称是变量/字段名，不包含真实值。

## English

The public source was sanitized as follows:

- Removed hard-coded city/region names.
- Removed hard-coded latitude/longitude values.
- Weather location now comes from local `config.json` or environment variables.
- No Codex `auth.json`, access token, JWT, account ID, or cookie is committed.
- No Windows username or user-specific absolute home path is committed.
- `.gitignore` excludes local configuration, auth files, logs, and build outputs.
- Repository text was scanned for the known location strings and common token formats; no matches were found.

Names such as `account_id` and `access_token` that remain in source code are field/variable names only; no real secret values are embedded.
