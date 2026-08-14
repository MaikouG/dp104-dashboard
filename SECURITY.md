# Security / 安全

## 中文

请不要提交以下内容：

- `%APPDATA%\DP104Dashboard\config.json`
- `.env`
- `.codex/auth.json`
- 任何 access token、JWT、cookie、account ID
- 精确家庭/办公地点、经纬度
- 带有个人路径或用户名的日志
- 编译产物中的本地调试配置

如果你意外提交了凭据，不要只删除文件；应立即撤销/轮换凭据并清理 Git 历史。

## English

Never commit:

- `%APPDATA%\DP104Dashboard\config.json`
- `.env`
- `.codex/auth.json`
- access tokens, JWTs, cookies, or account IDs
- precise home/work locations or coordinates
- logs containing personal paths or usernames
- local debug configuration from build outputs

If a credential is committed accidentally, deleting the file is not enough. Revoke/rotate the credential and remove it from Git history.
