# sub2api-manager

[ZCode](https://github.com/) skill：管理 [sub2api](https://github.com/Wei-Shaw/sub2api) 系 AI API 网关站点 —— 余额查询、用量统计、API 密钥管理、订阅状态、卡密兑换。

## 安装

复制到用户级 skill 目录：

```bash
git clone https://github.com/mmotiy/sub2api-manager.git ~/.agents/skills/sub2api-manager
```

## 配置

```bash
S=~/.agents/skills/sub2api-manager/scripts/sub2api.py

# 方式一：账号密码登录（保存 access+refresh 双 token，之后自动续期）
python "$S" login --email you@example.com --password '***'

# 方式二：从浏览器 F12 复制任意 /api/v1/ 请求的 Bearer token
python "$S" set-token --token "eyJ..."
```

Token 与配置存于 `~/.sub2api-manager/config.json`，不进仓库。默认站点为 `https://vip.auto-code.net`，多站点用 `--profile 名字` + `set-token --base-url https://...`。

## 用法速览

```bash
python "$S" me                            # 余额 / 账户状态
python "$S" usage-stats --start 2026-10-01 --end 2026-10-08
python "$S" usage-trend --granularity day
python "$S" keys                          # 密钥列表（脱敏）
python "$S" key-create --name demo --group-id 49 --quota 5 --expires-days 30
python "$S" key-update 123 --status inactive
python "$S" key-delete 123 --yes
python "$S" groups                        # 可用分组（倍率/限额）
python "$S" subs && python "$S" subs-summary
python "$S" redeem-history
python "$S" redeem --code 卡密 --yes
```

全局选项放子命令前：`--json`（原始响应）、`--profile`（站点）、`--token`（临时覆盖）。

## 说明

- 写操作（POST/PUT/DELETE）自动携带 `Idempotency-Key` 头——sub2api 新版必填。
- access_token 约 24h 过期；有 refresh_token 时脚本 401 后自动续期，无需人工干预。
- 端点细节见 [references/api.md](references/api.md)（基于上游源码 + 线上实测，2026-10-08）。
- 二开站点与上游 master 可能存在少量端点差异，遇 404 参考 api.md 的替代方案。
