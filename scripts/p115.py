#!/usr/bin/env python3
"""
115 网盘命令行工具（跨平台通用版）

认证优先级：
  1. 环境变量 P115_COOKIE      —— 一行 'k=v; k=v'
  2. 环境变量 P115_COOKIE_FILE —— cookie 文件路径
  3. 当前目录 cookies.txt
  4. ~/.115/cookies.txt
  5. iOS Minis 路径 /var/minis/shared/115/cookies.txt

通用选项（任意命令都可加）：
  --json        输出原始 JSON（给 agent / 管道用）
  --no-color    禁用颜色

路径寻址：凡是接受 <id> 的地方，都可以直接写路径：
  "0"             根目录
  "/电影区"        根目录下的目录
  "/电影区/蜘蛛侠"  多级路径
  2956148449000553774   照旧可以传数字 id

命令：
  login [browser]           从本机浏览器导入 cookie
  set-cookie '<k=v; ...>'   手动保存 cookie
  whoami                    查看当前账号 + cookie 过期时间
  ls [cid|path] [offset] [limit]   列目录（默认根，自动翻页见 -a）
  tree [cid|path] [depth]   递归列目录（完整翻页，不会截断）
  info <id>                 文件/目录详情
  path <id>                 反查某个 id 的完整路径
  search <关键字>            全局搜索
  find <关键字> [cid|path]   在指定目录下递归找（按名字）
  du [cid|path]             统计目录占用
  mkdir <父cid|父path> <名称>  新建文件夹
  rename <id|path> <新名>    重命名（支持 --dry-run）
  mv <目标cid|path> <id...>  移动
  cp <目标cid|path> <id...>  复制
  rm <id...>                删除（进回收站，可恢复）
  purge <id...>             彻底删除（不可恢复，需要 --yes）
  rb                        列出回收站
  restore <rid...>          从回收站还原
  url <id|path>             拿下载直链（见下方说明）
  share <id...>             创建分享链接
  dl <id|path> [输出目录]    下载文件

关于 url / dl：115 的 CDN 直链需要客户端签名，直接 GET 会被 403。
本脚本会优先把直链打出来供你复制到浏览器 / 迅雷；若 CDN 拒绝，
会明确报错而不是假装成功。
"""
import os
import sys
import json
import ssl
import time
import threading
import unicodedata
import urllib.parse
import urllib.request

API = "https://webapi.115.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
CTX = ssl._create_unverified_context()

COOKIE_HOME = os.path.expanduser("~/.115")
IOS_CK = "/var/minis/shared/115/cookies.txt"

# 已知会失效的 errno
AUTH_ERRNOS = {"40101017", "40101018", "40101020", "990009", "990001"}

# ===== 全局请求节流 =====
# 115 接口有强限流：**最多每秒 2 次请求**，超了会直接返回 HTTP 405
# （HTML 错误页而不是 JSON），而且会持续一段时间。所有请求一律走 _throttle()。
MIN_INTERVAL = 1.0                     # 两次请求最小间隔（秒）→ 严格 1 次/秒
_last_request_at = [0.0]
_throttle_lock = threading.Lock()


def _throttle():
    """保证任意两次请求间隔 >= MIN_INTERVAL（严格 1 次/秒）。"""
    with _throttle_lock:
        now = time.monotonic()
        wait = MIN_INTERVAL - (now - _last_request_at[0])
        if wait > 0:
            time.sleep(wait)
        _last_request_at[0] = time.monotonic()

# ---------------------------------------------------------------- 全局开关
JSON_OUT = "--json" in sys.argv
DRY_RUN = "--dry-run" in sys.argv
ASSUME_YES = "--yes" in sys.argv


def _strip_flags(argv):
    return [a for a in argv if not a.startswith("--")]


# ---------------------------------------------------------------- cookie

def _candidate_paths():
    p = []
    if os.environ.get("P115_COOKIE_FILE"):
        p.append(os.environ["P115_COOKIE_FILE"])
    p.append(os.path.join(os.getcwd(), "cookies.txt"))
    p.append(os.path.join(COOKIE_HOME, "cookies.txt"))
    p.append(IOS_CK)
    return p


