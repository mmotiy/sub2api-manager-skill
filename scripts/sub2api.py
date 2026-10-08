#!/usr/bin/env python3
"""sub2api 站点管理 CLI：余额查询 / 用量统计 / API 密钥管理 / 订阅管理。

仅用标准库。配置存于 ~/.sub2api-manager/config.json（按 profile 分站点）。
写操作自动携带 Idempotency-Key 头（该系站点必填）。
401 时自动尝试用 refresh_token 续期一次，失败则提示重新登录。

用法示例：
  python sub2api.py me                          # 余额与账户状态
  python sub2api.py keys                        # 密钥列表
  python sub2api.py key create --name xxx --quota 5 --expires-days 30
  python sub2api.py key update 123 --status inactive
  python sub2api.py key delete 123 --yes
  python sub2api.py usage-stats --start 2026-10-01 --end 2026-10-08
  python sub2api.py subs                        # 订阅列表
"""
import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

CONFIG_PATH = Path.home() / ".sub2api-manager" / "config.json"
DEFAULT_BASE = "https://vip.auto-code.net"


# ---------- 配置 ----------

def load_cfg():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            die(f"配置文件损坏 {CONFIG_PATH}: {e}")
    return {"profiles": {}}


def save_cfg(cfg):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def get_profile(name):
    cfg = load_cfg()
    cfg.setdefault("profiles", {})
    p = cfg["profiles"].get(name)
    if p is None:
        p = {"base_url": DEFAULT_BASE}
        cfg["profiles"][name] = p
        save_cfg(cfg)
    p.setdefault("base_url", DEFAULT_BASE)
    return cfg, p


def die(msg, code=1):
    print(f"错误: {msg}", file=sys.stderr)
    sys.exit(code)


# ---------- HTTP ----------

def http(method, base_url, path, token=None, body=None, idem=False):
    """发请求。返回 (status, json_dict_or_None)。"""
    url = base_url.rstrip("/") + path
    data = None
    headers = {"accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["content-type"] = "application/json"
    if token:
        headers["authorization"] = f"Bearer {token}"
    if idem:
        headers["Idempotency-Key"] = str(uuid.uuid4())
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:500]}
    except urllib.error.URLError as e:
        die(f"网络错误访问 {url}: {e.reason}")


def extract(payload):
    """解包站点统一信封 {code, message, data}；失败时带出错误信息。"""
    if not isinstance(payload, dict) or "data" not in payload:
        die(f"响应格式异常: {json.dumps(payload, ensure_ascii=False)[:400]}")
    if payload.get("code") not in (0, None):
        detail = payload.get("message", "")
        reason = payload.get("reason", "")
        die(f"接口返回 code={payload['code']} {reason}: {detail}"[:500])
    return payload["data"]


def call(args, method, path, body=None, idem=False, retry=True):
    _, p = get_profile(args.profile)
    token = getattr(args, "token", None) or p.get("access_token")
    if not token:
        die(f"profile '{args.profile}' 没有可用 token。请运行 login，或用 --token 传入。")
    status, payload = http(method, p["base_url"], path, token=token, body=body, idem=idem)
    if status == 401 and retry:
        # 先尝试 refresh_token 续期一次
        if p.get("refresh_token"):
            st, pl = http("POST", p["base_url"], "/api/v1/auth/refresh",
                          body={"refresh_token": p["refresh_token"]})
            if st == 200 and isinstance(pl, dict) and pl.get("code") == 0:
                d = pl["data"]
                cfg = load_cfg()
                prof = cfg["profiles"][args.profile]
                prof["access_token"] = d["access_token"]
                prof["refresh_token"] = d.get("refresh_token", prof["refresh_token"])
                save_cfg(cfg)
                return call(args, method, path, body=body, idem=idem, retry=False)
        die("token 已失效且无法自动续期。请让用户提供新 token（运行 set-token）或用账号密码重新 login。")
    if status >= 400:
        msg = ""
        if isinstance(payload, dict):
            msg = payload.get("message") or payload.get("raw") or ""
        die(f"HTTP {status} {method} {path}: {msg}"[:500])
    return extract(payload)


# ---------- 输出 ----------

