---
name: 115-pan
description: 操作 115 网盘（列目录、递归树、搜索、重命名、移动、复制、删除、回收站、上传、下载直链、离线下载、空间、排重、分享、签到）。当用户提到 115 网盘、115 文件管理、云端文件整理、批量改名/移动/删除、查回收站、上传下载文件到 115、磁力离线到 115 时使用。
---

# 115 网盘 CLI

`scripts/p115.py` 是 p115client 的薄外壳。所有 115 接口调用都由 p115client 完成，本 skill 只维护：cookie 管理、限流、路径寻址、中文输出。

## ⚠️ 限流铁律（先看这条）

**115 后端最多每秒 2 次请求。超了返回 HTTP 405，并封禁数分钟。**

本脚本已经内置 `call()` 包装器，**每次 p115client 调用间隔 ≥ 1 秒**，你不需要自己 sleep。
但你必须知道：

- **不要并发跑命令。** 两个 `p115.py tree` 同时跑 = 每秒 2 次 = 直接 405。
- **命令之间有代价。** `tree` 深度 3 可能发几十次请求 = 几十秒。预算见下方命令表。
- **看到 405 就是限流，不是登录问题。** 停手等 3-5 分钟。继续重试只会延长封禁。
- **405 和登录失效容易混。** 405 是 HTML 错误页；登录失效是 JSON 里 `errno` 为 `990001` 或 `99`。

## Cookie（三种来源 + 去重坑）

认证优先级，找到就用：

1. 环境变量 `P115_COOKIE` —— 一行 `k=v; k=v`
2. 环境变量 `P115_COOKIE_FILE` —— 文件路径
3. `./cookies.txt`
4. `~/.115/cookies.txt`
5. `/var/minis/shared/115/cookies.txt`（iOS Minis）

导入方式：

```bash
p115.py login              # 从浏览器自动嗅探（chrome → edge → brave → …）
p115.py login safari       # 指定浏览器
p115.py set-cookie '<k=v; ...>'   # 手动传
p115.py whoami             # 验证 + 看 cookie 签发时间
```

**去重坑（真实存在）**：`browser_cookie3` 会把各子域同名 cookie 全导进来，实测出现 **18 个同名 `acw_tc`**，服务端解析异常。本脚本在 cookie 进 client 之前已去重（保留第一次出现），你不用管。手工拼 cookie 时也别重复。

**UID 末段是签发时间，不是过期时间。** `UID=<uid>_<tag>_<ts>` 里的 `ts` 是签发时刻。115 不公开真实过期时间，别再拿它算「还剩几天」。

## 命令速查

请求数按实测/源码推算给出，用于判断一次操作要等多久。

| 命令 | 用途 | 示例 | 请求数 |
|---|---|---|---|
| `whoami` | 账号 + cookie 状态 | `p115.py whoami` | 1 |
| `ls [目标] [offset] [limit]` | 列目录 | `p115.py ls 0` | 1 |
| `tree [目标] [深度]` | 递归列目录，完整翻页 | `p115.py tree /图片 2` | 目录数 ≈ 请求数 |
| `info <id\|path>` | 单个条目详情 | `p115.py info /图片/a.jpg` | 1–2 |
| `path <id>` | 由 id 反查完整路径 | `p115.py path 2956275452366290775` | 2 |
| `search <关键字>` | 全局搜索 | `p115.py search 蜘蛛侠` | 1 |
| `find <关键字> [目标]` | 在目录树里按名递归找 | `p115.py find 蜘蛛侠 /🎬电影区` | 遍历到的目录数 |
| `du [目标]` | 统计占用 | `p115.py du /🎬电影区` | 遍历到的目录数（深） |
| `space` | 总空间/已用/剩余 | `p115.py space` | 1 |
| `mkdir <父> <名称>` | 新建文件夹 | `p115.py mkdir /其他 备份` | 2 |
| `rename <目标> <新名>` | 重命名 | `p115.py rename /其他/备份 备份2` | 2–3 |
| `mv <目标目录> <项...>` | 移动 | `p115.py mv /其他 /图片/a.jpg` | 2+项数 |
| `cp <目标目录> <项...>` | 复制 | `p115.py cp /其他 /图片/a.jpg` | 2+项数 |
| `rm <项...>` | 删除（进回收站） | `p115.py rm /其他/备份2` | 2+项数 |
| `rb [offset]` | 看回收站 | `p115.py rb` | 1 |
| `restore <rid...>` | 从回收站还原 | `p115.py restore 3550645885618619647` | 1 |
| `url <目标>` | 取可下载直链 | `p115.py url /图片/a.jpg` | 2 |
| `dl <目标> [输出目录]` | 下载到本地 | `p115.py dl /图片/a.jpg ./tmp` | 2 + CDN 流量（⚠ 见已知限制） |
| `up <本地文件> [目标目录]` | 上传 | `p115.py up ./a.zip /其他` | 2（分片走 OSS 不计限流） |
| `offline <链接...> [--to 目录]` | 离线下载 | `p115.py offline 'magnet:?xt=...' --to /云下载` | 2 |
| `offline-list [page]` | 看离线任务进度 | `p115.py offline-list` | 1 |
| `dup [目录]` | 启动全盘排重扫描 | `p115.py dup` | 2 |
| `dup list [offset]` | 取排重结果 | `p115.py dup list` | 1 |
| `share <项...>` | 创建分享链接 | `p115.py share /图片/a.jpg` | 2+项数 |
| `sign` | 每日签到 | `p115.py sign` | 1（见下方限制） |

