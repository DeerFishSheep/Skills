#!/usr/bin/env python3
"""
PanSou 网盘资源搜索 CLI

对接 PanSou API 服务，搜索全网盘资源链接并按网盘类型分类展示。
仅使用 Python 标准库，无第三方依赖。

用法: ps.py <命令> [参数...] [--json]

命令：
  search <关键词>            搜索资源
  check <链接...>            校验链接有效性
  health                     服务状态（插件、频道、存活统计）
  plugins                    列出可用插件与频道

search 参数：
  --type 115,quark,aliyun    网盘类型，逗号分隔，默认 115,quark,aliyun
  --from all|tg|plugin       数据来源，默认 all
  --limit 20                 返回条数上限
  --refresh                  跳过服务端缓存
  --check                    搜完自动验活（推荐）
  --json                     输出原始 JSON

check 参数：
  --json                     输出原始 JSON

服务端默认使用官方实例，可通过环境变量 PANSOU_API_BASE 覆盖。
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------- 配置

API_BASE = os.environ.get("PANSOU_API_BASE", "https://pansou.259952.xyz").rstrip("/")

# 默认搜索的网盘类型
DEFAULT_TYPES = ["115", "quark", "aliyun"]

# 网盘类型显示名
TYPE_LABEL = {
    "115": "115网盘",
    "quark": "夸克网盘",
    "aliyun": "阿里云盘",
    "baidu": "百度网盘",
    "uc": "UC网盘",
    "tianyi": "天翼云盘",
    "mobile": "移动云盘",
    "123": "123网盘",
    "xunlei": "迅雷网盘",
    "pikpak": "PikPak",
    "magnet": "磁力链接",
    "ed2k": "电驴链接",
    "others": "其他",
}

# 域名 → 网盘类型，用于 check 时自动识别
DOMAIN_TYPE = [
    ("115.com", "115"),
    ("115cdn.com", "115"),
    ("quark.cn", "quark"),
    ("pan.quark.cn", "quark"),
    ("aliyundrive.com", "aliyun"),
    ("alipan.com", "aliyun"),
    ("pan.baidu.com", "baidu"),
    ("yun.baidu.com", "baidu"),
    ("drive.uc.cn", "uc"),
    ("cloud.189.cn", "tianyi"),
    ("caiyun.139.com", "mobile"),
    ("yun.139.com", "mobile"),
    ("pan.xunlei.com", "xunlei"),
    ("mypikpak.com", "pikpak"),
    ("123pan.com", "123"),
    ("123684.com", "123"),
    ("123865.com", "123"),
]

# 检活接口支持的网盘类型
CHECKABLE = {"115", "quark", "aliyun", "baidu", "uc", "tianyi", "mobile", "123", "xunlei"}

CHECK_STATE = {
    "ok": ("✓", "有效"),
    "bad": ("✗", "失效"),
    "locked": ("🔒", "需要提取码"),
    "uncertain": ("?", "无法判定"),
    "unsupported": ("-", "不支持检测"),
}

TIMEOUT = 180

# ---------------------------------------------------------------- 全局开关

JSON_OUT = "--json" in sys.argv


def err(msg, code=1):
    """统一的中文错误出口。"""
    sys.stderr.write("✗ %s\n" % msg)
    sys.exit(code)


def out(obj):
    """JSON 输出。"""
    print(json.dumps(obj, ensure_ascii=False, indent=None if JSON_OUT else 1))


def pad(s, width):
    """按显示宽度左对齐（中文算 2 格）。"""
    import unicodedata
    w = 0
    for ch in str(s):
        if unicodedata.east_asian_width(ch) in ("W", "F") or ord(ch) >= 0x1F300:
            w += 2
        else:
            w += 1
    return str(s) + " " * max(0, width - w)


def hum(n):
    """字节数转可读大小。"""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return str(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return "%.1f%s" % (n, u)
        n /= 1024
    return "%.1fPB" % n


# ---------------------------------------------------------------- HTTP

def request(path, payload=None):
    """向 PanSou 发请求。payload 存在时用 POST + JSON，否则 GET。

    注意：GET 请求不要给 Request 传 method="GET" —— 显式指定 method 时
    urllib 会走一条不同的发送路径，在某些 TLS 环境下会报
    "400 The plain HTTP request was sent to HTTPS port"。不传 method
    时 urllib 根据有无 data 自动判断，行为正确。
    """
    url = API_BASE + path
    headers = {"Accept": "application/json", "User-Agent": "pansou-skill/1.0"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)

    last = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:200]
            except Exception:
                pass
            # 5xx 重试一次，4xx 直接报错
            if e.code >= 500 and attempt == 0:
                last = "HTTP %s" % e.code
                time.sleep(2)
                continue
            err("请求失败（HTTP %s）：%s\n  %s%s"
                % (e.code, path, body, API_BASE))
        except urllib.error.URLError as e:
            if attempt == 0:
                last = str(e.reason)
                time.sleep(2)
                continue
            err("无法连接 PanSou 服务：%s\n  当前地址: %s\n"
                "  可用 PANSOU_API_BASE 环境变量指定其他实例" % (e.reason, API_BASE))
        except json.JSONDecodeError:
            err("服务返回的不是 JSON，可能地址不对：%s" % API_BASE)
    err("重试后仍失败：%s" % last)


# ---------------------------------------------------------------- 工具

def detect_type(url):
    """从链接域名判断网盘类型。"""
    u = str(url).lower()
    if u.startswith("magnet:"):
        return "magnet"
    if u.startswith("ed2k:"):
        return "ed2k"
    for domain, t in DOMAIN_TYPE:
        if domain in u:
            return t
    return "others"


def fmt_time(s):
    """ISO 时间转 YYYY-MM-DD。"""
    if not s:
        return ""
    m = re.match(r"(\d{4}-\d{2}-\d{2})", str(s))
    return m.group(1) if m else ""


# ---------------------------------------------------------------- check

def check_links(items, batch=200):
    """批量验活。items 为 [(url, password, disk_type), ...]。返回结果列表。

    服务端单次上限 256 条，这里按 200 分批。
    """
    results = []
    for i in range(0, len(items), batch):
        chunk = items[i:i + batch]
        payload = {"items": [
            {"disk_type": t, "url": u, "password": p or ""}
            for (u, p, t) in chunk
        ]}
        d = request("/api/check/links", payload)
        results.extend(d.get("results") or [])
        if i + batch < len(items):
            time.sleep(1)
    return results


# ---------------------------------------------------------------- search

def do_search(kw, types, src="all", limit=20, refresh=False):
    """调用搜索接口，返回 (merged_by_type, total)。"""
    payload = {"kw": kw, "res": "merge", "src": src}
    if types:
        payload["cloud_types"] = types
    if refresh:
        payload["refresh"] = True

    d = request("/api/search", payload)
    if d.get("code") != 0:
        err("搜索失败：%s" % (d.get("message") or d))

    data = d.get("data") or {}
    merged = data.get("merged_by_type") or {}
    total = data.get("total") or 0

    # 按 limit 截断每个类型
    trimmed = {}
    left = limit
    for t in types or list(merged):
        if left <= 0:
            break
        arr = merged.get(t) or []
        if arr:
            trimmed[t] = arr[:left]
            left -= len(trimmed[t])
    return trimmed, total


def cmd_search(a):
    """搜索网盘资源。"""
    args = _strip_flags(a)
    if not args:
        err("用法：ps.py search <关键词> [--type 115,quark] [--limit 20] [--check]")

    kw = " ".join(args)
    types = _opt("--type").split(",") if _opt("--type") else list(DEFAULT_TYPES)
    types = [t.strip() for t in types if t.strip()]
    src = _opt("--from") or "all"
    limit = int(_opt("--limit") or 20)
    refresh = "--refresh" in sys.argv
    do_check = "--check" in sys.argv

    t0 = time.time()
    merged, total = do_search(kw, types, src, limit, refresh)
    elapsed = time.time() - t0

    if not merged:
        if JSON_OUT:
            out({"keyword": kw, "total": total, "results": {}})
        else:
            print("未找到「%s」的资源" % kw)
            print("  total=%d，可尝试：换关键词、放宽 --type、或加 --refresh" % total)
        return

    # 展平便于验活
    flat = []
    for t, arr in merged.items():
        for it in arr:
            flat.append((it, t))

    check_map = {}
    if do_check:
        items = [(it.get("url") or "", it.get("password") or "", t)
                 for it, t in flat if detect_type(it.get("url")) in CHECKABLE]
        if items:
            try:
                for r, (u, _p, _t) in zip(check_links(items), items):
                    check_map[u] = r
            except SystemExit:
                raise

    if JSON_OUT:
        payload = {"keyword": kw, "total": total, "elapsed": round(elapsed, 1),
                   "results": {}}
        for t, arr in merged.items():
            rows = []
            for it in arr:
                row = {"url": it.get("url"), "password": it.get("password"),
                       "note": it.get("note"), "datetime": it.get("datetime"),
                       "source": it.get("source")}
                r = check_map.get(it.get("url"))
                if r:
                    row["state"] = r.get("state")
                    row["summary"] = r.get("summary")
                rows.append(row)
            payload["results"][t] = rows
        out(payload)
        return

    # 文字输出
    n = sum(len(v) for v in merged.values())
    print("搜索「%s」：%d 条（%.1fs）" % (kw, n, elapsed))
    if check_map:
        ok = sum(1 for r in check_map.values() if r.get("state") == "ok")
        print("验活：%d/%d 有效" % (ok, len(check_map)))
    print()

    for t, arr in merged.items():
        print("── %s（%d 条）" % (TYPE_LABEL.get(t, t), len(arr)))
        rows = []
        for it in arr:
            r = check_map.get(it.get("url"))
            order = {"ok": 0, "locked": 1, "uncertain": 2, "bad": 3,
                     "unsupported": 4, None: 5}
            rows.append((order.get(r.get("state") if r else None, 5), it, r))
        rows.sort(key=lambda x: x[0])

        for _o, it, r in rows:
            mark = ""
            if r:
                mark = CHECK_STATE.get(r.get("state"), ("?", ""))[0] + " "
            note = (it.get("note") or "").strip().replace("\n", " ")
            if len(note) > 62:
                note = note[:62] + "…"
            print("  %s%s" % (mark, note))
            meta = []
            dt = fmt_time(it.get("datetime"))
            if dt:
                meta.append(dt)
            if it.get("source"):
                meta.append(it["source"])
            if r and r.get("state") != "ok":
                meta.append(r.get("summary") or "")
            if meta:
                print("     %s" % " · ".join(x for x in meta if x))
            print("     %s" % it.get("url"))
            print()


# ---------------------------------------------------------------- check 命令

def cmd_check(a):
    """校验分享链接是否有效。"""
    urls = _strip_flags(a)
    if not urls:
        err("用法：ps.py check <链接...>")

    items = []
    for u in urls:
        # 链接里可能自带 password=xxx
        pw = ""
        m = re.search(r"[?&](?:password|pwd|p)=([0-9a-zA-Z]+)", u)
        if m:
            pw = m.group(1)
        items.append((u, pw, detect_type(u)))

    res = check_links(items)

    if JSON_OUT:
        out({"results": res})
        return

    ok = 0
    for r in res:
        st = r.get("state")
        icon, label = CHECK_STATE.get(st, ("?", st))
        if st == "ok":
            ok += 1
        print("%s %-12s %s" % (icon, label, r.get("url")))
        if r.get("summary") and st != "ok":
            print("             %s" % r["summary"])
        if st == "bad":
            print("             该链接已失效，建议换其他来源")
    if len(res) > 1:
        print("\n%d/%d 有效" % (ok, len(res)))


# ---------------------------------------------------------------- health

def cmd_health(a):
    """查看服务状态。"""
    d = request("/api/health")
    if JSON_OUT:
        out(d)
        return
    print("服务地址: %s" % API_BASE)
    print("状态:     %s" % d.get("status", "?"))
    print("认证:     %s" % ("已启用" if d.get("auth_enabled") else "无，可直接调用"))
    print("插件:     %s 个%s" % (
        d.get("plugin_count", 0),
        "（%s）" % ", ".join((d.get("plugins") or [])[:5]) if d.get("plugins") else ""))
    print("频道:     %s 个" % d.get("channels_count", 0))
    tg = d.get("tg") or {}
    if tg:
        print("TG 可达:  %s" % ("是" if tg.get("reachable") else "否：%s" % (tg.get("reason") or "")))


def cmd_plugins(a):
    """列出可用插件与频道。"""
    d = request("/api/health")
    plugins = d.get("plugins") or []
    channels = d.get("channels") or []
    if JSON_OUT:
        out({"plugins": plugins, "channels": channels})
        return
    print("插件（%d 个）:" % len(plugins))
    for i in range(0, len(plugins), 4):
        print("  " + "  ".join(pad(p, 22) for p in plugins[i:i + 4]))
    print("\nTG 频道（%d 个）:" % len(channels))
    for i in range(0, len(channels), 4):
        print("  " + "  ".join(pad(c, 22) for c in channels[i:i + 4]))


# ---------------------------------------------------------------- 参数解析

def _opt(name):
    """取 --name value 形式的值。"""
    try:
        i = sys.argv.index(name)
    except ValueError:
        return None
    if i + 1 >= len(sys.argv):
        return None
    return sys.argv[i + 1]


def _strip_flags(argv):
    """去掉所有 --xxx 及其值，留下位置参数。"""
    value_flags = {"--type", "--from", "--limit"}
    res = []
    i = 0
    while i < len(argv):
        x = argv[i]
        if x in value_flags:
            i += 2
            continue
        if x.startswith("--"):
            i += 1
            continue
        res.append(x)
        i += 1
    return res


# ---------------------------------------------------------------- 入口

CMDS = {
    "search": cmd_search,
    "check": cmd_check,
    "health": cmd_health,
    "plugins": cmd_plugins,
}


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        print("\n可用命令: %s" % " ".join(sorted(CMDS)))
        return
    cmd = args[0]
    if cmd not in CMDS:
        err("未知命令：%s\n可用：%s" % (cmd, " ".join(sorted(CMDS))))
    try:
        CMDS[cmd](args[1:])
    except KeyboardInterrupt:
        err("已中断", 130)
    except BrokenPipeError:
        pass


if __name__ == "__main__":
    main()