def fmt_money(v):
    return "-" if v is None else f"{v:,.2f}"


def fmt_time(s):
    if not s:
        return "-"
    return s.replace("T", " ").split(".")[0]


def print_json(data):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def key_trunc(k):
    return k[:12] + "..." + k[-6:] if k and len(k) > 22 else k


# ---------- 命令实现 ----------

def cmd_login(a):
    if not (a.email and a.password):
        die("login 需要 --email 和 --password")
    _, p = get_profile(a.profile)
    status, payload = http("POST", p["base_url"], "/api/v1/auth/login",
                           body={"email": a.email, "password": a.password})
    if status != 200 or (isinstance(payload, dict) and payload.get("code") not in (0, None)):
        msg = payload.get("message", "") if isinstance(payload, dict) else payload
        die(f"登录失败 HTTP {status}: {msg}")
    d = extract(payload)
    cfg = load_cfg()
    prof = cfg["profiles"][a.profile]
    prof["access_token"] = d["access_token"]
    prof["refresh_token"] = d.get("refresh_token", "")
    prof["email"] = a.email
    save_cfg(cfg)
    u = d.get("user") or {}
    print(f"登录成功（profile={a.profile}），token 已保存。")
    print(f"  用户: {u.get('email', a.email)}  余额: {fmt_money(u.get('balance'))} USD")
    print(f"  access_token 有效期: {d.get('expires_in', '?')} 秒")


def cmd_set_token(a):
    cfg, p = get_profile(a.profile)
    p["access_token"] = a.token
    if a.refresh_token:
        p["refresh_token"] = a.refresh_token
    if a.base_url:
        p["base_url"] = a.base_url
    save_cfg(cfg)
    # 立即验证
    try:
        me = call(a, "GET", "/api/v1/auth/me")
        print(f"token 已保存并验证（profile={a.profile}）。")
        print(f"  用户: {me.get('email')}  余额: {fmt_money(me.get('balance'))} USD")
    except SystemExit:
        print(f"token 已保存（profile={a.profile}），但验证请求未通过，请检查 token 是否正确。")
        raise


def cmd_me(a):
    me = call(a, "GET", "/api/v1/auth/me?timezone=Asia%2FShanghai")
    if a.json:
        print_json(me)
        return
    print(f"账户: {me.get('email')}  (id={me.get('id')}, role={me.get('role')}, status={me.get('status')})")
    print(f"余额: {fmt_money(me.get('balance'))} USD")
    print(f"累计充值: {fmt_money(me.get('total_recharged'))}")
    print(f"并发上限: {me.get('concurrency')}  RPM限制: {me.get('rpm_limit') or '无'}")
    print(f"最近活跃: {fmt_time(me.get('last_active_at'))}  注册: {fmt_time(me.get('created_at'))}")


def cmd_usage_stats(a):
    q = {}
    if a.start:
        q["start_date"] = a.start
    if a.end:
        q["end_date"] = a.end
    if a.api_key_id:
        q["api_key_id"] = a.api_key_id
    q["timezone"] = "Asia/Shanghai"
    d = call(a, "GET", "/api/v1/usage/stats?" + urllib.parse.urlencode(q))
    if a.json:
        print_json(d)
        return
    rng = " / ".join(x for x in (a.start, a.end) if x) or "全部时间"
    print(f"用量统计（{rng}）:")
    print(f"  请求数: {d.get('total_requests', 0)}  总tokens: {d.get('total_tokens', 0):,}")
    print(f"  输入: {d.get('total_input_tokens', 0):,}  输出: {d.get('total_output_tokens', 0):,}"
          f"  缓存读: {d.get('total_cache_read_tokens', 0):,}")
    print(f"  计费成本: {fmt_money(d.get('total_cost'))}  实际成本: {fmt_money(d.get('total_actual_cost'))} USD")
    nd = d.get("night_discount") or {}
    if nd.get("enabled"):
        state = "生效中" if nd.get("active_now") else "未生效"
        print(f"  夜间折扣: {nd.get('discount_ratio')} 折（{nd.get('start_time')}~{nd.get('end_time')} {nd.get('timezone')}），当前{state}")


