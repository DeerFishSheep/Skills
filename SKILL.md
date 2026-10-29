---
name: 115-pan
description: 操作 115 网盘（列目录、递归树、搜索、路径寻址、重命名、移动、复制、删除、回收站、分享、下载直链）。当用户提到 115 网盘、115 文件管理、云端文件整理、批量改名/移动/删除、查回收站、拿下载链接时使用。
---

# 115 网盘操作

跨平台通用 skill。基于 `webapi.115.com`，Cookie 认证，明文 JSON。

> ## ⚠️ 限流铁律：每秒最多 2 次请求
>
> 115 接口有**强限流**，超过约 2 次/秒会直接返回 **HTTP 405**（返回 HTML 错误页而不是 JSON），
> 而且会**持续几分钟才恢复**。恢复期间所有 `/files` 类接口全部不可用。
>
> - 脚本内置全局限流器 `_throttle()`：任意两次请求间隔 ≥ `MIN_INTERVAL`（1.0s），
>   **严格 1 次/秒**。所有请求都自动排队，不需要调用方自己 sleep。
> - **写调用方代码时不要再额外并发或循环狂打**。不要为了探测而连续试参数——
>   我干过这事，一次就把接口打成 405 了。
> - 调试/探索新接口时，**每次请求之间手动 sleep ≥ 1 秒**，并且一次只变一个变量。
> - 碰 405 立刻停，等 **5 分钟**再试。继续打只会延长封禁时间。
> - 遍历大目录（翻页）是最容易触发限流的场景，`tree` / `du` / `find` 天然要发很多请求，
>   跑之前先想清楚，别在大目录上反复跑。

## 一、认证（按优先级自动尝试）

脚本按以下顺序取 Cookie，命中即用：

1. 环境变量 `P115_COOKIE` —— 一行 `k=v; k=v`
2. 环境变量 `P115_COOKIE_FILE` —— Cookie 文件路径
3. 当前目录 `cookies.txt`
4. `~/.115/cookies.txt`
5. `/var/minis/shared/115/cookies.txt`（iOS Minis）

### 获取 Cookie 的三种方式

**A. 从本机浏览器自动读取（桌面端推荐）**
```bash
pip install browser-cookie3
python3 scripts/p115.py login            # 自动探测 chrome/edge/brave/safari/firefox
python3 scripts/p115.py login chrome     # 或指定浏览器
```
前提：该浏览器已登录 115.com。

**B. 环境变量（通用，适合 Agent 注入）**
```bash
export P115_COOKIE='UID=xxx; CID=xxx; KID=xxx; SEID=xxx'
```

**C. 手动保存**
```bash
python3 scripts/p115.py set-cookie 'UID=xxx; CID=xxx; KID=xxx; SEID=xxx'
```

必需 Cookie 键：`UID`、`CID`、`KID`、`SEID`（`acw_tc`、`115_lang` 可选）。

> **重名 Cookie 会被自动去重。** browser_cookie3 会把每个子域（`yun.115.com`、`act.115.com`…）
> 的 `acw_tc` 全导进来，一条请求里出现十几个同名 cookie 会让服务端解析异常。
> `dedupe_cookie()` 只保留每个键第一次出现的值，`login` / `set-cookie` 落盘前都会过一遍。

## 二、通用选项

任意命令都可加：

| 选项 | 作用 |
|---|---|
| `--json` | 输出原始 JSON，给 agent / 管道 / jq 用 |
| `--dry-run` | 写操作只打印将要做什么，不真改 |
| `--yes` | `purge` 的二次确认 |

## 三、路径寻址（重要）

**凡是接受 `<id>` 的地方，都可以直接写路径**，不用记十九位 cid：

```bash
p115.py ls "/🎬电影区"              # 根目录下的电影区
p115.py ls "/🎬电影区/蜘蛛侠：崭新之日 (2026)"   # 多级路径
p115.py ls 2956148449000553774      # 数字 id 照旧可用
p115.py ls 0                        # 根目录
```

`rename` / `mv` / `cp` / `rm` / `url` / `info` / `share` 全部支持路径。

## 四、命令

```bash
P=scripts/p115.py

python3 $P login [browser]        # 从浏览器导入 cookie
python3 $P set-cookie '<cookie>'  # 手动保存
python3 $P whoami                 # 账号 + cookie 签发时间 + 来源
python3 $P ls [cid|path] [off] [lim]     # 列目录（默认根）
python3 $P tree [cid|path] [depth]       # 递归树（完整翻页，带统计）
python3 $P info <id|path>         # 条目详情（原始字段）
python3 $P path <id>              # 反查完整路径
python3 $P search <关键字>         # 全局搜索（跨整个盘）
python3 $P find <关键字> [cid|path]  # 在指定目录下递归找
python3 $P du [cid|path]          # 统计目录占用
python3 $P mkdir <父cid|path> <名称>
python3 $P rename <id|path> <新名> [--dry-run]
python3 $P mv <目标cid|path> <id|path...>
python3 $P cp <目标cid|path> <id|path...>
python3 $P rm <id|path...>        # 删除进回收站（可恢复）
python3 $P purge <id...> --yes    # 彻底删除（不可恢复）
python3 $P rb                     # 列出回收站
python3 $P restore <rid...>       # 从回收站还原
python3 $P url <id|path>          # 拿下载直链
python3 $P share <id|path...>     # 创建分享链接
python3 $P dl <id|path> [输出目录] # 下载文件
```

## 五、接口对照（webapi.115.com）

