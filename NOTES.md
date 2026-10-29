# 维护笔记

给改这个仓库的人看。`SKILL.md` 是给 agent 用的操作手册，这里是为什么这么写。

## 为什么换 p115client

旧版是 810 行手搓 `urllib`，每个接口自己拼参数、自己解 JSON。问题：

- 115 的接口签名/加密经常变，手搓跟不上
- 405 限流、cookie 去重、路径解析这些坑每加一个命令就要重踩一次
- 下载直链要签名，手搓必然失败

`p115client` 已经把这些做完了，还带了 `p115cipher`（加解密）、`p115oss`（上传）、`p115pickcode`（id 转换）。本仓库只做薄外壳。

**红线：不 vendor 上游源码。** 一个字节都不复制，只 `requirements.txt` 声明依赖。这样换台机器 `pip install -r requirements.txt` 就能跑，上游更新也不用管。

## p115client 版本与参数核实

装的是 **0.0.9.7.2**。源码读过一遍，确认几件事：

- **没有 `check_for_relogin` 参数。** 任务描述里提到的这个参数在 0.0.9.7.2 不存在。真正控制「不要弹二维码」的是 `P115Client(cookies, console_qrcode=False)`。本代码已显式传 `False`，任何情况下都不会进二维码流程。
- `P115Client(cookies)` 接受字符串、路径、Mapping。**本代码传字符串**，因为重名 cookie 必须在进 client 前就清掉，传路径的话 client 内部会回写文件，去重白做。
- `download_url` / `download_url_app` 在本账号上**实测返回 `errno 99` 「请重新登录」**。可用的是 `download_url_web2(pickcode)`，返回 `{"url": ..., "headers": {"cookie": ...}}`。代码用后者。
- `upload_file(file, pid=...)` 实测可用，返回 `pick_code` / `file_id` / `sha1`。
- `clouddownload_task_add_urls` 是离线下载的可用入口（`proapi.115.com/open/offline/add_task_urls`）。`extract_add_file` 是**解压**接口，不是离线，别搞混。
- `fs_storage_info()`（1 请求，只读）是查空间余量的正确方法。`tool_space()` 是「校验空间」扫描任务，**一天只能用一次**，拿它查余量是错的。

## 方法映射（CLI → p115client）

均为 0.0.9.7.2 源码核对结果。

| CLI | 方法 | 关键参数 |
|---|---|---|
| `whoami` / `login` | `user_my` | 无 |
| `ls` / `tree` / `find` / 路径解析 | `fs_files` | `{"cid":..., "offset":..., "limit":..., "show_dir":1}` |
| `info` | `fs_file` | `file_id`（位置参数） |
| `path` | `fs_file` + `fs_files` 父目录 | 用父目录响应的 `path` 字段拼全路径 |
| `search` | `fs_search` | `{"search_value":..., "limit":30}` |
| `space` | `fs_storage_info` | 无 |
| `mkdir` | `fs_mkdir` | `fs_mkdir(name, pid)` |
| `rename` | `fs_rename` | **元组** `(fid, new_name)` |
| `mv` | `fs_move` | `fs_move([id...], pid)` |
| `cp` | `fs_copy` | `fs_copy([id...], pid)` |
| `rm` | `fs_delete` | `fs_delete([id...])` |
| `rb` | `recyclebin_list` | `{"offset":..., "limit":...}` |
| `restore` | `recyclebin_revert` | `recyclebin_revert([rid...])` |
| `url` / `dl` | `download_url_web2` | `pickcode` |
| `up` | `upload_file` | `upload_file(path, pid=...)` |
| `offline` | `clouddownload_task_add_urls` | `{"url[0]":..., "wp_path_id":...}` |
| `offline-list` | `clouddownload_task_list` | `{"page":1}` |
| `dup` | `tool_repeat` | `{"folder_id": cid}` |
| `dup list` | `tool_repeat_list` | `{"s": offset, "l": 100}` |
| `sign` | `user_points_sign_post` | 要求 App 端 cookie |
| `share` | `share_send` | `{"file_ids": "id,id"}` |
| 路径→cid | `fs_dir_getid` | `{"path": "/a/b"}`，失败时回退本地逐级 `ls` |