def cmd_usage_trend(a):
    q = {"granularity": a.granularity, "timezone": "Asia/Shanghai"}
    if a.start:
        q["start_date"] = a.start
    if a.end:
        q["end_date"] = a.end
    d = call(a, "GET", "/api/v1/usage/dashboard/trend?" + urllib.parse.urlencode(q))
    if a.json:
        print_json(d)
        return
    print(f"趋势（{d.get('start_date')} ~ {d.get('end_date')}，按{a.granularity}）:")
    for row in d.get("trend", []):
        print(f"  {row.get('date')}  请求 {row.get('requests', 0):>6}  tokens {row.get('total_tokens', 0):>10,}"
              f"  成本 {fmt_money(row.get('cost'))}  实际 {fmt_money(row.get('actual_cost'))}")


def cmd_keys(a):
    d = call(a, "GET", "/api/v1/keys?page=%d&page_size=%d" % (a.page, a.page_size))
    items = d.get("items", [])
    if a.json:
        print_json(d)
        return
    print(f"API 密钥（{d.get('total', len(items))} 个，第 {d.get('page')}/{d.get('pages')} 页）:")
    for k in items:
        gname = (k.get("group") or {}).get("name", "-")
        quota = "无限" if not k.get("quota") else f"{k['quota']:.2f} (已用 {k.get('quota_used') or 0:.2f})"
        kv = k.get("key", "")
        shown = kv if a.show_key else key_trunc(kv)
        print(f"  [{k['id']}] {k['name']}  状态={k['status']}  分组={gname}(id={k.get('group_id')})")
        print(f"      key={shown}  配额={quota}  5h/1d/7d用量={k.get('usage_5h')}/{k.get('usage_1d')}/{k.get('usage_7d')}")
        print(f"      过期={fmt_time(k.get('expires_at'))}  最近使用={fmt_time(k.get('last_used_at'))}")


def cmd_key_show(a):
    d = call(a, "GET", f"/api/v1/keys/{a.id}")
    print_json(d) if a.json else print(json.dumps(d, ensure_ascii=False, indent=2))


def cmd_key_create(a):
    body = {"name": a.name}
    if a.group_id is not None:
        body["group_id"] = a.group_id
    if a.quota is not None:
        body["quota"] = a.quota
    if a.expires_days is not None:
        body["expires_in_days"] = a.expires_days
    if a.ip_whitelist:
        body["ip_whitelist"] = [x.strip() for x in a.ip_whitelist.split(",") if x.strip()]
    if a.ip_blacklist:
        body["ip_blacklist"] = [x.strip() for x in a.ip_blacklist.split(",") if x.strip()]
    d = call(a, "POST", "/api/v1/keys", body=body, idem=True)
    if a.json:
        print_json(d)
        return
    print(f"已创建密钥 id={d['id']}:")
    print(f"  名称: {d['name']}  分组id={d.get('group_id')}  配额={'无限' if not d.get('quota') else d['quota']}")
    print(f"  完整key（仅此一次完整展示）: {d['key']}")
    print(f"  过期: {fmt_time(d.get('expires_at'))}")


def cmd_key_update(a):
    body = {}
    if a.name:
        body["name"] = a.name
    if a.status:
        body["status"] = a.status
    if a.quota is not None:
        body["quota"] = a.quota
    if a.expires_at:
        body["expires_at"] = a.expires_at
    if a.reset_quota:
        body["reset_quota"] = True
    if a.ip_whitelist is not None:
        body["ip_whitelist"] = [x.strip() for x in a.ip_whitelist.split(",") if x.strip()]
    if not body:
        die("没有指定任何修改项")
    d = call(a, "PUT", f"/api/v1/keys/{a.id}", body=body, idem=True)
    if a.json:
        print_json(d)
        return
    print(f"已更新密钥 id={a.id}: 状态={d.get('status')} 配额={d.get('quota')} 名称={d.get('name')}")


def cmd_key_delete(a):
    if not a.yes:
        die("删除不可恢复。确认请加 --yes")
    d = call(a, "DELETE", f"/api/v1/keys/{a.id}", idem=True)
    if a.json:
        print_json(d)
        return
    print(f"已删除密钥 id={d.get('id')}: {d.get('message', 'ok')}")


