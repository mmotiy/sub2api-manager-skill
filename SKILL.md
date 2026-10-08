---
name: sub2api-manager
version: 1.0.0
description: "管理 sub2api 系 AI API 网关站点（主站点 https://vip.auto-code.net，支持多站点 profile）：余额查询、用量统计与趋势、API 密钥增删改查/启停/配额、订阅状态与进度、可用分组。当用户提到查余额、auto-code、sub2api、API key 管理、密钥额度/过期、订阅到期/用量、key 配额时使用——即使没有明说 'sub2api'。也适用于其他 sub2api 二开站点（用户提供 base_url 与 token 时）。"
---

# Sub2API 站点管理

管理 sub2api 站点（vip.auto-code.net 等）的余额、用量、API 密钥与订阅。全部操作通过本 skill 自带的 CLI 脚本完成，不要手写 curl（写操作必须带 `Idempotency-Key` 头，脚本已自动处理）。

## 快速用法

脚本位于**本 skill 目录**下的 `scripts/sub2api.py`（纯标准库，Python 3 直接跑；下文以 `$S` 代指其绝对路径，即 `<本skill目录>/scripts/sub2api.py`）。配置与 token 存于 `~/.sub2api-manager/config.json`（按 profile 分站点），不依赖 skill 目录、可随时覆盖更新。

```bash
S="<本skill目录>/scripts/sub2api.py"   # 用实际安装路径替换

# 余额/账户
python3 "$S" me                        # 余额、累计充值、并发、状态

# 用量统计
python3 "$S" usage-stats --start 2026-10-01 --end 2026-10-08
python3 "$S" usage-trend --granularity day

# API 密钥
python3 "$S" keys                      # 列表（默认脱敏；--show-key 显示完整）
python3 "$S" key-create --name 名字 --group-id 49 --quota 5 --expires-days 30
python3 "$S" key-update 123 --status inactive      # 停用
python3 "$S" key-update 123 --group-id 35          # 切换分组（实测支持）
python3 "$S" key-update 123 --quota 0 --reset-quota  # 改无限额并重置已用
python3 "$S" key-delete 123 --yes                  # 不可恢复，先向用户确认

# 分组与订阅
python3 "$S" groups                    # 可用分组（含倍率、限额）
python3 "$S" subs                      # 订阅列表（含周期与日/周/月用量）
python3 "$S" subs-summary              # 订阅用量汇总

# 卡密兑换
python3 "$S" redeem-history            # 兑换历史
python3 "$S" redeem --code 卡密 --yes  # 兑换（消耗卡密，先向用户确认）
```

> Windows 无 `python3` 时用 `python`；脚本带可执行位，也可直接 `./scripts/sub2api.py`。

所有命令支持 `--json` 输出原始响应、`--profile <名>` 切换站点、`--token <jwt>` 临时覆盖 token。注意全局选项（`--json`/`--profile`/`--token`）要放在子命令**前面**。

## Token 生命周期（重要）

- access_token 约 **24 小时过期**（JWT exp 字段）。401 时脚本会用 refresh_token 自动续期一次。
- 续期也失败时脚本会报错停止——此时**向用户要新 token**（让用户从浏览器 F12 复制任意 `/api/v1/` 请求的 `authorization: Bearer` 后串），然后：
  ```bash
  python3 "$S" set-token --token "eyJ..."          # 保存并自动验证
  ```
- 若用户愿意给账号密码，可 `python3 "$S" login --email xx --password yy`，脚本会保存 access+refresh 双 token 以后自动续期。
- **多站点**：每个站点一个 profile。新站点首次 `python3 "$S" --profile 名字 set-token --base-url https://站点 --token eyJ...`（或 `--profile 名字 login ...`），之后该 profile 的所有命令都带 `--profile 名字`。`python3 "$S" profiles` 查看全部站点、账号与 token 有效期。

## 行为约定

1. **查询类**（me/keys/subs/usage-stats/groups）直接执行并解读结果：余额给 USD 数值、密钥重点看状态/配额余量/过期时间、订阅重点看 expires_at 与日限额用量。
2. **写操作**（key create/update/delete/redeem）：创建与更新直接执行；**删除与卡密兑换（redeem）不可恢复，执行前必须向用户复述对象（密钥 id/名称或卡密）并确认**。
3. 展示密钥时默认脱敏；用户明确要完整 key 时才用 `--show-key` 或从 `key-create` 输出取。
4. 余额语境：`balance` 是 USD 现金余额；`total_recharged` 是历史充值总额。分组倍率（rate_multiplier）影响实际扣费，解读成本时结合 `usage-stats` 的 cost（计费成本）与 actual_cost（上游实际成本）。
5. 错误信息带 `reason` 字段时原样带给用户（如 IDEMPOTENCY_KEY_REQUIRED 表示脚本未带上幂等键——正常不会发生，出现说明用户绕过了脚本手写请求）。

## 深入参考

需要绕过脚本直接调 API（如脚本没覆盖的新操作）时，读 `references/api.md`：完整端点清单、请求/响应结构、认证方式，均经 2026-10-08 源码（Wei-Shaw/sub2api）+ 线上实测双重确认。注意线上为二开版本，个别新版端点可能 404（如 `/user/api-keys/:id/usage/daily`），遇到时改用 `/usage?api_key_id=N` 代替。