`fs_dir_getid2`（`/files/get_path_id`）实测对本账号返回空 `file_id`，**不可用**，代码用 `fs_dir_getid`。

## 限流（最重要的一条）

115 后端最多每秒 2 次请求。超了返回 **HTTP 405**（HTML 错误页），并封禁数分钟。

`p115client` **完全不限流**，一个 `tree` 能瞬间打出几十个请求。

所以 `call()` 必须包在**每个 p115client 方法调用**外层，不能包在 CLI 命令入口。当前实现：

```python
def call(fn, *args, **kwargs):
    for attempt in range(2):
        _throttle()          # 睡到距上次 ≥ 1.0s
        REQS[0] += 1
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if attempt == 0 and any(t in str(e) for t in TRANSIENT):
                time.sleep(3.0)
                continue
            raise RuntimeError(_explain(e)) from None
```

`TRANSIENT` 只包含 405/429/5xx/timeout。**只重试一次**，因为 405 重试会延长封禁。

`REQS[0]` 是请求计数，`tree`/`du`/`find` 结束时会打出来，方便估算预算。

**不要改成并发。** 线程池 + 两个 worker 就直接撞 405。

## Cookie

优先级：`P115_COOKIE` env → `P115_COOKIE_FILE` env → `./cookies.txt` → `~/.115/cookies.txt` → `/var/minis/shared/115/cookies.txt`。

**重名 cookie 去重是必须的**。`browser_cookie3` 会把 115.com 各子域的同名 cookie 全导进来，实测一次出现 **18 个同名 `acw_tc`**，服务端解析异常（不是报错，是行为诡异）。`dedupe()` 保留第一次出现，其余丢弃。

**`UID=<uid>_<tag>_<ts>` 的 `<ts>` 是签发时间，不是过期时间。** 旧实现当过期时间用，导致刚登录显示「-1 天」。现在只显示签发时刻，并明确写「115 不公开真实过期时刻」。

## 假 cid 静默返回根目录（最阴的坑）

请求一个**不存在**的 cid，`webapi.115.com/files` 不报错，直接返回**根目录**的内容。

后果：cid 打错一位 → 看到根目录列表 → 以为成功了 → 接着操作 → 删错东西。

本工具必须做的校验（`ls_page()`）：

```python
echoed = str(r.get("cid", ""))
if str(cid) != "0" and echoed and echoed != str(cid):
    err("目录不存在：cid=%s（115 回显 cid=%s）")
```

**这个校验是真的救过命。** 开发中我用一个已删除的目录 cid 列目录，115 返回了根目录，脚本把根目录 12 项当成「残留」全删了（后来从回收站全部还原）。没有回显校验，这类事故无法避免。

## 翻页截断

`webapi.115.com/files` 默认 / 上限单页 115 条。旧实现只取首页就返回，大目录静默截断。

现在 `iter_all()` 一路翻到不满一页为止。代价是请求数 = 目录条数 / 115，`tree` 的请求数就是这么来的。

## k_ec 与 App 接口

手机 App 走 `proapi.115.com/115ios/2.0/ufile/files`，带 `k_ec` 参数。

`k_ec` base64 解码后是 48 字节、含 PKCS#7 填充（`06 06 06 06`、`4d 4d 4d`），是**加密载荷不是签名**。上游已拆成独立包 `p115cipher` 解决。

**不要反推实现 k_ec。** 上游做完了，重复劳动无意义。本 skill 只用 web 端接口。

已实测：`fs_files_app(app="115ios")` **静默返回空数据**（`count=None`），不能用。别尝试绕。