def cmd_groups(a):
    d = call(a, "GET", "/api/v1/groups/available")
    if a.json:
        print_json(d)
        return
    print(f"可用分组（{len(d)} 个）:")
    for g in d:
        lim = f" 日限{g['daily_limit_usd']}" if g.get("daily_limit_usd") else ""
        print(f"  [{g['id']}] {g['name']}  平台={g.get('platform')}  倍率={g.get('rate_multiplier')}{lim}")
        desc = (g.get("description") or "").strip()
        if desc:
            print(f"      {desc[:80]}")


def _subs(a, suffix=""):
    return call(a, "GET", "/api/v1/subscriptions" + suffix)


def cmd_subs(a):
    d = _subs(a)
    if a.json:
        print_json(d)
        return
    print(f"订阅（{len(d)} 条）:")
    for s in d:
        p = s.get("pool") or {}
        g = p.get("group") or {}
        print(f"  [pool id={p.get('id')}] {g.get('name', p.get('display_group_name'))}")
        print(f"      状态={p.get('status')}  周期={fmt_time(p.get('starts_at'))} ~ {fmt_time(p.get('expires_at'))}")
        lim = p.get("daily_limit_usd") or 0
        if lim:
            print(f"      日限额 {fmt_money(lim)}  已用 {fmt_money(p.get('daily_usage_usd'))}"
                  f"  周已用 {fmt_money(p.get('weekly_usage_usd'))}/{fmt_money(p.get('weekly_limit_usd'))}"
                  f"  月已用 {fmt_money(p.get('monthly_usage_usd'))}/{fmt_money(p.get('monthly_limit_usd'))}")


def cmd_subs_active(a):
    d = _subs(a, "/active")
    print_json(d) if a.json else print(f"当前生效订阅: {len(d)} 条" + ("" if d else "（无，当前按余额计费）"))


def cmd_subs_summary(a):
    d = _subs(a, "/summary")
    if a.json:
        print_json(d)
        return
    print(f"订阅汇总: 生效订阅 {d.get('active_count')} 个 / 生效权益 {d.get('active_entitlement_count')} 个")
    for label, u, l in (("日", d.get("daily_used_usd"), d.get("daily_limit_usd")),
                        ("周", d.get("weekly_used_usd"), d.get("weekly_limit_usd")),
                        ("月", d.get("monthly_used_usd"), d.get("monthly_limit_usd")),
                        ("累计", d.get("total_used_usd"), None)):
        lim = fmt_money(l) if l else "∞"
        print(f"  {label}: 已用 {fmt_money(u)} / 限额 {lim} USD")


def cmd_subs_progress(a):
    d = _subs(a, "/progress")
    print_json(d) if a.json else print(f"订阅进度: {len(d)} 条")
    for s in d:
        print(f"  {json.dumps(s, ensure_ascii=False)[:200]}")


def cmd_redeem(a):
    if not a.yes:
        die("兑换会消耗卡密且不可恢复。确认请加 --yes")
    d = call(a, "POST", "/api/v1/redeem", body={"code": a.code})
    if a.json:
        print_json(d)
        return
    print(f"兑换成功: 类型={d.get('type')}  面值={d.get('value')}")
    if d.get("new_balance") is not None:
        print(f"  新余额: {fmt_money(d['new_balance'])} USD")
    if d.get("new_concurrency") is not None:
        print(f"  新并发: {d['new_concurrency']}")
    if d.get("message"):
        print(f"  {d['message']}")


def cmd_redeem_history(a):
    path = "/api/v1/redeem/history"
    if a.page or a.page_size:
        path += f"?page={max(a.page or 1, 1)}&page_size={a.page_size or 20}"
    d = call(a, "GET", path)
    items = d.get("items", d) if isinstance(d, dict) else d
    if a.json:
        print_json(d)
        return
    n = d.get("total", len(items)) if isinstance(d, dict) else len(items)
    print(f"兑换历史（{n} 条）:")
    for r in items:
        print(f"  [{r['id']}] {r.get('type')}  面值={r.get('value')}  状态={r.get('status')}"
              f"  使用时间={fmt_time(r.get('used_at'))}")