def cookie_path():
    for p in _candidate_paths():
        if p and os.path.exists(p):
            return p
    return None


def dedupe_cookie(s):
    """去掉重名 cookie（browser_cookie3 会把各子域同名 cookie 全导进来，
    一条请求里出现十几个 acw_tc 会让服务端解析失败）。保留第一次出现的。"""
    seen = {}
    order = []
    for kv in s.split(";"):
        kv = kv.strip()
        if not kv or "=" not in kv:
            continue
        k, _, v = kv.partition("=")
        k = k.strip()
        if k not in seen:
            order.append(k)
            seen[k] = v
    return "; ".join("%s=%s" % (k, seen[k]) for k in order)


def load_cookie():
    env = os.environ.get("P115_COOKIE", "").strip()
    if env:
        return dedupe_cookie(env)
    p = cookie_path()
    if not p:
        return None
    raw = open(p, encoding="utf-8").read().strip()
    return dedupe_cookie(raw) if raw else None


def save_cookie(s):
    dst = os.environ.get("P115_COOKIE_FILE") or os.path.join(COOKIE_HOME, "cookies.txt")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(dedupe_cookie(s.strip()))
    os.chmod(dst, 0o600)
    if os.path.isdir("/var/minis/shared/115"):
        try:
            with open(IOS_CK, "w", encoding="utf-8") as f:
                f.write(dedupe_cookie(s.strip()))
            os.chmod(IOS_CK, 0o600)
        except Exception:
            pass
    return dst


def cookie_from_browser(name):
    try:
        import browser_cookie3 as bc
    except ImportError:
        sys.exit("缺少依赖：pip install browser-cookie3\n"
                 "或者用 set-cookie 手动传入。")
    fn = {"chrome": bc.chrome, "edge": bc.edge, "safari": bc.safari,
          "firefox": bc.firefox, "brave": bc.brave, "chromium": bc.chromium,
          "opera": bc.opera, "vivaldi": bc.vivaldi}
    order = ([name] if name and name != "auto"
             else ["chrome", "edge", "brave", "chromium", "vivaldi",
                   "opera", "safari", "firefox"])
    last = None
    for b in order:
        f = fn.get(b)
        if not f:
            continue
        try:
            cj = f(domain_name="115.com")
        except Exception as e:
            last = "%s: %s" % (b, e)
            continue
        parts = ["%s=%s" % (c.name, c.value) for c in cj if c.name]
        if any(x.startswith("UID=") for x in parts):
            return "; ".join(parts), b
    sys.exit("未能从浏览器读取到 115 cookie。%s" % (last or "请确认已登录 115.com"))


def uid_issued():
    """UID=<uid>_<x>_<ts> 里的 ts 是**签发时间**，不是过期时间。
    旧版本把它当过期时间，导致刚登录也显示负数天数。这里保留解析但改名。"""
    c = load_cookie() or ""
    for kv in c.split(";"):
        kv = kv.strip()
        if kv.startswith("UID="):
            for p in kv[4:].split("_"):
                if p.isdigit() and len(p) >= 10:
                    return int(p)
    return None


# ---------------------------------------------------------------- 请求

def _out(obj):
    """--json 时输出紧凑 JSON。"""
    print(json.dumps(obj, ensure_ascii=False, indent=1 if not JSON_OUT else None))


