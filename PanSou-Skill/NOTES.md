# 实现说明

维护笔记：记录 PanSou API 的行为、参数语义与实测结论。`SKILL.md` 面向使用者，本文件面向改动代码的人。

## 架构

```
scripts/ps.py
    ├── 参数解析与中文输出
    ├── HTTP 请求（urllib，纯标准库）
    └── PanSou API（/api/search、/api/check/links、/api/health）
```

无第三方依赖，因此不需要虚拟环境与 `setup` 命令。直接 `python3 scripts/ps.py` 即可运行。

## 服务地址

```python
API_BASE = os.environ.get("PANSOU_API_BASE", "https://pansou.259952.xyz").rstrip("/")
```

默认指向自建实例。切换实例只需设置环境变量，无需改代码。

## urllib 的一个陷阱

给 `urllib.request.Request` 显式传 `method="GET"` 会导致请求失败，返回：

```
400 The plain HTTP request was sent to HTTPS port
```

不传 `method` 时，urllib 根据是否有 `data` 自动选择 GET / POST，行为正确。

**结论：不要给 Request 显式指定 `method`。**

```python
# 正确
req = urllib.request.Request(url, data=body, headers=headers)

# 错误 —— 会触发上述 400
req = urllib.request.Request(url, data=body, headers=headers, method="POST")
```

`urllib.request.Request` 在 Python 3.9 中甚至没有 `.method` 属性，显式传参本身也不具备可移植性。

## 搜索接口

```
POST /api/search
```

参数（定义见 PanSou 源码 `model/request.go`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `kw` | string | 关键词，必填 |
| `res` | string | `all` / `results` / `merge` |
| `src` | string | `all` / `tg` / `plugin` |
| `cloud_types` | array | 限定网盘类型 |
| `plugins` | array | 限定插件 |
| `channels` | array | 限定 TG 频道 |
| `refresh` | bool | 跳过缓存 |
| `conc` | int | 并发数 |
| `filter` | object | `{include: [], exclude: []}` 关键词过滤 |
| `ext` | object | 传递给插件的自定义参数 |

本实现固定使用 `res=merge` —— 直接拿到按网盘类型分组的链接，省去客户端分组。

### 返回结构

`res=merge` 时：

```json
{
  "code": 0,
  "data": {
    "total": 12,
    "merged_by_type": {
      "115": [{
        "url": "https://115cdn.com/s/xxxxx?password=yyyy",
        "password": "yyyy",
        "note": "标题描述",
        "datetime": "2025-12-30T04:22:59Z",
        "source": "tg:频道名 或 plugin:插件名",
        "images": ["..."]
      }]
    }
  }
}
```

`res=all` 时返回 `results[]`，每条含 `title` / `content` / `links[]` / `tags[]` / `channel`。
`links[]` 内每项有 `type` / `url` / `password`。

**`total` 是服务端命中总数，不受 `limit` 影响。** `limit` 只在客户端截断展示条数。

## 校验接口

```
POST /api/check/links
```

```json
{
  "items": [
    {"disk_type": "115", "url": "https://...", "password": "abcd"}
  ]
}
```

单次上限 **256** 条（源码 `api/limits.go` 中 `maxCheckItems = 256`）。本实现按 200 条分批。

### 支持的网盘类型

源码 `service/check_service.go` 中 `runCheck` 的 case 分支：

`aliyun` `quark` `uc` `baidu` `tianyi` `123` `xunlei` `115` `mobile`

其余类型走 `default` 分支，返回 `unsupported` + 「当前平台暂不支持检测」。
所以 `magnet` / `ed2k` / `pikpak` 无法校验。

### 状态与缓存

| state | summary 示例 | 缓存 TTL |
|---|---|---|
| `ok` | 链接有效 | 24 小时 |
| `bad` | 分享已取消 / 链接失效 | 6 小时 |
| `locked` | 115 需要提取码 | 12 小时 |
| `uncertain` | 请求失败 / 响应解析失败 | 30 分钟 |
| `unsupported` | 当前平台暂不支持检测 | 24 小时 |

TTL 定义见 `service/check_service.go` 的 `ttlForState()`。

响应含 `checked_at` 与 `expires_at`（毫秒时间戳），以及 `cache_hit` 标记。

## 115 校验的特殊行为

PanSou 校验 115 链接用 `https://115cdn.com/webapi/share/snap`，与 `115-Pan-Skill` 的做法一致。

这一点值得记录，因为 `webapi.115.com/share/info` 对**跨域分享**会误报「分享已取消」，
而 `share/snap` 能正确返回 `share_state`。两个接口的差异详见 115-Pan-Skill 的 NOTES.md。

## 官方实例与自建实例的差异

开发过程中对比了两套部署：

| 项目 | 官方 `so.252035.xyz` | 自建 `pansou.259952.xyz` |
|---|---|---|
| `/api/search` | 可用 | 可用 |
| `/api/check/links` | **404 / 超时** | 可用 |
| 插件数 | 72 | 40 |
| TG 频道数 | 125 | 108 |

官方实例的 `check` 接口路径在前端 JS 中确实存在（`/api/check/links`），
OPTIONS 探测返回 204，但实际 POST 请求返回 404 或超时。判断是该实例上的 check
服务未正常运行或存在网关配置问题。

**因此默认地址指向自建实例。**

## 网盘类型识别

`check` 命令需要知道链接属于哪种网盘，通过域名匹配：

```python
DOMAIN_TYPE = [
    ("115.com", "115"), ("115cdn.com", "115"),
    ("quark.cn", "quark"), ("pan.quark.cn", "quark"),
    ("aliyundrive.com", "aliyun"), ("alipan.com", "aliyun"),
    ...
]
```

`magnet:` 与 `ed2k:` 前缀单独处理。

注意 `anxia.com` 也是 115 的分享域名，但当前未列入自动识别 —— 遇到时会被判为 `others`，
需要手动指定类型的场景较少，暂不处理。

## 提取码提取

链接里的提取码有三种常见形式：

```
?password=yyyy
?pwd=yyyy
?p=yyyy
```

`check` 命令用正则统一提取：

```python
re.search(r"[?&](?:password|pwd|p)=([0-9a-zA-Z]+)", url)
```

## 输出排序

带 `--check` 时按状态排序，确保有效链接在最前面：

```python
order = {"ok": 0, "locked": 1, "uncertain": 2, "bad": 3, "unsupported": 4, None: 5}
```

未验活的结果排最后。

## 超时设置

`TIMEOUT = 180` 秒。搜索是多源并发的，冷门关键词可能触发全插件扫描，耗时较长。
实测常见关键词 2–8 秒返回，极端情况会超过 30 秒。

## 文件结构

```
PanSou-Skill/
├── SKILL.md          使用手册
├── NOTES.md          本文件
├── README.md         项目概览
├── LICENSE           MIT
├── requirements.txt  空（无第三方依赖）
├── .gitignore
└── scripts/ps.py     CLI 实现
```