# ---------- CLI ----------

def main():
    ap = argparse.ArgumentParser(description="sub2api 站点管理 CLI")
    ap.add_argument("--profile", default="default", help="站点配置名（默认 default）")
    ap.add_argument("--token", help="临时 access_token（优先于配置文件）")
    ap.add_argument("--json", action="store_true", help="输出原始 JSON")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("login", help="账号密码登录并保存 token")
    p.add_argument("--email", required=True)
    p.add_argument("--password", required=True)
    p.set_defaults(fn=cmd_login)

    p = sub.add_parser("set-token", help="手工保存 token（从浏览器复制）")
    p.add_argument("--token", required=True, help="access_token（Bearer 后面的部分）")
    p.add_argument("--refresh-token", help="可选 refresh_token")
    p.add_argument("--base-url", help="站点地址")
    p.set_defaults(fn=cmd_set_token)

    p = sub.add_parser("me", help="余额与账户状态")
    p.set_defaults(fn=cmd_me)

    p = sub.add_parser("usage-stats", help="用量统计（不传日期=全部）")
    p.add_argument("--start", help="开始日期 YYYY-MM-DD")
    p.add_argument("--end", help="结束日期 YYYY-MM-DD")
    p.add_argument("--api-key-id", type=int)
    p.set_defaults(fn=cmd_usage_stats)

    p = sub.add_parser("usage-trend", help="用量趋势")
    p.add_argument("--granularity", default="day", choices=["day", "week", "month"])
    p.add_argument("--start")
    p.add_argument("--end")
    p.set_defaults(fn=cmd_usage_trend)

    p = sub.add_parser("keys", help="密钥列表")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--page-size", type=int, default=20)
    p.add_argument("--show-key", action="store_true", help="显示完整 key")
    p.set_defaults(fn=cmd_keys)

    p = sub.add_parser("key-show", help="查看单个密钥")
    p.add_argument("id", type=int)
    p.set_defaults(fn=cmd_key_show)

    p = sub.add_parser("key-create", help="创建密钥")
    p.add_argument("--name", required=True)
    p.add_argument("--group-id", type=int)
    p.add_argument("--quota", type=float, help="配额 USD，0=无限")
    p.add_argument("--expires-days", type=int)
    p.add_argument("--ip-whitelist", help="逗号分隔")
    p.add_argument("--ip-blacklist", help="逗号分隔")
    p.set_defaults(fn=cmd_key_create)

    p = sub.add_parser("key-update", help="更新密钥")
    p.add_argument("id", type=int)
    p.add_argument("--name")
    p.add_argument("--status", choices=["active", "inactive"])
    p.add_argument("--quota", type=float)
    p.add_argument("--expires-at", help="ISO 8601 时间")
    p.add_argument("--reset-quota", action="store_true")
    p.add_argument("--ip-whitelist", help="逗号分隔；传空串清空")
    p.set_defaults(fn=cmd_key_update)

    p = sub.add_parser("key-delete", help="删除密钥（不可恢复）")
    p.add_argument("id", type=int)
    p.add_argument("--yes", action="store_true")
    p.set_defaults(fn=cmd_key_delete)

    p = sub.add_parser("groups", help="可用分组列表")
    p.set_defaults(fn=cmd_groups)

    p = sub.add_parser("subs", help="订阅列表")
    p.set_defaults(fn=cmd_subs)
    p = sub.add_parser("subs-active", help="当前生效订阅")
    p.set_defaults(fn=cmd_subs_active)
    p = sub.add_parser("subs-summary", help="订阅用量汇总")
    p.set_defaults(fn=cmd_subs_summary)
    p = sub.add_parser("subs-progress", help="订阅进度")
    p.set_defaults(fn=cmd_subs_progress)

    p = sub.add_parser("redeem", help="卡密兑换（消耗性，需 --yes）")
    p.add_argument("--code", required=True, help="卡密")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(fn=cmd_redeem)

    p = sub.add_parser("redeem-history", help="兑换历史")
    p.add_argument("--page", type=int)
    p.add_argument("--page-size", type=int)
    p.set_defaults(fn=cmd_redeem_history)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