def req(path, data=None, raw=False, retries=3):
    ck = load_cookie()
    if not ck:
        sys.exit("未配置 cookie。请先运行：p115.py login  或  p115.py set-cookie '<...>'")
    h = {"Cookie": ck, "User-Agent": UA, "Referer": "https://115.com/",
         "Accept": "application/json, text/plain, */*"}
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data, doseq=True).encode()
        h["Content-Type"] = "application/x-www-form-urlencoded; charset=utf-8"

    last_err = None
    for attempt in range(retries):
        _throttle()
        r = urllib.request.Request(API + path, data=body, headers=h)
        try:
            txt = urllib.request.urlopen(r, timeout=30, context=CTX).read().decode("utf-8", "replace")
            break
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:200]
            except Exception:
                pass
            # 405 / 429 / 5xx 是限流或临时故障，退避重试
            if e.code in (405, 429, 500, 502, 503, 504) and attempt < retries - 1:
                last_err = "HTTP %s" % e.code
                # 405 通常是限流，退避更狠一点：2s, 4s, 6s
                time.sleep(2.0 * (attempt + 1))
                continue
            sys.exit("HTTP %s 请求失败：%s\n%s" % (e.code, path, detail))
        except urllib.error.URLError as e:
            if attempt < retries - 1:
                last_err = str(e.reason)
                time.sleep(2.0 * (attempt + 1))
                continue
            sys.exit("网络不通：%s\n%s" % (path, e.reason))
    else:
        sys.exit("重试 %d 次仍失败：%s（%s）" % (retries, path, last_err))

    if raw:
        return txt
    try:
        j = json.loads(txt)
    except Exception:
        return {"_raw": txt}
    if isinstance(j, dict) and j.get("state") is False:
        if str(j.get("errno")) in AUTH_ERRNOS:
            sys.stderr.write("[!] cookie 已失效，请重新 login\n")
    return j


# ---------------------------------------------------------------- 显示

def disp_width(s):
    """中英混排的真实显示宽度：CJK/全角算 2，emoji 算 2。"""
    w = 0
    for ch in str(s):
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            w += 2
        elif ord(ch) >= 0x1F300:  # emoji
            w += 2
        else:
            w += 1
    return w


def pad(s, width):
    """按显示宽度左对齐填充。"""
    s = str(s)
    return s + " " * max(0, width - disp_width(s))


def hum(n):
    try:
        n = float(n)
    except Exception:
        return str(n)
    for u in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return "%.1f%s" % (n, u)
        n /= 1024
    return "%.1fPB" % n


def is_dir(it):
    return bool(it.get("cid")) and not it.get("fid")


def item_id(it):
    return it.get("cid") if is_dir(it) else it.get("fid")


# ---------------------------------------------------------------- 路径解析

def _items(cid, offset=0, limit=115, order="user_utime"):
    """列目录。内置 cid 回显校验：115 对不存在的 cid 会**静默返回根目录**，
    旧版本直接照单全收，打错一位就看到根目录还以为是成功了。"""
    q = [("aid", "1"), ("cid", str(cid)), ("o", order), ("asc", "1"),
         ("offset", offset), ("show_dir", "1"), ("limit", limit), ("natsort", "1")]
    r = req("/files?" + urllib.parse.urlencode(q))
    if isinstance(r, dict) and r.get("state") is not False:
        echoed = str(r.get("cid", ""))
        if str(cid) != "0" and echoed and echoed != str(cid):
            sys.exit("目录不存在：cid=%s（115 返回 cid=%s，通常是 id 打错了）"
                     % (cid, echoed))
    return r


def check_cid(cid):
    """显式校验一个 cid 是否存在，返回首条用于确认的响应。"""
    return _items(cid, 0, 1)


def resolve(target):
    """把 id 或路径统一解析成 cid。路径写法：0 / 123 / /a/b / a/b"""
    if target is None:
        return "0"
    t = str(target).strip()
    if t.isdigit():
        return t
    if not t.startswith("/"):
        t = "/" + t
    if t == "/":
        return "0"
    parts = [p for p in t.split("/") if p]
    cur = "0"
    for seg in parts:
        found = None
        off = 0
        while True:
            r = _items(cur, off, 115)
            page = r.get("data") or []
            for it in page:
                if is_dir(it) and it.get("n") == seg:
                    found = it["cid"]
                    break
            if found:
                break
            if len(page) < 115:
                break
            off += 115
        if not found:
            sys.exit("路径不存在：%s（在 /%s 下找不到「%s」）"
                     % (t, "/".join(parts[:parts.index(seg)]), seg))
        cur = found
    return cur


