# Sub2API 管理 API 参考

依据：上游源码 `Wei-Shaw/sub2api`（backend/internal/server/routes/*.go）+ 线上站点
`https://vip.auto-code.net` 2026-10-08 逐项实测。线上为二开部署，与上游 master 有少量差异，已标注。

## 通用约定

- Base: `{base_url}/api/v1`
- 认证：`Authorization: Bearer <access_token>`（JWT，约 24h 过期）
- 响应信封：`{"code": 0, "message": "success", "data": ...}`；`code != 0` 即业务错误，
  二开版错误信息在 `message`（中文）+ `reason`（大写蛇形错误码）+ `error.code`。
- **写操作（POST/PUT/DELETE）必须带 `Idempotency-Key: <uuid>` 请求头**，否则返回
  `code=400, reason=IDEMPOTENCY_KEY_REQUIRED`（实测确认，上游源码 handler/admin/idempotency_helper.go）。
- 分组等资源用数字 id（不是名字）。时间均为 ISO 8601 带 `+08:00` 时区。

## 认证

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/auth/login` | body `{email, password}` → `{access_token, refresh_token, expires_in, token_type, user}` |
| POST | `/auth/refresh` | body `{refresh_token}` → 新的 access+refresh 对 |
| POST | `/auth/logout` | 可选 body `{refresh_token}` 撤销 |
| GET | `/auth/me` | 当前用户全量信息（含 balance） |

登录接口有 20 次/分钟限流。`expires_in` 为 access_token 秒数（实测 86400）。

## 余额 / 账户

- `GET /auth/me` → `data.balance`（USD 现金余额，float）、`total_recharged`（历史充值总额）、
  `concurrency`（并发上限）、`rpm_limit`、`status`、`last_active_at`、identities/auth_bindings（绑定信息）。
- `GET /user/profile` — 同类信息的用户面板口径。
- `GET /user/aff` — 推广/返利额度（源码有，未实测）。

## 用量统计

| 方法 | 路径 | 参数 |
|---|---|---|
| GET | `/usage` | 明细列表：`page` `page_size` `start_date` `end_date` `api_key_id` `group_id` `model` `timezone` `sort_by` `sort_order` |
| GET | `/usage/stats` | 聚合：`start_date` `end_date` `api_key_id` `timezone`；不传日期=全部 |
| GET | `/usage/dashboard/stats` | 面板总览（含 today_* 与 rpm/tpm） |
| GET | `/usage/dashboard/trend` | `granularity=day\|week\|month` + 日期；返回 trend[] 按日/周/月 |
| GET | `/usage/dashboard/models` | 按模型统计 |
| GET | `/usage/errors` | 错误请求列表 |

`/usage/stats` 关键字段：`total_requests` `total_input_tokens` `total_output_tokens`
`total_cache_read_tokens` `total_cost`（本站计费成本）`total_actual_cost`（上游实际成本）
`night_discount{enabled, active_now, discount_ratio, start_time, end_time, timezone}`。
注意 token 过期后 401；statistical 接口属重查询，勿高频轮询。

**版本差异**：`GET /user/api-keys/:id/usage/daily`（按 key 按日用量）上游 master 有，
线上二开版 **404**。要按 key 统计用 `/usage?api_key_id=N&start_date=...`。

## API 密钥管理 `/keys`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/keys?page=1&page_size=20` | 列表，data: `{items[], total, page, page_size, pages}` |
| GET | `/keys/:id` | 单个 |
| POST | `/keys` | 创建 |
| PUT | `/keys/:id` | 更新 |
| DELETE | `/keys/:id` | 删除（不可恢复） |

**创建** body（实测可用）：

```json
{
  "name": "必填",
  "group_id": 49,                // 可选；不填用默认分组
  "quota": 5.0,                  // USD 配额；0 或 null = 无限
  "expires_in_days": 30,         // 可选
  "ip_whitelist": ["1.2.3.4"],   // 可选
  "ip_blacklist": [],
  "custom_key": "sk-...",        // 可选自定义 key 值（上游源码支持）
  "rate_limit_5h": 0, "rate_limit_1d": 0, "rate_limit_7d": 0
}
```

响应 data 含**完整 key 值**（仅创建时返回明文）与 `expires_at`。

**更新** body（字段可选，nil 不修改）：`name` `status(active|inactive→线上存为disabled)`
`group_id` `quota`(0=无限) `expires_at`(ISO) `reset_quota`(bool 重置已用)
`ip_whitelist`/`ip_blacklist`（`[]` 清空）`rate_limit_*` `reset_rate_limit_usage`。

**单条 item 字段**：`id` `key` `name` `group_id` `group{name,rate_multiplier,...}` `status`
`quota` `quota_used` `usage_5h/1d/7d` `expires_at` `last_used_at` `current_concurrency`。

## 订阅 `/subscriptions`（只读）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/subscriptions` | 全部订阅；data 为数组，元素 `{pool_key, pool{...}}` |
| GET | `/subscriptions/active` | 当前生效（无则 `[]`） |
| GET | `/subscriptions/progress` | 进度（无则 `[]`） |
| GET | `/subscriptions/summary` | `{active_count, active_entitlement_count, daily/weekly/monthly_used_usd, *_limit_usd, total_used_usd, subscriptions[]}` |

`pool` 关键字段：`status`(active/expired) `starts_at` `expires_at` `daily_limit_usd`
`daily_usage_usd` `weekly_*` `monthly_*` `group{name,rate_multiplier}` `display_group_name`。

订阅**不能**从用户侧 API 创建——购买走支付/卡密流程（`POST /redeem` 兑换卡密、payment 路由），
skill 不覆盖。

## 分组

- `GET /groups/available` — 用户可用分组；元素含 `id` `name` `platform` `rate_multiplier`
  `daily_limit_usd` `allow_image_generation` `description` 等。创建/改 key 的 `group_id` 从这里取。
- `GET /groups/rates` — 分组倍率（源码有）。

## 其他可能有用的端点

- `POST /redeem` body `{code}` — 卡密兑换。**不需要 Idempotency-Key**（实测无效码直接返回
  `code=404, reason=REDEEM_CODE_NOT_FOUND`）。响应 data：`{message, type, value,
  new_balance?, new_concurrency?}`。type 实测取值 `balance`（充余额）/`campaign_balance`
  （活动余额）/`subscription`（开订阅）。
  兑换消耗卡密不可恢复。有 10 次/分钟限流。- `GET /redeem/history` — 兑换历史。默认返回最近 25 条数组；带 `page`/`page_size` 参数则返回
  分页信封 `{items,total,...}`。字段：`id` `code`（已用码的码值）`type` `value` `status`(used)
  `used_at` `created_at` `group_id` `validity_days`。
- `GET /announcements` / `POST /announcements/:id/read` — 公告
- `GET /user/platform-quotas` — 平台配额
- `GET /channels/available` — 可用渠道
- `GET /v1/models`（网关层，用 sk- key 而非 JWT）— 检查某 key 可用模型
