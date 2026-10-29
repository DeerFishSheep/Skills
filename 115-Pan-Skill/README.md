# 115-Pan-Skill

把 115 网盘当作文件系统操作的命令行工具，同时可作为 AI agent 的 skill 使用。

接口层由 [p115client](https://github.com/ChenyangGao/p115client) 承担，本仓库提供 CLI 外壳：cookie 管理、请求限流、路径寻址、中文输出。

## 特性

- **完整文件操作** —— 列目录、递归树、搜索、新建、重命名、移动、复制、删除、回收站还原
- **上传与下载** —— 分块上传、秒传、直链获取、脚本内直接下载
- **离线下载** —— 提交磁力与 ed2k 链接
- **分享管理** —— 创建、列举、撤销
- **路径寻址** —— `/电影区/蜘蛛侠` 可直接使用，无需记忆目录 id
- **自包含安装** —— 依赖装在 skill 目录内，可整体迁移
- **解释器自动切换** —— 任意 Python 调用都会自动切换到正确的 venv
- **请求限流** —— 内置 1 秒 1 次节流，避免触发服务端封禁

## 安装

需要 Python 3.11 或更高版本。

```bash
git clone <repo-url> 115-Pan-Skill
cd 115-Pan-Skill

python3 scripts/p115.py setup     # 创建 .venv 并安装依赖
python3 scripts/p115.py login     # 从本机浏览器导入 cookie
python3 scripts/p115.py doctor    # 验证安装
```

`login` 依赖浏览器中已登录 115.com。若无法自动导入，可手动传入：

```bash
python3 scripts/p115.py set-cookie 'UID=...; CID=...; KID=...; SEID=...'
```

## 使用

```bash
# 查看根目录
python3 scripts/p115.py ls 0

# 列出某个目录，深层展开
python3 scripts/p115.py tree "/🎬电影区" 2

# 全局搜索
python3 scripts/p115.py search 蜘蛛侠

# 复制、移动、重命名
python3 scripts/p115.py cp "/其他" "/图片/a.jpg"
python3 scripts/p115.py mv "/云下载" "/其他/备份"
python3 scripts/p115.py rename "/其他/备份" "备份2026"

# 上传与下载
python3 scripts/p115.py up ./archive.zip "/其他"
python3 scripts/p115.py dl "/其他/archive.zip" ./downloads

# 获取直链
python3 scripts/p115.py url "/其他/archive.zip"

# 分享
python3 scripts/p115.py share "/图片/a.jpg"
python3 scripts/p115.py shares
python3 scripts/p115.py share-cancel sws2c343wpd
```

完整命令列表见 [`SKILL.md`](SKILL.md)。

## 命令一览

| 分类 | 命令 |
|---|---|
| 环境 | `setup` `doctor` `whoami` `login` `set-cookie` |
| 读取 | `ls` `tree` `info` `path` `search` `find` `du` `space` `rb` |
| 写入 | `mkdir` `rename` `mv` `cp` `rm` `restore` |
| 传输 | `url` `dl` `up` |
| 离线 | `offline` `offline-list` |
| 分享 | `share` `shares` `share-cancel` |
| 其他 | `points` `sign` `dup` |

## 请求限流

115 后端限制约每秒 2 次请求，超出返回 HTTP 405 并封禁数分钟。脚本对每次接口调用施加 1 秒间隔，正常情况下无需干预。

需要注意：

- 不要并发执行多个命令
- `tree`、`du`、`find` 会随目录规模产生较多请求
- 遇到 405 应停止操作并等待 3–5 分钟

## 已知限制

| 项目 | 说明 |
|---|---|
| `sign` 签到 | 需 App 端登录态，网页 cookie 不可用。积分查询请用 `points` |
| 彻底删除 | 115 未公开按 id 彻底删除的接口，`rm` 仅移入回收站 |
| 回收站清空 | 需要安全密钥，需在网页端操作 |
| venv 迁移 | venv 内含绝对路径，换机器需重新执行 `setup` |

## 项目结构

```
115-Pan-Skill/
├── SKILL.md          使用手册（面向 agent 与用户）
├── NOTES.md          实现说明（面向维护者）
├── README.md         本文件
├── requirements.txt  依赖声明
├── .gitignore
└── scripts/
    └── p115.py       CLI 实现
```

`.venv/` 与 `cookies.txt` 在运行时生成，不纳入版本控制。

## 依赖

| 包 | 用途 | 许可 |
|---|---|---|
| [p115client](https://github.com/ChenyangGao/p115client) | 115 接口封装 | MIT |
| [browser-cookie3](https://github.com/borisbabic/browser_cookie3) | 从浏览器导入 cookie | BSD-3-Clause |

`p115client` 会引入 `p115cipher`（加解密）、`p115oss`（上传）、`p115pickcode`（id 转换）等传递依赖。

本仓库不包含上述项目的源码。

## 许可

MIT
