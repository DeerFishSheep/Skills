---
name: pansou
description: 通过 PanSou 搜索网盘资源（115、夸克、阿里云、百度、UC、天翼、123、迅雷等），支持校验链接有效性。当用户提到盘搜、PanSou、找资源、搜网盘、搜电影/剧集/电子书、资源链接、磁力搜索时使用。
---

# PanSou 盘搜

调用 PanSou API 搜索网盘资源，按网盘类型分类展示，并可批量校验链接是否失效。

仅使用 Python 标准库，**无需安装依赖、无需虚拟环境**。

## 服务地址

默认使用 `https://pansou.259952.xyz`。

可通过环境变量指向自建实例：

```bash
export PANSOU_API_BASE=https://your-pansou.example.com
```

## 快速开始

```bash
# 看服务状态
python3 scripts/ps.py health

# 搜索
python3 scripts/ps.py search 繁花

# 搜索并验活
python3 scripts/ps.py search 繁花 --check

# 只验活指定链接
python3 scripts/ps.py check 'https://115cdn.com/s/xxxxx?password=yyyy'
```

## 命令

### search

```bash
python3 scripts/ps.py search <关键词> [选项]
```

| 选项 | 说明 | 默认 |
|---|---|---|
| `--type` | 网盘类型，逗号分隔 | `115,quark,aliyun` |
| `--from` | 数据来源：`all` / `tg` / `plugin` | `all` |
| `--limit` | 返回条数上限 | `20` |
| `--refresh` | 跳过服务端缓存，强制重新搜索 | 关闭 |
| `--check` | 搜索后自动校验链接有效性 | 关闭 |
| `--json` | 输出原始 JSON | — |

**支持的网盘类型**：`115` `quark` `aliyun` `baidu` `uc` `tianyi` `mobile` `123` `xunlei` `pikpak` `magnet` `ed2k`

```bash
# 搜多个网盘
python3 scripts/ps.py search 三体 --type 115,quark,aliyun --limit 10

# 只看 TG 来源，跳过缓存
python3 scripts/ps.py search 沙丘 --from tg --refresh

# 搜索 + 验活
python3 scripts/ps.py search 奥本海默 --check --limit 8
```

### check

```bash
python3 scripts/ps.py check <链接...> [--json]
```

校验链接是否仍然有效。自动从链接判断网盘类型，无需手动指定。

直接输出每个链接的状态：

```
✓ 有效    https://115cdn.com/s/xxxxx?password=yyyy
✗ 失效    https://115cdn.com/s/zzzzz?password=aaaa
          分享已取消

1/2 有效
```

**可校验的类型**：`115` `quark` `aliyun` `baidu` `uc` `tianyi` `mobile` `123` `xunlei`
**不支持**：`magnet` `ed2k` `pikpak`（返回 `unsupported`）

### health

```bash
python3 scripts/ps.py health
```

输出服务地址、状态、认证要求、插件数、TG 频道数、TG 可达性。

### plugins

```bash
python3 scripts/ps.py plugins
```

列出所有可用插件与 TG 频道名称，用于 `--from plugin` 时了解有哪些来源。

## 输出说明

搜索结果的每一条包含：

```
✓ 繁花(2023)【30集全】【4K.高码率】【杜比视界】
  2025-12-30 · tg:dianying4k
  https://115cdn.com/s/swzgial3h0m?password=zc39
```

- 行首图标：`✓` 有效 / `✗` 失效 / `🔒` 需要提取码 / `?` 无法判定 / 无图标表示未验活
- 第二行：日期 · 数据来源
- 第三行：链接（含提取码）

有 `--check` 时，**有效链接排在最前面**，失效的排在后面并标注原因。

## 校验状态

| state | 含义 | 缓存时长 |
|---|---|---|
| `ok` | 链接有效 | 24 小时 |
| `bad` | 链接已失效 | 6 小时 |
| `locked` | 需要提取码 | 12 小时 |
| `uncertain` | 无法判定 | 30 分钟 |
| `unsupported` | 该网盘类型不支持校验 | 24 小时 |

同一链接重复校验会命中缓存（`cache_hit: true`），不会重复请求上游。

## 与 115-Pan-Skill 配合

PanSou 负责「找」，115 skill 负责「存」。

```bash
# 1. 搜索并验活
python3 scripts/ps.py search 繁花 --type 115 --check

# 2. 挑一条有效链接，精确查看内容（标题、大小、文件列表）
python3 ~/.agents/skills/115-Pan-Skill/scripts/p115.py check 'https://115cdn.com/s/xxxxx?password=yyyy'

# 3. 转存到自己的网盘
python3 ~/.agents/skills/115-Pan-Skill/scripts/p115.py save 'https://115cdn.com/s/xxxxx?password=yyyy' /云下载
```

**分工**：

- PanSou 的 `check` 只知道「有效 / 失效」，适合快速筛掉死链
- 115 skill 的 `check` 能给出标题、大小、分享者、过期时间、内部文件列表，适合确认内容后再转存

两个 skill 相互独立，任一个不可用不影响另一个。

## 使用建议

**关键词策略**。资源标题通常包含年份、分辨率、版本信息，搜不到时：

```bash
# 加年份
ps.py search "沙丘 2024"

# 加版本
ps.py search "沙丘 4K"

# 去掉季数，搜总集
ps.py search "繁花 全集"

# 换翻译名
ps.py search "Dune"
```

**先验活再看**。PanSou 索引的是历史累积数据，越老的分享失效概率越高。看到几十条结果时先加 `--check` 过滤，避免在死链上浪费时间。

**限制返回数量**。`total` 是服务端命中总数，`--limit` 控制实际返回条数。默认 20 条足够，不需要一次取几百条。

**注意网盘类型**。搜索结果按链接域名分类，但有些标题写着「115」实际给的是别的网盘，以链接为准。

## 服务端行为

- 搜索是**多源并发**的（插件 + TG 频道），耗时 2–10 秒不等，取决于关键词命中量
- 限定 `--type` 会显著减少耗时
- 服务端有内存 + 磁盘两级缓存，重复查询会很快
- 官方实例与自建实例的插件数量不同，`health` 可查看

## 错误处理

| 现象 | 原因 | 处理 |
|---|---|---|
| `无法连接 PanSou 服务` | 地址错误或服务未运行 | 检查 `PANSOU_API_BASE`，或确认自建实例状态 |
| `HTTP 404 page not found` | 接口路径不对，或实例版本过旧 | 确认服务端版本，`check` 接口需较新版本 |
| `HTTP 400` | 请求参数不合法 | 检查 `--type` 取值，或用 `--json` 看原始响应 |
| 搜索结果为空但 `total > 0` | `--type` 过滤掉了所有结果 | 放宽 `--type` 或去掉该选项 |
| `unsupported` | 该网盘类型不支持验活 | 磁力、ed2k、PikPak 无法校验 |

## 接口参考

供需要自行扩展时使用。

### 搜索

```
POST /api/search
Content-Type: application/json
```

```json
{
  "kw": "关键词",
  "res": "merge",
  "src": "all",
  "cloud_types": ["115", "quark"],
  "refresh": false,
  "limit": 20
}
```

`res` 取值：`all`（返回 `results` 明细）/ `results` / `merge`（返回 `merged_by_type` 分类）

### 校验

```
POST /api/check/links
Content-Type: application/json
```

```json
{
  "items": [
    {"disk_type": "115", "url": "https://...", "password": "abcd"}
  ]
}
```

单次上限 **256** 条。

### 健康检查

```
GET /api/health
```

返回插件列表、TG 频道列表、认证状态、存活统计。