def iter_all(cid, order="user_utime"):
    """完整翻页遍历一个目录的所有条目，不再截断。
    翻页节奏由 req() 的 _throttle() 统一控制（<=2 次/秒）。"""
    off = 0
    while True:
        r = _items(cid, off, 115, order)
        page = r.get("data") or []
        for it in page:
            yield it
        if len(page) < 115:
            break
        off += 115


def resolve_item(target):
    """解析成单个条目（文件或目录），返回 (cid 或 fid, 是否目录, 条目)。"""
    t = str(target).strip()
    if t.isdigit():
        r = req("/files/get_info?" + urllib.parse.urlencode({"file_id": t}))
        d = r.get("data")
        if isinstance(d, list) and d:
            d = d[0]
        if not d:
            sys.exit("找不到 id=%s（%s）" % (t, r.get("error") or "接口无返回"))
        return t, is_dir(d), d
    # 路径：解析到父目录再找最后一段
    if not t.startswith("/"):
        t = "/" + t
    parts = [p for p in t.split("/") if p]
    if not parts:
        sys.exit("根目录不是文件")
    name = parts[-1]
    parent = resolve("/" + "/".join(parts[:-1])) if len(parts) > 1 else "0"
    for it in iter_all(parent):
        if it.get("n") == name:
            return item_id(it), is_dir(it), it
    sys.exit("找不到：%s" % t)


# ---------------------------------------------------------------- 命令

def _print_items(r):
    if JSON_OUT:
        _out(r)
        return
    if "data" not in r:
        _out(r)
        return
    print("count=%s  page=%s" % (r.get("count", "?"), len(r["data"])))
    if r["data"]:
        w = min(60, max(disp_width(it.get("n", "")) for it in r["data"]))
        for it in r["data"]:
            d = is_dir(it)
            tag = "[DIR] " if d else "[FILE]"
            size = "" if d else hum(it.get("s", 0))
            print("  %s %s %10s  id=%s" % (tag, pad(it.get("n", ""), w), size, item_id(it)))


def cmd_login(a):
    b = a[0] if a else "auto"
    ck, src = cookie_from_browser(b)
    print("imported from %s -> %s" % (src, save_cookie(ck)))


def cmd_setcookie(a):
    if not a:
        sys.exit("用法：set-cookie '<k=v; k=v>'")
    print("saved ->", save_cookie(a[0]))