## 405 的真实成因

实测结论：

- **和 IP 无关**（换 IP 无效）
- **和 UA 无关**（同 IP 换 UA 无效）
- 是**接口级限流叠加登录态**问题

所以唯一对策就是降频 + 保活 cookie。

## 直链 403（防盗链）

`url` 能拿到直链（`download_url_web2` 的 `location`）。但脚本 GET 这个直链会 **403**。

实测过的组合，全部 403：

- UA：Chrome / 115Browser 27.0 / 115Browser 35.6 / okhttp 3.14.9
- cookie：带 session cookie / 只带响应里的临时 cookie / 不带
- Range 头：带 / 不带

结论：115 CDN 有更底层的防盗链（可能校验 referer 链或 TLS 指纹）。**这不是本代码能修的**，所以 `dl` 保留但明确报错并打印直链，让用户复制到浏览器。要真下载，用 `url` + 浏览器/迅雷。

## 上传

`upload_file` 实测通过（53 字节文本文件，`state: true`，返回 `pick_code`/`sha1`）。

内部流程：算 sha1 → `upload_init` 判秒传 → 未命中则向阿里云 OSS 分片上传 → 回调 `upload_file` 确认。**只有 web 接口那几步过 `call()` 限流**，OSS 分片不等 1 秒（不归 115 的 webapi 管）。

## 签到

`user_points_sign` / `user_points_sign_post` 都要求 **App 端登录态**。用网页 cookie 调用返回 `errno 99`。

代码保留 `sign` 但如实报错，不假装成功。要签到请用 App 或 App cookie。

## 回收站

- `rm` 只进回收站，115 没有「按文件 id 彻底删除」的公开接口 → **本工具不提供 `purge`**。
- `recyclebin_clean2`（彻底删）需要**安全密钥**，默认 `000000` 会报「安全密钥错误，你还可以输入 2 次」。本工具不猜用户密码，不做这个命令。
- 开发中产生的 3 个 `__selftest__` 临时对象因此留在回收站里，需要用户在网页端手动清空。

## 旧实现踩过的坑（已全部修掉，留档）

1. 假 cid 静默返回根目录 → 见上
2. `tree` 只取首页 115 条会截断 → `iter_all()`
3. `UID` 末段当过期时间 → 改为签发时间
4. 18 个同名 `acw_tc` 未去重 → `dedupe()`
5. 手搓 `download` 拿直链必然 403 → 现用 `download_url_web2`
6. `fs_files_app` 静默空返回 → 不碰 App 接口

## 文件结构

```
115-Pan-Skill/
├── SKILL.md          agent 操作手册（限流、命令、路径、错误码）
├── NOTES.md          本文件，维护者笔记
├── requirements.txt  只有 p115client + browser-cookie3
├── .gitignore        __pycache__ / *.pyc / cookies.txt / .venv
└── scripts/p115.py   全部 CLI 实现
```

---

## 自包含安装：一切跟 skill 目录走（2026-10-29 定稿）

### 决策变化

先做过一版「固定 `~/.115/`」，被否掉了。理由：skill 可能装到任意位置
（`~/.agents/skills/`、项目目录、别人机器上的任意路径），依赖若散落在家目录，
调用方无法从 skill 目录自证「我装好了」。

**最终方案：一切运行时产物放在 skill 自己的根目录下。**

```
<SKILL_DIR>/.venv/              依赖（p115client 等）
<SKILL_DIR>/cookies.txt         凭证
<SKILL_DIR>/.setup-state.json   安装元数据
```

`SKILL_DIR = dirname(dirname(abspath(__file__)))` —— 从脚本位置反推，不写死。

好处：
- skill 装到哪，依赖跟到哪，整份目录自包含
- 调用方进 skill 目录就能找到一切，不用全局搜索
- 多份 skill 副本互不干扰

### venv 不可跨机器 / 跨路径拷贝

