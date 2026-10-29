# 实现说明

维护笔记：记录本工具的设计取舍、接口行为与实测结论。`SKILL.md` 面向使用者，本文件面向改动代码的人。

## 架构

```
scripts/p115.py
    ├── 参数解析与中文输出
    ├── cookie 读取、去重、持久化
    ├── call()  —— 全局限流 + 异常归一化 + 一次退避重试
    └── p115client —— 所有 115 接口调用
```

依赖通过 `requirements.txt` 声明，不复制上游源码。上游更新时无需改动本仓库。

## 限流

115 后端限制约每秒 2 次请求，超出返回 **HTTP 405**（HTML 错误页，非 JSON），并持续封禁数分钟。

`p115client` 自身不限流，单次 `tree` 可能发出数十个请求。因此节流必须包在**每个 client 方法调用**外层，而不是 CLI 命令入口：

```python
def call(fn, *args, **kwargs):
    for attempt in range(2):
        _throttle()            # 睡到距上次调用 ≥ 1.0s
        REQS[0] += 1
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if attempt == 0 and any(t in str(e) for t in TRANSIENT):
                time.sleep(3.0)
                continue
            raise RuntimeError(_explain(e)) from None
```

要点：

- `TRANSIENT` 仅含 405 / 429 / 5xx / timeout。**只重试一次** —— 405 重试会延长封禁窗口。
- `REQS[0]` 记录请求数，`tree` / `du` / `find` 结束时输出，便于估算耗时。
- **不可改为并发。** 两个 worker 即达到每秒 2 次上限，直接触发 405。

## p115client 版本约束

使用版本 **0.0.9.7.2**，要求 **Python ≥ 3.12**（`Requires-Python: >=3.12,<4.0`）。
3.9 / 3.10 / 3.11 下 pip 找不到可安装的发行版。`setup` 若在低版本 Python 下执行会失败，
需先升级解释器。

源码核对后的关键结论：

- **无 `check_for_relogin` 参数。** 控制命令行二维码的是 `P115Client(cookies, console_qrcode=False)`。代码显式传 `False`，任何路径下都不会进入扫码流程。
- **cookie 以字符串传入，不传路径。** 重名 cookie 必须在进入 client 前去除；传路径时 client 内部会回写文件，去重失效。
- **`download_url` / `download_url_app` 返回 `errno 99`**（该账号下实测）。可用的是 `download_url_web2`。
- **`fs_dir_getid2`（`/files/get_path_id`）返回空 `file_id`**，不可用。路径解析使用 `fs_dir_getid`。
- **`fs_storage_info` 是查询空间余量的正确方法**（1 请求、只读）。`tool_space` 是「校验空间」扫描任务，每账号每日仅可执行一次，不能用于查余量。
- **`clouddownload_task_add_urls` 是离线下载入口。** `extract_add_file` 是解压接口，与离线无关。

### 方法映射

| CLI | p115client 方法 | 关键参数 |
|---|---|---|
| `whoami` / `login` | `user_my` | — |
| `ls` / `tree` / `find` / 路径解析 | `fs_files` | `{"cid":…, "offset":…, "limit":…, "show_dir":1}` |
| `info` | `fs_file` | `file_id`（位置参数） |
| `path` | `fs_file` + `fs_files`（父目录） | 由父目录响应的 `path` 字段拼接 |
| `search` | `fs_search` | `{"search_value":…, "limit":30}` |
| `space` | `fs_storage_info` | — |
| `mkdir` | `fs_mkdir` | `fs_mkdir(name, pid)` |
| `rename` | `fs_rename` | **元组** `(fid, new_name)` |
| `mv` | `fs_move` | `fs_move([id…], pid)` |
| `cp` | `fs_copy` | `fs_copy([id…], pid)` |
| `rm` | `fs_delete` | `fs_delete([id…])` |
| `rb` | `recyclebin_list` | `{"offset":…, "limit":…}` |
| `restore` | `recyclebin_revert` | `recyclebin_revert([rid…])` |
| `url` / `dl` | `download_url_web2` | `pickcode`, `user_agent` |
| `up` | `upload_file` | `upload_file(path, pid=…)` |
| `offline` | `clouddownload_task_add_urls` | `{"url[0]":…, "wp_path_id":…}` |
| `offline-list` | `clouddownload_task_list` | `{"page":1}` |
| `dup` | `tool_repeat` | `{"folder_id": cid}` |
| `dup list` | `tool_repeat_list` | `{"s": offset, "l": 100}` |
| `share` | `share_send` | `{"file_ids": "id,id"}` |
| `shares` | `share_list` | `{"offset":…, "limit":…}` |
| `share-cancel` | `share_update` | `{"share_code":…, "action":"cancel"}` |
| `points` | `user_points_balance` | — |
| `sign` | `user_points_sign_post` | 需 App 端 cookie，网页 cookie 不可用 |
| 路径 → cid | `fs_dir_getid` | `{"path": "/a/b"}`，失败时回退本地逐级 `ls` |