通用选项，加在任意命令后：

- `--json` —— 输出原始 JSON，给管道/agent 解析用
- `--dry-run` —— 写操作只打印不执行（mkdir/rename/mv/cp/rm/up/offline/share/dl 都支持）
- `--yes` —— 危险操作跳过二次确认（非交互环境必须加）

## 路径寻址

凡是参数写成 `<id|path>` 的地方，以下四种写法等价可用：

```
0                      根目录
/🎬电影区               根目录下的目录（带不带前导 / 都行）
/🎬电影区/蜘蛛侠：崭新之日   多级路径
2956148449000553774    直接给数字 id（最快，省掉解析请求）
```

**用 id 比用路径省请求。** 路径要 1 次 `getid`（服务端查不到时本地逐级 `ls`，更贵）；id 直接命中。

**假 cid 坑（已修）**：115 对不存在的 cid **静默返回根目录**，不报错。旧实现照单全收，打错一位就看到根目录还以为成功了。本脚本会比对响应里的 `cid` 回显，不匹配直接报「目录不存在」。如果你自己写脚本调 115 接口，务必做同样的校验。

## 错误码对照

| 现象 | 含义 | 怎么办 |
|---|---|---|
| HTTP **405**（HTML 错误页） | 触发限流 | 停 3–5 分钟，确认没有并发进程。不要重试加固 |
| `errno 99` / **990001** 登录超时 | cookie 失效 | `p115.py login` 重新导入 |
| `errno 99` + `k_ec` 相关 | 该接口是 App 接口，要加密参数 | 换 web 端接口。本 skill 不用 App 接口 |
| **990009** 操作尚未执行完成 | 上一个删除/还原/复制还在跑 | 等几秒再执行 |
| **231011** 文件已删除 | 目标已不存在 | `p115.py rb` 看回收站 |
| 空间不足 | 网盘满了 | `p115.py space` 看余量 |
| 取直链 `errno 99` | App 版 `download_url` 不可用 | 已在代码里改用 web 版 `download_url_web2`，正常路径不会撞到 |

## 已知限制（真实存在，不要当成 bug 去修）

- **`sign` 大概率失败**。签到接口 `proapi.115.com/{app}/2.0/user/points_sign` 要求 App 端登录态，网页 cookie 会返回 `errno 99`。代码已如实报错，不伪装成功。
- **`dl` 实测 403，`url` 可用。** 直链本身拿得到（`url` 命令实测通过，可复制到浏览器/迅雷下载），但脚本直接 GET CDN 会 403 —— 已实测 8 种 UA / cookie / Range 组合全部 403，是 115 的防盗链，不是代码问题。所以：**要下载就用 `url` 拿链接交给浏览器，不要指望 `dl`。**
- **删除只能进回收站。** 115 没有「按文件 id 彻底删除」的公开接口，本工具不提供 `purge`。要彻底清空请 rm 后在网页端回收站操作。
- **回收站彻底删除需要安全密钥。** `recyclebin_clean2` 用默认 `000000` 会报「安全密钥错误」。README 里不猜用户密码。
- **`offline` 对无效链接直接拒绝**，返回「错误的链接」。磁力链要带完整 `magnet:?xt=urn:btih:...`。
- **`dup` 是两段式。** 先 `dup` 触发服务端全盘扫描（耗时不定），再 `dup list` 取结果。扫描是一次性的，不要反复触发。
- **`du` 和 `find` 深度上限分别是 8 和 6。** 更深的树会静默截断，防止请求数爆炸。

## 未验证命令

以下命令代码已写好、方法名与 p115client 源码签名核对过，但**没有实跑过**（涉及写入用户网盘或需要特定条件）：`mkdir` `rename` `mv` `cp` `rm` `restore` `up` `offline` `dup` `sign` `share`。

已完成 `--dry-run` 验证（参数解析、路径寻址均正确）：`mkdir` `up` `offline`。

实测**跑通**的是：`whoami` `ls` `tree` `info` `path` `search` `find` `du` `space` `rb` `url` `dl`（`dl` 卡在 CDN 403，直链获取本身正常）、`dup list`。

未验证的命令先用 `--dry-run` 看要做什么，再加 `--yes` 真跑。

## 接口源库

本 skill 不复制上游代码，全部 115 接口调用通过 p115client 完成：

- PyPI: https://pypi.org/project/p115client/
- 源码: https://github.com/ChenyangGao/p115client
- 作者: ChenyangGao
- 许可: MIT
- 实际使用版本: 0.0.9.7.2
- 关键传递依赖: p115cipher（加解密）、p115oss（上传）、p115pickcode（id 转换）

安装：pip install -r requirements.txt

本仓库只维护：CLI 外壳、cookie 管理与去重、全局节流、路径寻址、中文输出。
接口层的 bug 与更新归上游项目。

## 安装

```bash
pip install -r requirements.txt
python scripts/p115.py login     # 或 set-cookie
python scripts/p115.py whoami    # 验证
```

维护细节、抓包结论、踩坑记录见 `NOTES.md`。