| 操作 | 方法 | 路径 | 关键参数 |
|------|------|------|----------|
| 列目录 | GET | /files | cid,offset,limit,show_dir,o,asc,aid=1,natsort=1 |
| 详情 | GET | /files/get_info | file_id |
| 搜索 | GET | /files/search | search_value,cid=0,type=0 |
| 新建目录 | POST | /files/add | pid,cname |
| 重命名 | POST | /files/batch_rename | files_new_name[fid]=name |
| 移动 | POST | /files/move | pid=目标cid,fid[0]=,... |
| 复制 | POST | /files/copy | pid=目标cid,fid[0]=,... |
| 删除 | POST | /rb/delete | fid[0]=,... |
| 回收站 | GET | /rb | aid=1,cid=0,offset,limit |
| 还原 | POST | /rb/revert | rid[0]=,... （注意是 rid 不是 fid） |
| 下载直链 | GET | /files/download | pickcode=**pc 字段** |
| 创建分享 | POST | /share/send | file_ids（逗号分隔）,ignore_warn=1,is_share=1 |
| 账号 | GET | /user/info | - |

通用参数：`aid=1` 固定，`cid=0` 为根目录。

## 六、关键返回字段

- 目录：`cid`（目录ID）、`n`（名称）、`pid`（父ID）、`t`（修改时间戳）、`pc`（pickcode）
- 文件：`fid`（文件ID）、`n`、`s`（字节大小）、`sha`（哈希）、`pc`（pickcode）
- 判断目录：有 `cid` 且无 `fid`
- 列目录响应的 `path` 字段：完整祖先链，可直接用于反查路径
- 回收站：`id`（还原时作 `rid`）/`file_name`/`type`/`file_size`/`parent_name`

## 七、已验证结论

### 2026-09-20 首轮实测
- 115 客户端 HAR 里的 Cookie 可直接用于 webapi.115.com（会话共用）
- 列目录 / 账号 / 新建 / 重命名 / 移动 / 删除 全部返回 `state=true`
- 删除走 `/rb/delete`，进回收站，非彻底删除
- 复制 / 还原 / 回收站列表 均已实测通过

### 2026-10-29 加固与扩展
- **不存在的 cid 会静默返回根目录**（`state=true, cid=0`）。`_items()` 现在对比回显 cid，
  不一致直接报错。这是最危险的坑：打错一位会看到根目录还以为是成功了。
- **`tree` 现在完整翻页**，旧版只取首页 115 条会静默截断。
- **`UID=<uid>_<tag>_<ts>` 里的 ts 是签发时间，不是过期时间**。旧版 `whoami` 把它当过期时间，
  刚登录也显示 `-1 days left`。现已改为显示"签发于 N 小时前"。
- **`/files/download?pickcode=<pc>` 可拿到 `file_url` 直链**（VIP 账号验证通过）。
- **直链直接 GET 会被 CDN 403**：响应体是 `{"message":"no cookie value","status":403}`，
  `Server: AliyunOSS`。带全 cookie、换 UA、加 Range、改 Referer 全部无效 —— 说明 115 的 CDN
  需要客户端签名，不是普通 Cookie 能过的。**直链可复制到浏览器/迅雷/IDM 用，程序直接下载不通。**
- **`/share/send` 可用**，返回 `share_url`（`https://115cdn.com/s/xxxx`）+ `receive_code`。
  但**响应里没有 `share_id`**，且 `/share/delete`、`/share/cancel`、`/share/list` 全部返回
  `服务器开小差了` —— 分享只能用网页端撤销。
- **`/files/upload/init`（秒传）不可用**：返回 `服务器开小差了`。上传未实现。
- **`/files/getpathinfo` 不可用**（同上）。路径反查改用「父目录 list 的 `path` 字段」，
  已实现为 `path` 命令。
- **`/rb/clean` 返回 `密钥错误`**，彻底清空回收站的接口未打通。`purge` 只做到删进回收站。
- **`/files` 接口有强限流**：**每秒最多 2 次请求**，超了返回 HTTP 405（HTML 错误页，不是 JSON），
  并持续数分钟。脚本内置 `_throttle()` 全局限流器（间隔 1.0s，严格 1 次/秒），
  并对 405/429/5xx 做指数退避重试（2s/4s/6s）。
  - 405 可能会被误认为“参数错”或“接口挂”，**实际是限流**。
  - 触发后需冷却 **5 分钟以上**；继续请求会延长封禁。
  - 探索新接口时必须手动 sleep ≥ 1s，且一次只变一个变量。

## 八、安全约定

- 写操作（rename/mv/cp/rm/mkdir）建议先加 `--dry-run` 看一遍
- 删除默认只进回收站；`purge` 需要 `--yes`，且只能删进回收站（彻底删除接口未打通）
- Cookie 文件权限必须 600，禁止提交到任何仓库
- 环境变量名必须是 `P115_COOKIE`（不能以数字开头）
- **`url` 拿到的直链含账号凭证，不要贴到公开场合**

## 九、依赖

- Python 3，标准库即可（urllib/ssl/json/unicodedata）
- 可选：`browser-cookie3`（仅 `login` 从浏览器导入时需要）
  - 推荐装在独立 venv，避开 PEP 668：`python3 -m venv ~/.115/venv && ~/.115/venv/bin/pip install browser-cookie3`
  - Windows 新版 Chrome App-Bound 加密可能读不出，退回方式 B/C
  - macOS 读 Chrome/Safari 会弹 Keychain 授权，放行即可
  - Safari 需要「完全磁盘访问权限」，否则 `PermissionError`

## 十、仍未实现

- **上传**（秒传接口返回错误，普通分片上传未探索）
- **离线下载**（`/offline/add_task_urls` 未实测）
- **分享删除/管理**（接口全挂，只能网页端操作）
- **彻底删除 / 清空回收站**（`/rb/clean` 密钥错误）
- **目录打包下载**（`/files/download` 对目录返回「文件上传不完整」）
- **程序内直链下载**（CDN 防盗链，见上文）