venv 的 `pyvenv.cfg` 和脚本 shebang 写死绝对路径。目录被搬走后 venv 会失效。

**检测**：`venv_is_stale()` 读 `pyvenv.cfg` 的 `command` 行，取最后一段
（当初创建时的目标路径），与当前 `VENV_HOME` 比较，不一致就是漂移。

**修复**：`setup` 检测到漂移会先 `rmtree` 再重建。实测搬目录后：
```
→ 检测到 venv 是从别的路径搬过来的，重建中…
→ 创建虚拟环境…
→ 安装依赖…
✓ 完成。p115client 0.0.9.7.2
```
重建后功能正常。

### 自动切换 `_reexec_into_fixed_venv()`

启动时检查：当前 python 有没有 p115client？没有但 `<skill>/.venv` 存在
→ `os.execv` 切过去重跑。用 `P115_REEXEC=1` 防递归。

三种写法结果一致：
```bash
python3 scripts/p115.py ls 0                 # 系统 python，自动切
/usr/bin/python3 scripts/p115.py ls 0        # 另一个 python，自动切
.venv/bin/python scripts/p115.py ls 0        # 直接 venv，不切
```

### 踩过的 bug：`in_fixed_venv()` 判断错误

第一版用 `realpath(sys.executable) == realpath(venv_python())`。**错的** ——
venv 里的 `python` 本身就是指向系统 python 的 symlink，realpath 后两边一样。
Homebrew python 被误判「已在 venv」，于是不切换、继续报缺库。

正确做法：比较 `sys.prefix`，venv 里它就是 venv 根目录。

```python
def in_fixed_venv():
    return os.path.realpath(sys.prefix) == os.path.realpath(VENV_HOME)
```

### `.gitignore` 必须排除

```
.venv/            # 80MB，每台机器自己建
cookies.txt       # 凭证，绝不能提交
.setup-state.json # 安装元数据，含本机绝对路径
```

纯文件体积 148KB，`.venv` 79MB。

### `setup` / `doctor`

- `setup`：建 venv + 装依赖 + 写 state，幂等，自动处理路径漂移
- `doctor`：报全 skill 目录、venv 状态（含 stale 警告）、p115client 版本与位置、
  cookie、账号。**新对话接手第一条命令。**

### 版本号显示坑

`p115client` 包里的 `__version__` 是手写过期值（0.0.9.7.2 的包写着 `(0, 0, 9)`）。
查真实版本必须用 `importlib.metadata.version("p115client")`。

---

## 写命令实测记录（2026-10-29）

在 `其他` 目录下建临时目录跑完整闭环，跑完已清理：

| 命令 | 调用 | 结果 |
|---|---|---|
| `mkdir /其他 __probe_xxx` | `fs_mkdir(name, pid)` | ✅ 返回新 cid |
| `rename <id> __probe_renamed` | `fs_rename((cid, name))` | ✅ 生效 |
| `cp /图片 <id>` | `fs_copy(payload, pid)` | ✅ 副本落在图片，同名自动 `(1)` |
| `mv /其他 <副本id>` | `fs_move(payload, pid)` | ✅ 跨目录成功 |
| `rm <id1> <id2>` | `fs_delete(payload)` | ✅ 进回收站 |
| `restore <rid>` | `recyclebin_revert([rid])` | ✅ 回到原位 |

**注意**：cp 同名会变成 `xxx(1)`，这是 115 服务端行为，不是 bug。

**仍未实跑**：`up` `offline` `dup`（触发）`sign` `share`。这些要么写盘、要么触发服务端长任务，
首次使用建议先 `--dry-run`。

## 测试遗留（需手动清）

回收站里留了 5 个测试对象（`__probe_renamed` ×2、`__selftest_up2.txt` ×2、`__selftest__`），
另有原有的 `Filmix.Trash`。115 彻底删除要安全密钥，脚本不猜密码，**需在网页端回收站点「清空」**。