def cmd_whoami(a):
    r = req("/user/info")
    if JSON_OUT:
        _out(r)
        return
    _out(r)
    exp = uid_issued()
    if exp:
        age = int(time.time()) - exp
        print("cookie 签发于: %s（%d 小时前）"
              % (time.strftime("%Y-%m-%d %H:%M", time.localtime(exp)), age // 3600))
        print("  注：这是签发时间，不是过期时间。115 不公开真实过期时刻。")
    src = "env P115_COOKIE" if os.environ.get("P115_COOKIE") else cookie_path()
    print("cookie source:", src)


def cmd_ls(a):
    target = a[0] if a else "0"
    off = a[1] if len(a) > 1 else 0
    lim = a[2] if len(a) > 2 else 115
    cid = resolve(target)
    r = _items(cid, off, lim)
    if not JSON_OUT:
        r["_resolved_cid"] = cid
    _print_items({k: v for k, v in r.items() if k != "_resolved_cid"})
    if not JSON_OUT and r.get("count") and int(r.get("count", 0)) > int(lim):
        more = int(r["count"]) - (int(off) + int(lim))
        if more > 0:
            print("... 还有 %d 条，用 ls %s %d %d 继续"
                  % (more, cid, int(off) + int(lim), lim))


def cmd_tree(a):
    target = a[0] if a else "0"
    depth = int(a[1]) if len(a) > 1 else 2
    root = resolve(target)

    if JSON_OUT:
        def build(c, d):
            out = []
            for it in iter_all(c):
                node = {"name": it.get("n"), "id": item_id(it),
                        "dir": is_dir(it), "size": it.get("s")}
                if is_dir(it) and d > 1:
                    node["children"] = build(it["cid"], d - 1)
                out.append(node)
            return out
        _out({"cid": root, "children": build(root, depth)})
        return

    total = {"dir": 0, "file": 0}

    def walk(c, d, prefix):
        items = list(iter_all(c))
        for i, it in enumerate(items):
            d_ = is_dir(it)
            total["dir" if d_ else "file"] += 1
            last = i == len(items) - 1
            branch = "└── " if last else "├── "
            mark = "[D]" if d_ else "[F]"
            print("%s%s%s %s" % (prefix, branch, mark, it.get("n", "")))
            if d_ and d > 1:
                walk(it["cid"], d - 1, prefix + ("    " if last else "│   "))

    walk(root, depth, "")
    print("\n共 %d 个目录 / %d 个文件（完整翻页，无截断）"
          % (total["dir"], total["file"]))


def cmd_info(a):
    if not a:
        sys.exit("用法：info <id|path>")
    fid, d, item = resolve_item(a[0])
    _out(item)


def cmd_path(a):
    if not a:
        sys.exit("用法：path <id>")
    fid = a[0]
    r = req("/files/get_info?" + urllib.parse.urlencode({"file_id": fid}))
    d = r.get("data")
    if isinstance(d, list) and d:
        d = d[0]
    if not d:
        sys.exit("找不到 id=%s" % fid)
    # 用父目录的 list 请求拿 path 字段（那里有完整路径）
    pid = d.get("pid") or "0"
    parent = _items(pid, 0, 1)
    chain = parent.get("path") or []
    names = [p.get("name") for p in chain if p.get("name")]
    if names and names[0] == "根目录":
        names = names[1:]
    full = "/" + "/".join(names + [d.get("n", "")])
    if JSON_OUT:
        _out({"id": fid, "name": d.get("n"), "path": full})
    else:
        print(full)


def cmd_search(a):
    if not a:
        sys.exit("用法：search <关键字>")
    q = [("aid", "1"), ("cid", "0"), ("offset", "0"), ("limit", "30"),
         ("show_dir", "1"), ("search_value", a[0]), ("type", "0")]
    _print_items(req("/files/search?" + urllib.parse.urlencode(q)))


def cmd_find(a):
    if not a:
        sys.exit("用法：find <关键字> [cid|path]")
    kw = a[0].lower()
    cid = resolve(a[1]) if len(a) > 1 else "0"
    hits = []

    def walk(c, prefix, depth):
        if depth > 6:
            return
        for it in iter_all(c):
            name = it.get("n", "")
            here = prefix + "/" + name
            if kw in name.lower():
                hits.append((here, item_id(it), is_dir(it), it.get("s")))
            if is_dir(it):
                walk(it["cid"], here, depth + 1)

    cid_check = check_cid(cid)
    walk(cid, "", 0)
    if JSON_OUT:
        _out({"keyword": a[0], "hits": [
            {"path": h[0], "id": h[1], "dir": h[2], "size": h[3]} for h in hits]})
        return
    print("找到 %d 项：" % len(hits))
    for path, iid, d, size in hits:
        print("  %s %s %10s  id=%s" % ("[DIR] " if d else "[FILE]",
                                       pad(path, 60), "" if d else hum(size), iid))


def cmd_du(a):
    target = a[0] if a else "0"
    cid = resolve(target)
    STAT = {"bytes": 0, "files": 0, "dirs": 0}

    def size_of(c, depth=0):
        total = 0
        n = 0
        try:
            items = list(iter_all(c))
        except SystemExit:
            return 0, 0
        for it in items:
            if is_dir(it):
                STAT["dirs"] += 1
                if depth < 8:
                    s, k = size_of(it["cid"], depth + 1)
                    total += s
                    n += k
            else:
                total += int(it.get("s") or 0)
                n += 1
        return total, n

    total, n = size_of(cid)
    STAT["bytes"] = total
    STAT["files"] = n
    if JSON_OUT:
        _out({"cid": cid, "bytes": total, "files": n, "dirs": STAT["dirs"]})
    else:
        print("占用：%s（%d 个文件 / %d 个子目录）" % (hum(total), n, STAT["dirs"]))


def cmd_mkdir(a):
    if len(a) < 2:
        sys.exit("用法：mkdir <父cid|父path> <名称>")
    pid = resolve(a[0])
    if DRY_RUN:
        print("[dry-run] 将在 cid=%s 下创建目录「%s」" % (pid, a[1]))
        return
    r = req("/files/add", [("pid", pid), ("cname", a[1])])
    _out(r)


def cmd_rename(a):
    if len(a) < 2:
        sys.exit("用法：rename <id|path> <新名> [--dry-run]")
    fid, d, item = resolve_item(a[0])
    old = item.get("n", "")
    if DRY_RUN:
        print("[dry-run] 重命名「%s」-> 「%s」" % (old, a[1]))
        return
    key = "files_new_name[%s]" % fid
    if d:
        key = "files_new_name[%s]" % fid
    r = req("/files/batch_rename", [(key, a[1])])
    if r.get("state"):
        print("已重命名：「%s」-> 「%s」" % (old, a[1]))
    else:
        _out(r)


def _batch(path, target, ids, key="fid", label=""):
    if not ids:
        sys.exit("没有要给的目标 id")
    data = []
    if target is not None:
        data.append(("pid", target))
    resolved = []
    for i, f in enumerate(ids):
        iid = resolve_item(f)[0] if not str(f).isdigit() else f
        resolved.append(iid)
        data.append(("%s[%d]" % (key, i), iid))
    if DRY_RUN:
        print("[dry-run] %s %d 项 -> %s（ids=%s）"
              % (label or path, len(resolved), target, ",".join(resolved)))
        return
    r = req(path, data)
    if r.get("state"):
        print("%s 完成，共 %d 项" % (label or path, len(resolved)))
    else:
        _out(r)
        sys.exit(1)


def cmd_mv(a):
    if len(a) < 2:
        sys.exit("用法：mv <目标cid|path> <id|path...>")
    _batch("/files/move", resolve(a[0]), a[1:], label="移动")


def cmd_cp(a):
    if len(a) < 2:
        sys.exit("用法：cp <目标cid|path> <id|path...>")
    _batch("/files/copy", resolve(a[0]), a[1:], label="复制")


def cmd_rm(a):
    if not a:
        sys.exit("用法：rm <id|path...>")
    _batch("/rb/delete", None, a, label="删除到回收站")


def cmd_purge(a):
    if not a:
        sys.exit("用法：purge <id|path...> --yes   （不可恢复！）")
    if not ASSUME_YES:
        sys.exit("purge 是不可恢复操作。确认要彻底删除请加 --yes。")
    # 先删进回收站
    _batch("/rb/delete", None, a, label="第一步：删除到回收站")
    print("已进回收站。115 未公开「按文件 id 彻底删除」的接口，")
    print("要彻底清空请在网页端回收站操作，或用 rb 确认后手动清理。")


def cmd_rb(a):
    r = req("/rb?" + urllib.parse.urlencode(
        [("aid", "1"), ("cid", "0"), ("offset", a[0] if a else "0"), ("limit", "115")]))
    if JSON_OUT:
        _out(r)
        return
    if "data" not in r:
        _out(r)
        return
    print("recycle count=%s" % r.get("count", "?"))
    for it in r["data"]:
        isd = str(it.get("type")) == "2"
        tag = "[DIR] " if isd else "[FILE]"
        size = "" if isd else hum(it.get("file_size", 0))
        print("  %s %s %10s  rid=%s  from=%s" % (
            tag, pad(it.get("file_name", ""), 44), size,
            it.get("id"), it.get("parent_name", "")))


def cmd_restore(a):
    if not a:
        sys.exit("用法：restore <rid...>")
    _batch("/rb/revert", None, a, key="rid", label="还原")


def cmd_url(a):
    if not a:
        sys.exit("用法：url <id|path>")
    fid, d, item = resolve_item(a[0])
    if d:
        sys.exit("「%s」是目录，没法直接拿直链。用 tree 看里面，再对单个文件取。" % item.get("n"))
    pc = item.get("pc")
    if not pc:
        sys.exit("这个条目没有 pickcode，无法取直链。")
    r = req("/files/download?" + urllib.parse.urlencode({"pickcode": pc}))
    if not r.get("state"):
        sys.exit("取直链失败：%s" % (r.get("msg") or r.get("error") or r))
    url = r.get("file_url") or ""
    if JSON_OUT:
        _out({"name": r.get("file_name"), "size": r.get("file_size"),
              "sha1": r.get("sha1"), "url": url})
        return
    print("文件名: %s" % r.get("file_name"))
    print("大小:   %s" % hum(r.get("file_size")))
    print("SHA1:   %s" % r.get("sha1"))
    print("直链:")
    print("  %s" % url)
    print("\n注意：115 CDN 对直链有防盗链校验，直接用程序 GET 大概率返回 403")
    print("（{\"message\":\"no cookie value\"}）。复制到浏览器 / 迅雷 / IDM 一般可用。")


def cmd_share(a):
    if not a:
        sys.exit("用法：share <id|path...>")
    ids = []
    for t in a:
        ids.append(resolve_item(t)[0])
    r = req("/share/send", [("file_ids", ",".join(ids)),
                            ("ignore_warn", "1"), ("is_share", "1")])
    if not r.get("state"):
        _out(r)
        sys.exit(1)
    d = r.get("data") or {}
    if JSON_OUT:
        _out({"share_url": d.get("share_url"), "share_code": d.get("share_code"),
              "receive_code": d.get("receive_code"), "count": d.get("file_count")})
        return
    print("分享链接: %s" % d.get("share_url"))
    if d.get("receive_code"):
        print("提取码:   %s" % d.get("receive_code"))
    print("\n提醒：分享删除接口（/share/delete）实测不可用，")
    print("需要撤销请到网页端「我的分享」里操作。")


def cmd_dl(a):
    if not a:
        sys.exit("用法：dl <id|path> [输出目录]")
    outdir = a[1] if len(a) > 1 else "."
    fid, d, item = resolve_item(a[0])
    if d:
        sys.exit("目录下载请用网页端；这里只支持单文件。")
    pc = item.get("pc")
    if not pc:
        sys.exit("没有 pickcode，无法下载。")
    r = req("/files/download?" + urllib.parse.urlencode({"pickcode": pc}))
    if not r.get("state"):
        sys.exit("取直链失败：%s" % (r.get("msg") or r.get("error")))
    url = r["file_url"]
    name = r.get("file_name") or "download.bin"
    dst = os.path.join(outdir, name)
    os.makedirs(outdir, exist_ok=True)
    h = {"User-Agent": UA, "Cookie": load_cookie() or "",
         "Referer": "https://115.com/"}
    try:
        rq = urllib.request.Request(url, headers=h)
        resp = urllib.request.urlopen(rq, timeout=30, context=CTX)
        total = int(resp.headers.get("Content-Length") or 0)
        got = 0
        with open(dst, "wb") as f:
            while True:
                buf = resp.read(262144)
                if not buf:
                    break
                f.write(buf)
                got += len(buf)
        print("下载完成: %s (%s)" % (dst, hum(got)))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        sys.exit("CDN 拒绝下载（HTTP %s）：%s\n"
                 "这是 115 的防盗链限制，直链需要用浏览器/迅雷打开。\n"
                 "直链：%s" % (e.code, body, url))


CMDS = {"login": cmd_login, "set-cookie": cmd_setcookie, "whoami": cmd_whoami,
        "ls": cmd_ls, "tree": cmd_tree, "info": cmd_info, "path": cmd_path,
        "search": cmd_search, "find": cmd_find, "du": cmd_du,
        "mkdir": cmd_mkdir, "rename": cmd_rename, "mv": cmd_mv, "cp": cmd_cp,
        "rm": cmd_rm, "purge": cmd_purge, "rb": cmd_rb, "restore": cmd_restore,
        "url": cmd_url, "share": cmd_share, "dl": cmd_dl}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    c = sys.argv[1]
    if c not in CMDS:
        sys.exit("unknown: %s\navailable: %s" % (c, " ".join(sorted(CMDS))))
    CMDS[c](_strip_flags(sys.argv[2:]))