## Cookie 处理

读取优先级：`P115_COOKIE` → `P115_COOKIE_FILE` → `<skill>/cookies.txt` → `./cookies.txt` → `~/.115/cookies.txt` → `/var/minis/shared/115/cookies.txt`。

**去重是必需的。** `browser_cookie3` 会导入 115.com 各子域的同名 cookie，实测一次出现 18 个同名 `acw_tc`，导致服务端行为异常（不报错，但返回不符合预期）。`dedupe()` 保留首次出现的值。

**`UID=<uid>_<tag>_<ts>` 中的 `<ts>` 表示签发时间。** 115 不公开真实过期时刻。`whoami` 输出签发时间并注明这一点。

## 路径解析与 cid 校验

115 对不存在的 cid **不返回错误，而是返回根目录内容**。若不校验，错误的 id 会静默得到根目录列表，后续操作将作用于错误目标。

`ls_page()` 比对响应回显：

```python
echoed = str(r.get("cid", ""))
if str(cid) != "0" and echoed and echoed != str(cid):
    err("目录不存在：cid=%s（115 回显 cid=%s）")
```

**自行调用 115 接口时必须做同样校验。**

分页：`webapi.115.com/files` 单页上限 115 条。`iter_all()` 持续翻页至不满一页为止，避免大目录被截断。`tree` 的请求数即由此产生。

## 下载：UA 与 cookie 的绑定

`download_url_web2(pickcode)` 返回 `{"url": …, "headers": {"cookie": …}}`。该 cookie 与请求时传入的 `user_agent` 绑定：

- 未传 `user_agent` 时，响应中 `headers["user-agent"]` 为空字符串，生成的 cookie 绑在空 UA 上。
- 此后无论使用何种 UA 请求，均返回 `403 {"message":"ua not match cookie"}`。

正确做法是把 UA 显式传给接口，下载时同时携带该 UA 与 cookie：

```python
DL_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

r  = client().download_url_web2(pc, user_agent=DL_UA)
url = r["url"]
ck  = r["headers"]["cookie"]
# GET url，headers 带 {"Cookie": ck, "User-Agent": DL_UA}
```

cookie 有效期为 15 分钟。下载请求直达 CDN，不经 115 的 webapi，因此不受 1 秒节流约束。

## 上传

`upload_file(path, pid=pid)` 内部完成：计算 sha1 → `upload_init` 判定秒传 → 未命中则分片上传至阿里云 OSS → 回调确认。

只有 web 接口部分经过 `call()` 节流；OSS 分片直传不受 115 webapi 限制。

## 分享

创建返回 `share_url`、`receive_code`、`share_code`。

**`share_list` 的返回体使用 `list` 字段，`data` 为 `null`** —— 与其他接口不一致，容易出错。

**条目中不含 `share_id`**（全为 `None`），仅有 `share_code`。撤销必须使用 `share_code`：

```
share_update({"share_code": code, "action": "cancel"})
```

`action` 可取 `cancel` 或 `delete`。

## 分享接收：为什么用 share/snap 而不是 share_info

接收外部分享需要两步：**校验** + **转存**。

### share_info 会误报

`webapi.115.com/share/info`（`client.share_info`）对跨域分享常返回
`state: false` + `分享已取消`，但同一链接在浏览器里打开是正常的。

实测同一个分享 `swsl91b3zdf`（提取码 `char`）：

| 接口 | 结果 |
|---|---|
| `webapi.115.com/share/info` | `state: false`，`分享已取消` |
| `115cdn.com/webapi/share/snap` | `state: true`，`share_state: 1`，标题/大小/文件列表齐全 |

### 正确接口

网页端分享页实际调用的是 `https://115cdn.com/webapi/share/snap`：

```
GET /webapi/share/snap
    share_code=<分享码>
    offset=0
    limit=20
    receive_code=<提取码>
    cid=

Headers:
  Referer: https://115cdn.com/s/<share_code>?password=<提取码>&
  X-Requested-With: XMLHttpRequest
  User-Agent: <DL_UA>
```

返回包含：

- `data.shareinfo.share_title` —— 分享标题
- `data.shareinfo.file_size` —— 总大小
- `data.shareinfo.share_state` —— `1` 正常
- `data.shareinfo.forbid_reason` —— 非空表示不可用
- `data.shareinfo.expire_time` —— `-1` 表示永久
- `data.list[].cid` / `.fid` —— 转存所需的 id
- `data.userinfo.user_name` —— 分享者

判定有效性：`state == true` 且 `forbid_reason` 为空 且 `share_state ∈ {0, 1}`。

### 转存

