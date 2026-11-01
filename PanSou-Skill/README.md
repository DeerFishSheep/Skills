# PanSou-Skill

通过 [PanSou](https://github.com/fish2018/pansou) 搜索网盘资源的命令行工具，同时可作为 AI agent 的 skill 使用。

支持 115、夸克、阿里云、百度、UC、天翼、移动、123、迅雷、PikPak、磁力、电驴等网盘类型，并能校验链接是否仍然有效。

## 特性

- **多网盘搜索** —— 一次搜索覆盖多个网盘来源，结果按类型分类
- **链接验活** —— 批量校验链接有效性，自动过滤失效资源
- **多源并发** —— 背后是数十个插件与百余个 Telegram 频道
- **零依赖** —— 纯 Python 标准库，不需要虚拟环境
- **附带查片工具** —— `scripts/tmdb.py` 走 TMDB 官方 API，搜前定片名、搜后写简介
- **可切换实例** —— 默认使用自建 PanSou 服务，也可通过环境变量指向任意实例

## 环境要求

| 项 | 要求 |
|---|---|
| Python | 3.8 或更高 |
| 操作系统 | macOS / Linux / Windows |
| 网络 | 可访问 PanSou 服务 |

无需安装任何依赖。

## 使用

```bash
cd PanSou-Skill

# 服务状态
python3 scripts/ps.py health

# 搜索（默认 115 + 夸克 + 阿里云 + 磁力）
python3 scripts/ps.py search 繁花

# 搜索并验活
python3 scripts/ps.py search 繁花 --check

# 指定网盘类型
python3 scripts/ps.py search 沙丘 --type 115,quark,aliyun --limit 10

# 校验已有链接
python3 scripts/ps.py check 'https://115cdn.com/s/xxxxx?password=yyyy'

# 查看可用插件与频道
python3 scripts/ps.py plugins

# 查片名 / 影片资料（附属工具，TMDB 官方 API）
python3 scripts/tmdb.py 尸变
```

完整命令说明见 [`SKILL.md`](SKILL.md)。

## 查影片资料：scripts/tmdb.py

搜资源前先用它把片名、年份确认准；需要介绍片子时也用它。

```bash
python3 scripts/tmdb.py 尸变                  # 中文名 / 原名 / 英文名都能搜
python3 scripts/tmdb.py "The Weight" 2026     # 第二参数限定年份
python3 scripts/tmdb.py --id 1290418          # 已知 TMDB id 直取
python3 scripts/tmdb.py 监狱雄心 --json       # 机器可读
```

输出中文名 / 原名 / 年份 / 类型 / 片长 / 导演 / 编剧 / 主演 / 评分 / 简介。

需要一个 TMDB API key，按下列顺序读取：

1. 环境变量 `TMDB_API_KEY`
2. `.secrets/tmdb_api_key`（skill 目录内，600 权限，已 gitignore）
3. `~/.config/tmdb/api_key`（旧位置，兼容）

```bash
mkdir -p .secrets && chmod 700 .secrets
echo '你的key' > .secrets/tmdb_api_key && chmod 600 .secrets/tmdb_api_key
```

## 命令一览

| 命令 | 用途 |
|---|---|
| `search <关键词>` | 搜索资源 |
| `check <链接...>` | 校验链接有效性 |
| `health` | 服务状态 |
| `plugins` | 列出插件与频道 |
| `scripts/tmdb.py <片名>` | 查片名与影片资料（附属工具） |

`search` 选项：

| 选项 | 说明 | 默认 |
|---|---|---|
| `--type` | 网盘类型，逗号分隔 | `115,quark,aliyun,magnet` |
| `--from` | `all` / `tg` / `plugin` | `all` |
| `--limit` | 返回条数 | `20` |
| `--refresh` | 跳过缓存 | 关闭 |
| `--check` | 搜完自动验活 | 关闭 |
| `--json` | 原始 JSON 输出 | — |

## 服务地址

默认指向 `https://pansou.259952.xyz`。

切换到其他实例：

```bash
export PANSOU_API_BASE=https://your-pansou.example.com
python3 scripts/ps.py health
```

也可以使用官方实例 `https://so.252035.xyz`，但该实例的校验接口当前不可用，`search` 正常。

## 与 115-Pan-Skill 配合

PanSou 负责找资源，[115-Pan-Skill](../115-Pan-Skill/) 负责存。

```bash
# 1. 搜索并验活
python3 scripts/ps.py search 繁花 --type 115 --check

# 2. 查看内容详情
python3 ../115-Pan-Skill/scripts/p115.py check 'https://115cdn.com/s/xxxxx?password=yyyy'

# 3. 转存到自己的网盘
python3 ../115-Pan-Skill/scripts/p115.py save 'https://115cdn.com/s/xxxxx?password=yyyy' /云下载
```

## 已知限制

| 项目 | 说明 |
|---|---|
| 磁力 / ed2k / PikPak | 不支持验活，返回 `unsupported` |
| 结果时效 | PanSou 索引历史数据，较老的分享可能已失效，建议加 `--check` |
| 搜索耗时 | 多源并发，常见 2–8 秒，冷门词可能更久 |
| 官方实例 | `check` 接口不可用，需自建实例 |

## 项目结构

```
PanSou-Skill/
├── SKILL.md          使用手册
├── NOTES.md          实现说明
├── README.md         本文件
├── LICENSE           MIT
├── requirements.txt  空（无第三方依赖）
└── scripts/
    └── ps.py         CLI 实现
```

## 接口来源

PanSou 的服务端项目：[fish2018/pansou](https://github.com/fish2018/pansou)（MIT）。

本仓库只包含客户端，不含服务端代码。

## 许可

MIT
