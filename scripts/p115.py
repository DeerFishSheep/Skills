#!/usr/bin/env python3
"""
115 网盘 CLI（p115client 薄外壳）

全部接口调用走 p115client，本文件只负责：cookie 管理、全局限流、
路径寻址、中文输出、危险操作拦截。

用法: p115.py <命令> [参数...] [--json] [--dry-run] [--yes]

限流铁律：115 最多每秒 2 次请求，超了返回 HTTP 405 并封禁数分钟。
本文件所有 p115client 调用都过 call()，1 秒 1 次，绝不放行裸调用。
"""
import json
import os
import sys
import time
import threading
import unicodedata

# ---------------------------------------------------------------- 全局开关
JSON_OUT = "--json" in sys.argv
DRY_RUN = "--dry-run" in sys.argv
ASSUME_YES = "--yes" in sys.argv

COOKIE_HOME = os.path.expanduser("~/.115")
IOS_CK = "/var/minis/shared/115/cookies.txt"

# 断线重连般的模糊错误，重试一次通常就好
TRANSIENT = ("405", "429", "500", "502", "503", "504", "timeout", "timed out")


def err(msg, code=1):
    """统一的中文错误出口。"""
    sys.stderr.write("✗ %s\n" % msg)
    sys.exit(code)


def out(obj):
    if JSON_OUT:
        print(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(obj, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- 限流
# 115 接口最多每秒 2 次，超了 HTTP 405 并持续封禁数分钟。
# p115client 自身完全不限流，所以必须包在**每个方法调用**外层，
# 不能包在命令入口 —— tree/du/dup 一个命令会发几十上百个请求。
_MIN_INTERVAL = 1.0
_last_at = [0.0]
_lock = threading.Lock()
REQS = [0]  # 本次进程累计请求数，用于给用户报预算


def _throttle():
    with _lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_at[0])
        if wait > 0:
            time.sleep(wait)
        _last_at[0] = time.monotonic()


def call(fn, *args, **kwargs):
    """包住每一次 p115client 调用：限流 + 异常归一化 + 一次退避重试。"""
    for attempt in range(2):
        _throttle()
        REQS[0] += 1
        try:
            return fn(*args, **kwargs)
        except SystemExit:
            raise
        except Exception as e:
            text = str(e)
            if attempt == 0 and any(t in text for t in TRANSIENT):
                time.sleep(3.0)
                continue
            raise RuntimeError(_explain(e)) from None


def _explain(e):
    """把 p115client 抛的 errno/JSON 原文翻成人能看懂的中文下一步。"""
    text = str(e)
    name = type(e).__name__
    if "990001" in text or "请重新登录" in text:
        return ("登录态失效（990001 / errno 99）。cookie 过期了，重新运行 "
                "`p115.py login` 或 `p115.py set-cookie '<...>'`。\n原始信息: " + text)
    if "405" in text:
        return ("HTTP 405 = 触发限流，不是登录问题。停手等 3-5 分钟再跑，"
                "并确认没有别的程序同时在刷 115。\n原始信息: " + text)
    if "990009" in text or "尚未执行完成" in text:
        return ("上一个操作（删除/还原/复制）还没跑完，等几秒再来。\n原始信息: " + text)
    if "231011" in text or "已删除" in text:
        return "目标已经被删了（231011），用 `rb` 看回收站。\n原始信息: " + text
    if "k_ec" in text or "errno', 99" in text:
        return ("App 接口需要 k_ec 参数，本 skill 不走 App 接口。\n原始信息: " + text)
    if "空间不足" in text:
        return "网盘空间不足。用 `space` 看余量。\n原始信息: " + text
    return "%s: %s" % (name, text)


# ---------------------------------------------------------------- cookie
def dedupe(s):
    """去掉重名 cookie。

    browser_cookie3 会把各子域同名 cookie 全导进来，实测 18 个同名 acw_tc
    会让服务端解析异常。保留第一次出现的值。
    """
    seen, order = {}, []
    for kv in s.split(";"):
        kv = kv.strip()
        if "=" not in kv:
            continue
        k, _, v = kv.partition("=")
        k = k.strip()
        if k and k not in seen:
            order.append(k)
            seen[k] = v
    return "; ".join("%s=%s" % (k, seen[k]) for k in order)


def cookie_paths():
    p = []
    if os.environ.get("P115_COOKIE_FILE"):
        p.append(os.environ["P115_COOKIE_FILE"])
    p += [os.path.join(os.getcwd(), "cookies.txt"),
          os.path.join(COOKIE_HOME, "cookies.txt"), IOS_CK]
    return p


def cookie_path():
    for p in cookie_paths():
        if p and os.path.exists(p):
            return p
    return None


def load_cookie():
    env = os.environ.get("P115_COOKIE", "").strip()
    if env:
        return dedupe(env)
    p = cookie_path()
    if not p:
        return None
    raw = open(p, encoding="utf-8").read().strip()
    return dedupe(raw) if raw else None


def save_cookie(s):
    dst = os.environ.get("P115_COOKIE_FILE") or os.path.join(COOKIE_HOME, "cookies.txt")
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(dedupe(s.strip()))
    os.chmod(dst, 0o600)
    if os.path.isdir(os.path.dirname(IOS_CK)):
        try:
            with open(IOS_CK, "w", encoding="utf-8") as f:
                f.write(dedupe(s.strip()))
            os.chmod(IOS_CK, 0o600)
        except OSError:
            pass
    return dst


def cookie_from_browser(name):
    try:
        import browser_cookie3 as bc
    except ImportError:
        err("缺少依赖 browser-cookie3。pip install -r requirements.txt")
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
        except Exception as e:      # 浏览器没装/没登录/keychain 拒绝
            last = "%s: %s" % (b, e)
            continue
        parts = ["%s=%s" % (c.name, c.value) for c in cj if c.name]
        if any(x.startswith("UID=") for x in parts):
            return "; ".join(parts), b
    err("没能从浏览器读到 115 cookie。%s\n确认已在 115.com 登录，或用 set-cookie 手动传。"
        % (last or ""))


def uid_issued_at():
    """UID=<uid>_<tag>_<ts> 里的 ts 是**签发时间**，不是过期时间。

    旧实现把它当过期时间，导致刚登录也显示负数天。
    """
    for kv in (load_cookie() or "").split(";"):
        kv = kv.strip()
        if kv.startswith("UID="):
            for part in kv[4:].split("_"):
                if part.isdigit() and len(part) >= 10:
                    return int(part)
    return None


# ---------------------------------------------------------------- client
_CLIENT = [None]


def client():
    """建 P115Client。cookie 以字符串传入（不用路径），这样重名 cookie
    在进 client 前就已经被去重，client 内部不会再回写污染文件。"""
    if _CLIENT[0] is not None:
        return _CLIENT[0]
    try:
        from p115client import P115Client
    except ImportError:
        err("缺少依赖 p115client。pip install -r requirements.txt")
    ck = load_cookie()
    if not ck:
        err("未配置 cookie。先跑：p115.py login   或   p115.py set-cookie '<k=v; ...>'")
    # console_qrcode=False：绝不能在任何情况下弹二维码等扫码。
    # p115client 没有 check_for_relogin 参数（0.0.9.7.2 已核实），
    # 这个开关的作用就是关掉命令行二维码，405/登录失效直接抛错。
    _CLIENT[0] = P115Client(ck, console_qrcode=False)
    return _CLIENT[0]


def new_client():
    """换账号后重建。"""
    _CLIENT[0] = None
    return client()


# ---------------------------------------------------------------- 显示
def width(s):
    """中英混排真实显示宽度：CJK/全角 2，emoji 2。"""
    w = 0
    for ch in str(s):
        if unicodedata.east_asian_width(ch) in ("W", "F") or ord(ch) >= 0x1F300:
            w += 2
        else:
            w += 1
    return w


def pad(s, n):
    s = str(s)
    return s + " " * max(0, n - width(s))


def hum(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return str(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return "%.1f%s" % (n, u)
        n /= 1024
    return "%.1fPB" % n


def is_dir(it):
    """115 的目录有 cid 无 fid，文件有 fid。不能只看 cid 字段是否存在。"""
    return bool(it.get("cid")) and not it.get("fid")


def item_id(it):
    return it.get("cid") if is_dir(it) else it.get("fid")


# ---------------------------------------------------------------- 路径寻址
def ls_page(cid, offset=0, limit=115, order="user_utime"):
    """列一页。带 cid 回显校验：115 对不存在的 cid 会**静默返回根目录**，
    不校验的话打错一位就看到根目录还以为成功了。"""
    r = call(client().fs_files, {"cid": str(cid), "offset": offset,
                                 "limit": limit, "o": order, "asc": 1,
                                 "show_dir": 1, "natsort": 1})
    echoed = str(r.get("cid", ""))
    if str(cid) != "0" and echoed and echoed != str(cid):
        err("目录不存在：cid=%s（115 回显 cid=%s，通常是把 id 打错了）"
            % (cid, echoed))
    return r


def iter_all(cid, order="user_utime"):
    """完整翻页。旧实现只取首页 115 条会静默截断，这里翻到底。"""
    off = 0
    while True:
        page = ls_page(cid, off, 115, order).get("data") or []
        for it in page:
            yield it
        if len(page) < 115:
            return
        off += 115


def resolve_dir(target):
    """把 id 或路径解析成目录 cid。

    "0" / 123 / "/电影区" / "电影区/蜘蛛侠" 都行。
    先试服务端 getid（1 个请求），失败再本地逐级 ls（路径不存在时更可读）。
    """
    if target is None:
        return "0"
    t = str(target).strip()
    if t.isdigit():
        return t
    path = t if t.startswith("/") else "/" + t
    if path == "/":
        return "0"
    try:
        r = call(client().fs_dir_getid, {"path": path})
        if r.get("state") and r.get("id"):
            return str(r["id"])
    except RuntimeError:
        pass  # 服务端不认这个路径，走本地逐级解析给出更准确的中文报错

    cur, walked = "0", []
    for seg in [p for p in path.split("/") if p]:
        found = None
        for it in iter_all(cur):
            if is_dir(it) and it.get("n") == seg:
                found = str(it["cid"])
                break
        if not found:
            err("路径不存在：%s（在 /%s 下找不到「%s」）"
                % (path, "/".join(walked), seg))
        cur = str(found)
        walked.append(seg)
    return cur


def resolve_item(target):
    """解析成单个条目，返回 (id, 是否目录, 条目原始 dict)。"""
    t = str(target).strip()
    if t.isdigit():
        r = call(client().fs_file, t)
        data = r.get("data")
        if isinstance(data, list) and data:
            data = data[0]
        if not data:
            err("找不到 id=%s（%s）" % (t, r.get("error") or "接口无返回"))
        return t, is_dir(data), data
    path = t if t.startswith("/") else "/" + t
    parts = [p for p in path.split("/") if p]
    if not parts:
        err("根目录不是文件")
    name = parts[-1]
    parent = resolve_dir("/" + "/".join(parts[:-1])) if len(parts) > 1 else "0"
    for it in iter_all(parent):
        if it.get("n") == name:
            return str(item_id(it)), is_dir(it), it
    err("找不到：%s" % path)


def need_dir(target="0"):
    cid = resolve_dir(target)
    return cid


# ---------------------------------------------------------------- 打印
def print_items(r, hint_cid=None):
    if JSON_OUT:
        out(r)
        return
    data = r.get("data")
    if not isinstance(data, list):
        out(r)
        return
    total = r.get("count")
    print("count=%s  本页 %d 条" % (total if total is not None else "?", len(data)))
    if not data:
        return
    w = min(48, max(width(it.get("n", "")) for it in data))
    for it in data:
        d = is_dir(it)
        print("  %s %s %10s  id=%s"
              % ("[DIR] " if d else "[FILE]", pad(it.get("n", ""), w),
                 "" if d else hum(it.get("s", 0)), item_id(it)))
    try:
        total, cur = int(total), int(r.get("offset") or 0) + len(data)
    except (TypeError, ValueError):
        return
    if total > cur and hint_cid is not None:
        print("... 还有 %d 条：p115.py ls %s %d" % (total - cur, hint_cid, cur))


def confirm(prompt):
    """危险写操作的二次确认。--yes 直接放行，非 tty 一律拒绝。"""
    if ASSUME_YES:
        return
    if not sys.stdin.isatty():
        err("这是危险操作，非交互环境请显式加 --yes")
    sys.stderr.write("⚠ %s  [y/N] " % prompt)
    sys.stderr.flush()
    if sys.stdin.readline().strip().lower() not in ("y", "yes"):
        err("已取消")


# ================================================================ 命令
def cmd_login(a):
    browser = a[0] if a else "auto"
    ck, src = cookie_from_browser(browser)
    print("从 %s 导入 → %s" % (src, save_cookie(ck)))
    c = new_client()
    r = call(c.user_my)
    if not r.get("state"):
        err("cookie 已保存但校验失败：%s" % (r.get("error") or r))
    d = r.get("data") or {}
    print("登录成功：%s（VIP=%s）" % (d.get("user_name", "?"), d.get("vip", "?")))


def cmd_setcookie(a):
    if not a:
        err("用法：set-cookie '<k=v; k=v>'")
    dst = save_cookie(a[0])
    print("已保存 → %s（已去重重名 cookie）" % dst)


def cmd_whoami(a):
    c = client()
    r = call(c.user_my)
    if JSON_OUT:
        out(r)
        return
    if not r.get("state"):
        err("校验失败：%s" % (r.get("error") or r))
    d = r.get("data") or {}
    print("用户名: %s" % d.get("user_name", "?"))
    print("UID:    %s" % d.get("user_id", "?"))
    print("VIP:    %s" % (d.get("vip") or d.get("forever_name") or "否"))
    ts = uid_issued_at()
    if ts:
        print("cookie 签发于: %s（%d 小时前）"
              % (time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)),
                 (int(time.time()) - ts) // 3600))
        print("  注：这是签发时间，115 不公开真实过期时刻。")
    src = "env P115_COOKIE" if os.environ.get("P115_COOKIE") else cookie_path()
    print("cookie 来源: %s" % src)


def cmd_ls(a):
    target = a[0] if a else "0"
    off = int(a[1]) if len(a) > 1 else 0
    lim = int(a[2]) if len(a) > 2 else 115
    cid = resolve_dir(target)
    r = ls_page(cid, off, lim)
    print_items(r, cid)


def cmd_tree(a):
    target = a[0] if a else "0"
    depth = int(a[1]) if len(a) > 1 else 2
    root = resolve_dir(target)

    if JSON_OUT:
        def build(c, d):
            out_items = []
            for it in iter_all(c):
                node = {"name": it.get("n"), "id": item_id(it),
                        "dir": is_dir(it), "size": it.get("s")}
                if is_dir(it) and d > 1:
                    node["children"] = build(it["cid"], d - 1)
                out_items.append(node)
            return out_items
        out({"cid": root, "children": build(root, depth)})
        return

    stat = {"dir": 0, "file": 0}

    def walk(c, d, prefix):
        items = list(iter_all(c))
        for i, it in enumerate(items):
            d_ = is_dir(it)
            stat["dir" if d_ else "file"] += 1
            last = i == len(items) - 1
            print("%s%s%s %s" % (prefix, "└── " if last else "├── ",
                                 "[D]" if d_ else "[F]", it.get("n", "")))
            if d_ and d > 1:
                walk(it["cid"], d - 1, prefix + ("    " if last else "│   "))

    walk(root, depth, "")
    print("\n共 %d 目录 / %d 文件（完整翻页，请求 %d 次）"
          % (stat["dir"], stat["file"], REQS[0]))


def cmd_info(a):
    if not a:
        err("用法：info <id|path>")
    _iid, _d, item = resolve_item(a[0])
    out(item)


def cmd_path(a):
    if not a:
        err("用法：path <id>")
    fid = a[0]
    r = call(client().fs_file, fid)
    data = r.get("data")
    if isinstance(data, list) and data:
        data = data[0]
    if not data:
        err("找不到 id=%s" % fid)
    # 用父目录的 list 响应里的 path 字段拼完整路径（get_info 不带这条链）
    parent = ls_page(data.get("pid") or "0", 0, 1)
    names = [p.get("name") for p in (parent.get("path") or []) if p.get("name")]
    if names and names[0] == "根目录":
        names = names[1:]
    full = "/" + "/".join(names + [data.get("n", "")])
    if JSON_OUT:
        out({"id": fid, "name": data.get("n"), "path": full})
    else:
        print(full)


def cmd_search(a):
    if not a:
        err("用法：search <关键字>")
    r = call(client().fs_search, {"search_value": a[0], "limit": 30})
    if not r.get("state"):
        err("搜索失败：%s" % (r.get("error") or r))
    print_items(r)


def cmd_find(a):
    if not a:
        err("用法：find <关键字> [cid|path]")
    kw = a[0].lower()
    root = resolve_dir(a[1] if len(a) > 1 else "0")
    hits = []

    def walk(c, prefix, depth):
        if depth > 6:            # 深度护栏，避免畸形目录树把请求打爆
            return
        for it in iter_all(c):
            name = it.get("n", "")
            here = prefix + "/" + name
            if kw in name.lower():
                hits.append((here, item_id(it), is_dir(it), it.get("s")))
            if is_dir(it):
                walk(it["cid"], here, depth + 1)

    walk(root, "", 0)
    if JSON_OUT:
        out({"keyword": a[0], "hits": [
            {"path": h[0], "id": h[1], "dir": h[2], "size": h[3]} for h in hits]})
        return
    print("找到 %d 项（请求 %d 次）：" % (len(hits), REQS[0]))
    for p, iid, d, size in hits:
        print("  %s %s %10s  id=%s"
              % ("[DIR] " if d else "[FILE]", pad(p, 60),
                 "" if d else hum(size), iid))


def cmd_du(a):
    target = a[0] if a else "0"
    root = resolve_dir(target)
    stat = {"bytes": 0, "files": 0, "dirs": 0}

    def size_of(c, depth=0):
        total = files = 0
        for it in iter_all(c):
            if is_dir(it):
                stat["dirs"] += 1
                if depth < 8:      # 深度护栏
                    s, k = size_of(it["cid"], depth + 1)
                    total += s
                    files += k
            else:
                total += int(it.get("s") or 0)
                files += 1
        return total, files

    total, files = size_of(root)
    stat.update(bytes=total, files=files)
    if JSON_OUT:
        out({"cid": root, **stat})
    else:
        print("占用：%s（%d 文件 / %d 目录，请求 %d 次）"
              % (hum(total), files, stat["dirs"], REQS[0]))


def cmd_mkdir(a):
    if len(a) < 2:
        err("用法：mkdir <父cid|父path> <名称>")
    pid = resolve_dir(a[0])
    if DRY_RUN:
        print("[dry-run] 在 cid=%s 下创建目录「%s」" % (pid, a[1]))
        return
    r = call(client().fs_mkdir, a[1], pid)
    if not r.get("state"):
        err("创建失败：%s" % (r.get("error") or r))
    print("已创建「%s」 id=%s" % (a[1], r.get("cid") or r.get("file_id")))


def cmd_rename(a):
    if len(a) < 2:
        err("用法：rename <id|path> <新名>")
    iid, _d, item = resolve_item(a[0])
    old = item.get("n", "")
    if DRY_RUN:
        print("[dry-run] 重命名「%s」→「%s」" % (old, a[1]))
        return
    r = call(client().fs_rename, (iid, a[1]))
    if not r.get("state"):
        err("重命名失败：%s" % (r.get("error") or r))
    print("已重命名：「%s」→「%s」" % (old, a[1]))


def _batch(label, ids, fn, dest=None):
    """mv/cp/rm/restore 共用的批量执行。"""
    if not ids:
        err("没有要给的目标")
    resolved = []
    for t in ids:
        resolved.append(str(t) if str(t).isdigit() else resolve_item(t)[0])
    if DRY_RUN:
        print("[dry-run] %s %d 项%s（ids=%s）"
              % (label, len(resolved),
                 " → cid=%s" % dest if dest else "", ",".join(resolved)))
        return
    r = call(fn, resolved) if dest is None else call(fn, resolved, dest)
    if not r.get("state"):
        err("%s失败：%s" % (label, r.get("error") or r))
    print("%s完成，共 %d 项" % (label, len(resolved)))


def cmd_mv(a):
    if len(a) < 2:
        err("用法：mv <目标cid|目标path> <id|path...>")
    _batch("移动", a[1:], client().fs_move, resolve_dir(a[0]))


def cmd_cp(a):
    if len(a) < 2:
        err("用法：cp <目标cid|目标path> <id|path...>")
    _batch("复制", a[1:], client().fs_copy, resolve_dir(a[0]))


def cmd_rm(a):
    if not a:
        err("用法：rm <id|path...>   （进回收站，可 restore 回来）")
    _batch("删除到回收站", a, client().fs_delete)


def cmd_rb(a):
    off = int(a[0]) if a else 0
    r = call(client().recyclebin_list, {"offset": off, "limit": 115})
    if JSON_OUT:
        out(r)
        return
    data = r.get("data") or []
    print("回收站 %s 项" % r.get("count", "?"))
    for it in data:
        d = str(it.get("type")) == "2"
        print("  %s %s %10s  rid=%s  from=%s"
              % ("[DIR] " if d else "[FILE]", pad(it.get("file_name", ""), 40),
                 "" if d else hum(it.get("file_size", 0)),
                 it.get("id"), it.get("parent_name", "")))
    if data:
        print("\n还原：p115.py restore <rid...>")


def cmd_restore(a):
    if not a:
        err("用法：restore <rid...>")
    r = call(client().recyclebin_revert, a)
    if not r.get("state"):
        err("还原失败：%s" % (r.get("error") or r))
    print("已还原 %d 项" % len(a))


def cmd_url(a):
    if not a:
        err("用法：url <id|path>")
    iid, d, item = resolve_item(a[0])
    if d:
        err("「%s」是目录，取不了直链。先用 tree 进去，再对单个文件取。"
            % item.get("n"))
    pc = item.get("pc")
    if not pc:
        err("这个条目没有 pickcode，取不了直链。")
    # App 接口（download_url / download_url_app）实测 errno 99，
    # web 版 download_url_web2 稳定可用，且会一并返回下载所需的 cookie 头。
    r = call(client().download_url_web2, pc)
    if not r.get("state"):
        err("取直链失败：%s" % (r.get("error") or r))
    url = r.get("url") or ""
    if JSON_OUT:
        out({"id": iid, "name": item.get("n"), "pickcode": pc,
             "url": url, "headers": r.get("headers") or {}})
        return
    print("文件名: %s" % item.get("n"))
    print("大小:   %s" % hum(item.get("s")))
    print("直链:")
    print("  %s" % url)
    ck = (r.get("headers") or {}).get("cookie")
    if ck:
        print("\n下载需要带这个 cookie 头（15 分钟过期）:")
        print("  %s" % ck)


def cmd_dl(a):
    if not a:
        err("用法：dl <id|path> [输出目录]")
    outdir = a[1] if len(a) > 1 else "."
    iid, d, item = resolve_item(a[0])
    if d:
        err("目录下载不在本工具范围，用网页端或 url 逐个取。")
    pc = item.get("pc")
    if not pc:
        err("没有 pickcode，无法下载。")
    r = call(client().download_url_web2, pc)
    if not r.get("state"):
        err("取直链失败：%s" % (r.get("error") or r))
    url = r["url"]
    headers = r.get("headers") or {}
    name = item.get("n") or "download.bin"
    dst = os.path.join(outdir, name)
    os.makedirs(outdir, exist_ok=True)
    if DRY_RUN:
        print("[dry-run] 下载 → %s" % dst)
        return

    # 下载走 CDN，不是 115 接口，不受 1 秒限流；但必须带签名直链和配套 cookie 头。
    import urllib.request
    req = urllib.request.Request(url, headers={k: v for k, v in headers.items() if v})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(dst, "wb") as f:
            got = 0
            while True:
                buf = resp.read(262144)
                if not buf:
                    break
                f.write(buf)
                got += len(buf)
    except Exception as e:
        err("CDN 拒绝下载（%s）。115 防盗链导致脚本直连常驻 403。\n"
            "把下面直链复制到浏览器 / 迅雷 / IDM（约 15 分钟内有效）：\n%s" % (e, url))
    print("已下载 → %s（%s）" % (dst, hum(got)))


def cmd_up(a):
    if not a:
        err("用法：up <本地文件> [目标目录=0]")
    src = os.path.expanduser(a[0])
    if not os.path.isfile(src):
        err("本地文件不存在：%s" % src)
    pid = resolve_dir(a[1] if len(a) > 1 else "0")
    size = os.path.getsize(src)
    if DRY_RUN:
        print("[dry-run] 上传 %s（%s）→ cid=%s" % (src, hum(size), pid))
        return
    # upload_file 内部会自己算 sha1 走秒传/分块；它向 OSS 发的分片请求
    # 不经过 webapi 限流，但初始化那一步仍然过 call()。
    r = call(client().upload_file, src, pid=pid)
    if not r.get("state"):
        err("上传失败：%s" % (r.get("error") or r))
    d = r.get("data") or {}
    if JSON_OUT:
        out(d)
        return
    print("已上传「%s」id=%s  大小=%s"
          % (d.get("file_name", os.path.basename(src)),
             d.get("file_id", "?"), hum(d.get("file_size", size))))


def cmd_offline(a):
    # --to 的值是目录，不能进 urls；先分流再判断
    to = "0"
    urls, i = [], 0
    while i < len(a):
        if a[i] == "--to":
            if i + 1 >= len(a):
                err("--to 后面要跟目录 cid 或路径")
            to = a[i + 1]
            i += 2
            continue
        urls.append(a[i])
        i += 1
    if not urls:
        err("用法：offline <磁力/ed2k/http链接...> [--to 目录cid|path]")
    pid = resolve_dir(to)
    if DRY_RUN:
        print("[dry-run] 离线下载 %d 个链接 → cid=%s：%s"
              % (len(urls), pid, " | ".join(urls)))
        return
    payload = {f"url[{n}]": u for n, u in enumerate(urls)}
    payload["wp_path_id"] = pid
    r = call(client().clouddownload_task_add_urls, payload)
    if not r.get("state"):
        detail = r.get("error_msg") or r.get("error") or r
        err("离线任务创建失败：%s\n（磁力链要带完整磁力头；115 对无效链接直接拒绝）" % detail)
    if JSON_OUT:
        out(r)
        return
    print("已提交 %d 个离线任务" % len(urls))
    print("用 `p115.py offline-list` 看进度")


def cmd_offline_list(a):
    r = call(client().clouddownload_task_list, {"page": int(a[0]) if a else 1})
    if JSON_OUT:
        out(r)
        return
    tasks = r.get("tasks") or []
    print("离线任务 %s 个（配额 %s/%s）"
          % (r.get("count", "?"), r.get("quota", "?"), r.get("total", "?")))
    for t in tasks:
        print("  %-8s %5s%%  %s"
              % (t.get("display_status") or t.get("status_text") or "?",
                 t.get("display_percent", 0), t.get("name", "")[:60]))


def cmd_space(a):
    # fs_storage_info = 网页端「空间」卡片，1 个请求、只读，比 tool_space 温和。
    # tool_space 是「校验空间」扫描任务，一天只能用一次，不用它查余量。
    r = call(client().fs_storage_info)
    if JSON_OUT:
        out(r)
        return
    d = r.get("1") or r.get("data") or r
    total, used = d.get("total"), d.get("used")
    if total is None:
        out(r)
        return
    pct = (used / total * 100) if total else 0
    print("总空间: %s" % hum(total))
    print("已用:   %s（%.1f%%）" % (hum(used), pct))
    print("剩余:   %s" % hum(total - used))


def cmd_dup(a):
    # 排重必须先跑一遍扫描（tool_repeat），再取列表（tool_repeat_list）。
    # 扫描是服务端任务，耗时不定，所以拆成 dup 和 dup-list 两步。
    if a and a[0] == "list":
        off = int(a[1]) if len(a) > 1 else 0
        r = call(client().tool_repeat_list, {"s": off, "l": 100})
        if JSON_OUT:
            out(r)
            return
        data = r.get("data") or []
        print("重复组 %s 条（本页 %d）" % (r.get("count", "?"), len(data)))
        for it in data:
            print("  %s  %s  size=%s"
                  % (it.get("sha1", "")[:12], pad(it.get("file_name", ""), 40),
                     hum(it.get("file_size", 0))))
        return
    if DRY_RUN:
        print("[dry-run] 触发全盘排重扫描（服务端任务，可能耗时数分钟）")
        return
    fid = resolve_dir(a[0]) if a else "0"
    r = call(client().tool_repeat, {"folder_id": fid})
    if not r.get("state"):
        err("排重启动失败：%s" % (r.get("error") or r))
    print("排重扫描已启动（folder_id=%s）" % fid)
    print("稍后用 `p115.py dup list` 取结果")


def cmd_sign(a):
    # 注意：签到接口要用 App 端 cookie，web cookie 会返回 errno 99。
    # 这里如实报错，不假装成功。
    r = call(client().user_points_sign_post)
    if not r.get("state"):
        err("签到失败：%s\n（签到接口要求 App 端登录态，网页 cookie 会返回 errno 99）"
            % (r.get("error") or r))
    if JSON_OUT:
        out(r)
        return
    print("签到成功")
    d = r.get("data") or {}
    if d.get("points"):
        print("本次获得: %s 积分" % d.get("points"))


def cmd_share(a):
    if not a:
        err("用法：share <id|path...>")
    ids = [str(t) if str(t).isdigit() else resolve_item(t)[0] for t in a]
    if DRY_RUN:
        print("[dry-run] 分享 %d 项：%s" % (len(ids), ",".join(ids)))
        return
    r = call(client().share_send, {"file_ids": ",".join(ids)})
    if not r.get("state"):
        err("创建分享失败：%s" % (r.get("error") or r))
    d = r.get("data") or {}
    if JSON_OUT:
        out({"share_url": d.get("share_url"), "receive_code": d.get("receive_code"),
             "count": d.get("file_count")})
        return
    print("分享链接: %s" % d.get("share_url"))
    if d.get("receive_code"):
        print("提取码:   %s" % d.get("receive_code"))
    print("\n提醒：撤销分享要回网页端「我的分享」，接口侧不可靠。")


CMDS = {
    "login": cmd_login, "set-cookie": cmd_setcookie, "whoami": cmd_whoami,
    "ls": cmd_ls, "tree": cmd_tree, "info": cmd_info, "path": cmd_path,
    "search": cmd_search, "find": cmd_find, "du": cmd_du,
    "mkdir": cmd_mkdir, "rename": cmd_rename, "mv": cmd_mv, "cp": cmd_cp,
    "rm": cmd_rm, "rb": cmd_rb, "restore": cmd_restore,
    "url": cmd_url, "dl": cmd_dl, "up": cmd_up,
    "offline": cmd_offline, "offline-list": cmd_offline_list,
    "space": cmd_space, "dup": cmd_dup, "sign": cmd_sign, "share": cmd_share,
}


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        print("\n可用命令: %s" % " ".join(sorted(CMDS)))
        return
    # 只剔除全局开关，命令自己的选项（如 --to）必须留给命令解析
    cmd, rest = args[0], [x for x in args[1:]
                          if x not in ("--json", "--dry-run", "--yes", "--no-color")]
    if cmd not in CMDS:
        err("未知命令：%s\n可用：%s" % (cmd, " ".join(sorted(CMDS))))
    try:
        CMDS[cmd](rest)
    except RuntimeError as e:
        err(str(e))
    except KeyboardInterrupt:
        err("已中断", 130)


if __name__ == "__main__":
    main()