`client.share_receive` 对应 `POST webapi.115.com/share/receive`：

```python
{
  "share_code": code,
  "receive_code": pw,
  "file_id": "cid1,cid2",   # 从 snap 的 list 里取
  "cid": 目标目录
}
```

返回 `receive_title` / `recv_folder_count` / `recv_file_count` / `receive_size`。

实测转存 68.3 GB 单文件成功，落在指定目录。

## 签到不可用

`user_points_sign` / `user_points_sign_post` 要求 App 端登录态。实测 `app` 为 `web`、`android`、`ios`、`115ios` 及默认值，均返回「请重新登录」；`user_sign`（q.115.com）返回 HTML 错误页。

网页 cookie 无法完成签到，代码如实报错。积分查询走 `user_points_balance`，该接口正常。

## App 接口与 `k_ec`

App 使用 `proapi.115.com/{app}/2.0/ufile/files`，携带 `k_ec` 参数。

`k_ec` base64 解码为 48 字节，含 PKCS#7 填充（`06 06 06 06`、`4d 4d 4d`），属于**加密载荷而非签名**。上游已将实现拆分为独立包 `p115cipher`，无需自行实现。

`fs_files_app(app="115ios")` 实测静默返回空数据（`count=None`），不可用。本工具全部使用 web 端接口。

## 405 的成因

实测结论：

- 与出口 IP 无关
- 与 User-Agent 无关
- 属于接口级限流叠加登录态问题

对策是降低请求频率并保持 cookie 有效。

## 回收站

- `rm` 仅移入回收站。115 未公开「按文件 id 彻底删除」接口，因此不提供 `purge`。
- `recyclebin_clean2` 需要安全密钥，默认值 `000000` 会报「安全密钥错误」。本工具不代为猜测，彻底清空需在网页端操作。

## 安装路径与解释器切换

运行时产物集中在 skill 根目录：

```
<SKILL_DIR>/.venv/              依赖
<SKILL_DIR>/cookies.txt         凭证
<SKILL_DIR>/.setup-state.json   安装元数据
```

`SKILL_DIR = dirname(dirname(abspath(__file__)))`，由脚本位置推导，不写死。

**为什么放在 skill 目录内而非家目录**：skill 可能安装到任意位置（`~/.agents/skills/`、项目目录、其他路径）。依赖若散落在家目录，调用方无法仅凭 skill 目录判断安装状态。目录内自包含后，skill 安装到哪里，依赖就在哪里，多个副本互不干扰。

### venv 路径漂移

venv 的 `pyvenv.cfg` 与脚本 shebang 写死绝对路径，目录移动后失效。

`venv_is_stale()` 读取 `pyvenv.cfg` 的 `command` 行，取末段（创建时的目标路径）与当前 `VENV_HOME` 比较。不一致时 `setup` 会删除并重建。

### 解释器判断

判断当前进程是否运行在 skill 的 venv 中，**必须比较 `sys.prefix`，不能用 `realpath(sys.executable)`** —— venv 中的 `python` 是指向系统 Python 的符号链接，realpath 后两者相同，会导致误判为「已在 venv 中」而不切换。

```python
def in_fixed_venv():
    return os.path.realpath(sys.prefix) == os.path.realpath(VENV_HOME)
```

启动时若当前环境缺少 p115client 而 `<skill>/.venv` 存在，`_reexec_into_fixed_venv()` 通过 `os.execv` 切换解释器，并以 `P115_REEXEC=1` 防止递归。

### Python 版本门槛

`p115client` 声明 `Requires-Python: >=3.12,<4.0`。3.9 / 3.10 / 3.11 下 pip 报告
`Could not find a version that satisfies the requirement p115client (from versions: none)`，
信息不够直观。

`cmd_setup` 在创建 venv 前检查 `sys.version_info`，低于 3.12 时直接给出三个平台的升级命令。

注意：该检查只在 `.venv` 不存在时才有意义。若 `.venv` 已存在，
`_reexec_into_fixed_venv()` 会先把低版本解释器切换成 venv 内的 3.12+，
此时版本检查自然通过 —— 这是期望行为。

### 版本号读取

`p115client` 包内的 `__version__` 为过期手写值（0.0.9.7.2 的包中写作 `(0, 0, 9)`）。读取真实版本须用 `importlib.metadata.version("p115client")`。

### `.gitignore`

```
.venv/              依赖目录，体积约 79 MB
cookies.txt         凭证
.setup-state.json   含本机绝对路径
__pycache__/
*.pyc
```

仓库纯文件体积约 150 KB。

## 文件结构

```
115-Pan-Skill/
├── SKILL.md          使用手册
├── NOTES.md          本文件
├── README.md         项目概览
├── requirements.txt  依赖声明
├── .gitignore
└── scripts/p115.py   CLI 实现
```
