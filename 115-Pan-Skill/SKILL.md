---
name: 115-pan
description: 操作 115 网盘（列目录、递归树、搜索、重命名、移动、复制、删除、回收站、上传、下载直链、离线下载、空间、排重、分享、签到）。当用户提到 115 网盘、115 文件管理、云端文件整理、批量改名/移动/删除、查回收站、上传下载文件到 115、磁力离线到 115 时使用。
---

# 115 网盘 CLI

命令行工具，把 115 网盘当成文件系统操作。接口层由 [p115client](https://github.com/ChenyangGao/p115client) 承担，本仓库提供 CLI 外壳：cookie 管理、限流、路径寻址、中文输出。

## 安装

需要 **Python 3.12 或更高**（`p115client` 的硬性要求）。

```bash
git clone https://github.com/DeerFishSheep/Skills.git
cd Skills/115-Pan-Skill

python3 scripts/p115.py setup     # 在 skill 目录建 .venv 并装依赖
python3 scripts/p115.py login     # 从本机浏览器导入 cookie
python3 scripts/p115.py doctor    # 验证一切就绪
```

`setup` 幂等，重复执行安全，会自动处理目录迁移后的 venv 失效问题。所有的运行时产物都在 skill 目录内：

```
115-Pan-Skill/
├── .venv/            依赖（setup 创建，不入库）
├── cookies.txt       cookie（权限 600，不入库）
├── SKILL.md
├── NOTES.md
├── README.md
├── requirements.txt
└── scripts/p115.py
```

**venv 不能跨机器拷贝**（内部写死绝对路径）。换机器请重新跑 `setup`；检测到路径漂移时会自动重建。

### 解释器自动切换

若当前 python 缺少 p115client，而 skill 内 `.venv` 存在，脚本会自动切换过去。以下写法结果一致：

```bash
python3 scripts/p115.py ls 0              # 自动切
/usr/bin/python3 scripts/p115.py ls 0     # 自动切
.venv/bin/python scripts/p115.py ls 0     # 直接使用，无切换开销
```

推荐直接用 `.venv/bin/python`。

### 自检

新环境接手时先跑 `doctor`，不要猜：

```bash
python3 scripts/p115.py doctor
python3 scripts/p115.py doctor --json     # 机器可读
```

输出覆盖：skill 目录、venv 状态（含路径漂移检测）、p115client 版本与位置、cookie 来源、账号连通性。

## ⚠️ 限流

**115 后端最多每秒 2 次请求。超出返回 HTTP 405，并封禁数分钟。**

脚本内置 `call()` 包装器，每次 p115client 调用间隔 ≥ 1 秒，无需自行 sleep。但必须注意：

- **不要并发执行。** 两个 `tree` 同时跑即达每秒 2 次，直接 405。
- **命令有请求代价。** `tree` 深度 3 可能发几十次请求。预算见命令表。
- **405 是限流，不是登录问题。** 停手等 3–5 分钟，重试会延长封禁。
- **405 与登录失效的区分**：405 返回 HTML 错误页；登录失效返回 JSON，`errno` 为 `990001` 或 `99`。

## Cookie

认证来源，按优先级取第一个可用的：

1. 环境变量 `P115_COOKIE` —— `k=v; k=v`
2. 环境变量 `P115_COOKIE_FILE` —— 文件路径
3. `<skill 目录>/cookies.txt`
4. `./cookies.txt`
5. `~/.115/cookies.txt`
6. `/var/minis/shared/115/cookies.txt`

```bash
p115.py login                    # 自动探测浏览器（chrome → edge → brave → safari → firefox）
p115.py login safari             # 指定浏览器
p115.py set-cookie '<k=v; ...>'  # 手动传入
p115.py whoami                   # 验证并查看签发时间
```

必需键：`UID`、`CID`、`KID`、`SEID`。

**重名 cookie 会被自动去重。** `browser_cookie3` 会把各子域同名 cookie 全部导入，实测可出现 18 个同名 `acw_tc`，导致服务端解析异常。脚本在 cookie 进入 client 前去重，保留首次出现的值。

**`UID=<uid>_<tag>_<ts>` 中的 `<ts>` 是签发时间，不是过期时间。** 115 不公开真实过期时刻。

## 命令

请求数列用于估算等待时间。

### 环境

| 命令 | 用途 | 请求数 |
|---|---|---|
| `setup` | 安装依赖到 skill 内 `.venv` | 0 |
| `doctor` | 自检路径/依赖/cookie/账号 | 0–1 |
| `whoami` | 账号与 cookie 状态 | 1 |

### 读取

| 命令 | 用途 | 示例 | 请求数 |
|---|---|---|---|
| `ls [目标] [offset] [limit]` | 列目录 | `p115.py ls 0` | 1 |
| `tree [目标] [深度]` | 递归列目录，完整翻页 | `p115.py tree /图片 2` | ≈ 目录数 |
| `info <目标>` | 条目详情 | `p115.py info /图片/a.jpg` | 1–2 |
| `path <id>` | 由 id 反查完整路径 | `p115.py path 2956275452366290775` | 2 |
| `search <关键字>` | 全局搜索 | `p115.py search 蜘蛛侠` | 1 |
| `find <关键字> [目标]` | 在目录树内递归按名查找 | `p115.py find 蜘蛛侠 /🎬电影区` | ≈ 遍历目录数 |
| `du [目标]` | 统计占用 | `p115.py du /🎬电影区` | ≈ 遍历目录数 |
| `space` | 总空间/已用/剩余 | `p115.py space` | 1 |
| `rb [offset]` | 列出回收站 | `p115.py rb` | 1 |

### 写入

| 命令 | 用途 | 示例 |
|---|---|---|
| `mkdir <父> <名称>` | 新建文件夹 | `p115.py mkdir /其他 备份` |
| `rename <目标> <新名>` | 重命名 | `p115.py rename /其他/备份 备份2` |
| `mv <目标目录> <项...>` | 移动 | `p115.py mv /其他 /图片/a.jpg` |
| `cp <目标目录> <项...>` | 复制 | `p115.py cp /其他 /图片/a.jpg` |
| `rm <项...>` | 删除到回收站 | `p115.py rm /其他/备份2` |
| `restore <rid...>` | 从回收站还原 | `p115.py restore 3550645885618619647` |

### 传输

| 命令 | 用途 | 示例 |
|---|---|---|
| `url <目标>` | 获取下载直链 | `p115.py url /图片/a.jpg` |
| `dl <目标> [输出目录]` | 下载到本地 | `p115.py dl /图片/a.jpg ./tmp` |
| `up <本地文件> [目标目录]` | 上传 | `p115.py up ./a.zip /其他` |

### 离线下载

| 命令 | 用途 | 示例 |
|---|---|---|
| `offline <链接...> [--to 目录]` | 提交离线任务 | `p115.py offline 'magnet:?xt=...' --to /云下载` |
| `offline-list [page]` | 查看任务进度 | `p115.py offline-list` |

### 分享与积分

| 命令 | 用途 | 示例 |
|---|---|---|
| `check <链接>` | 校验分享链接，显示内容 | `p115.py check 'https://115cdn.com/s/xxx?password=yyy'` |
| `save <链接> [目录]` | 转存分享到自己的网盘 | `p115.py save 'https://115cdn.com/s/xxx?password=yyy' /云下载` |
| `share <项...>` | 创建分享链接 | `p115.py share /图片/a.jpg` |
| `shares` | 列出我的分享 | `p115.py shares` |
| `share-cancel <share_code...>` | 撤销分享 | `p115.py share-cancel sws2c343wpd` |
| `points` | 查询积分余额 | `p115.py points` |
| `sign` | 每日签到 | `p115.py sign`（不可用，见下） |

### 排重

| 命令 | 用途 | 示例 |
|---|---|---|
| `dup [目录]` | 触发全盘排重扫描 | `p115.py dup` |
| `dup list [offset]` | 读取排重结果 | `p115.py dup list` |

### 通用选项

| 选项 | 作用 |
|---|---|
| `--json` | 输出原始 JSON，供管道或程序解析 |
| `--dry-run` | 写操作只打印计划，不执行 |
| `--yes` | 跳过危险操作的二次确认（非交互环境必需） |

## 分享接收

从外部拿到 115 分享链接后，两步走：

```bash
# 1. 先校验，看内容是否值当
p115.py check 'https://115cdn.com/s/swsmyd73h8c?password=vwvw'

# 2. 转存到自己的网盘
p115.py save 'https://115cdn.com/s/swsmyd73h8c?password=vwvw' /云下载
```

链接写法都支持：

```
https://115cdn.com/s/xxxxx?password=yyyy
https://115.com/s/xxxxx?password=yyyy
xxxxx yyyy
xxxxx
```

`save` 默认只转存第一项，加 `--all` 转存全部。支持 `--dry-run`。

**校验用的是 `115cdn.com/webapi/share/snap`，不是 `webapi.115.com/share/info`。**
后者对跨域分享常误报「分享已取消」，前者是网页端分享页实际调用的接口，能拿到
标题、大小、分享者、过期时间、文件列表。

## 路径寻址

凡参数为 `<id|path>` 处，以下写法等价：

```
0                          根目录
/🎬电影区                   根目录下的一级目录（前导 / 可省略）
/🎬电影区/蜘蛛侠：崭新之日     多级路径
2956148449000553774        数字 id，直接命中
```

**用 id 比用路径省请求。** 路径需先解析（服务端查不到时退化为本地逐级 `ls`），id 直接命中。

**不存在的 cid 会被拦截。** 115 对无效 cid 不报错，而是静默返回根目录内容。脚本比对响应中的 `cid` 回显，不匹配即报「目录不存在」。自行调用 115 接口时应做同样校验。

## 错误码

| 现象 | 含义 | 处理 |
|---|---|---|
| HTTP **405**（HTML 错误页） | 触发限流 | 停 3–5 分钟，确认无并发进程 |
| `errno` **990001** / **99** 登录超时 | cookie 失效 | `p115.py login` 重新导入 |
| `errno` **990009** 操作尚未执行完成 | 上一个写入操作仍在处理 | 等数秒重试 |
| `errno` **231011** 文件已删除 | 目标不存在 | `p115.py rb` 查看回收站 |
| 空间不足 | 配额已满 | `p115.py space` 查看余量 |
| `403 ua not match cookie` | 下载 cookie 与 UA 不匹配 | 使用 `dl` 命令，勿自行拼接请求 |

## 已知限制

### `sign` 不可用

签到接口 `proapi.115.com/{app}/2.0/user/points_sign` 要求 App 端登录态。实测 `app` 为
`web` / `android` / `ios` / `115ios` 及默认值均返回「请重新登录」；`user_sign`（q.115.com）
返回 HTML 错误页。网页 cookie 无法完成签到。

代码如实报错，不伪装成功。查询积分请用 `points`，该接口正常。

### 下载的 UA 必须与 cookie 配对

`download_url_web2` 返回一对「直链 + 专用 cookie」，该 cookie 绑定 `user_agent` 参数。
不传 `user_agent` 时接口生成的 cookie 绑在空 UA 上，任何 UA 请求都会返回
`403 ua not match cookie`。

脚本固定使用 `DL_UA` 常量并显式传给接口，下载时同时携带 `Cookie` 与该 UA。
直链 cookie 有效期 15 分钟。

### 撤销分享使用 `share_code`

`share_list` 返回的条目**不含 `share_id` 字段**，仅有 `share_code`。
撤销走 `share_update(share_code=..., action="cancel")`。

### 删除只能进回收站

115 未公开「按文件 id 彻底删除」接口。`rm` 只把对象移入回收站，
彻底清空需在网页端回收站操作。工具不提供 `purge`。

回收站彻底删除需要安全密钥，本工具不代为猜测。

### 其他

- **`offline`** 拒绝无效链接，磁力链需含完整 `magnet:?xt=urn:btih:...`。
- **`dup` 为两段式**：先 `dup` 触发服务端扫描（耗时不定），再 `dup list` 取结果。扫描为一次性，不要反复触发。
- **`du` 与 `find` 深度上限分别为 8 和 6**，更深层级会被截断以避免请求数失控。
- **`cp` 遇同名自动追加 `(1)`**，为 115 服务端行为。

## 测试状态

以下命令已在真实账号上验证通过：

- **读取**：`doctor` `whoami` `ls` `tree` `info` `path` `search` `find` `du` `space` `rb` `dup list` `shares` `points`
- **写入**：`mkdir` `rename` `cp` `mv` `rm` `restore`
- **传输**：`url` `dl` `up`（上传下载往返 SHA1 一致）
- **分享**：`share` `shares` `share-cancel`（完整闭环）、`check` `save`（校验与转存，已实测 68GB 文件转存成功）

以下命令已实现并通过参数校验，但未在真实环境中执行，首次使用建议先加 `--dry-run`：

- `offline` `offline-list` `dup`

`sign` 因接口限制不可用，见上。

## 接口源库

全部 115 接口调用由 [p115client](https://pypi.org/project/p115client/) 完成，本仓库不复制其代码。

| 项 | 值 |
|---|---|
| PyPI | https://pypi.org/project/p115client/ |
| 源码 | https://github.com/ChenyangGao/p115client |
| 作者 | ChenyangGao |
| 许可 | MIT |
| 使用版本 | 0.0.9.7.2 |
| 传递依赖 | `p115cipher`（加解密）、`p115oss`（上传）、`p115pickcode`（id 转换） |

本仓库负责：CLI 外壳、cookie 管理与去重、全局节流、路径寻址、中文输出。
接口层的问题与更新归上游项目。

实现细节与接口行为记录见 `NOTES.md`。
