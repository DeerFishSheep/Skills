# Skills

AI Agent Skills 集合。每个 skill 是一个独立目录，自包含安装，可直接被 agent 使用或单独复制。

## Skill 列表

| Skill | 说明 | 依赖 |
|---|---|---|
| [115-Pan-Skill](115-Pan-Skill/) | 115 网盘命令行工具：文件管理、上传下载、离线、分享 | Python 3.11+ |

## 使用方式

每个 skill 目录内有独立说明：

- `README.md` —— 项目概览与安装
- `SKILL.md` —— 完整使用手册（面向 agent）
- `NOTES.md` —— 实现说明（面向维护者）

### 通用安装流程

```bash
git clone https://github.com/DeerFishSheep/Skills.git
cd Skills/<skill-name>

# 各 skill 的 setup 命令见其 README
```

## 约定

本仓库的 skill 遵循以下约定：

- **自包含** —— 运行时产物（虚拟环境、配置、凭证）位于 skill 目录内，可整体迁移
- **不复制上游代码** —— 第三方依赖通过 `requirements.txt` 声明，不 vendor
- **凭证不入库** —— `.gitignore` 排除 cookie、token 等敏感文件
- **文档分层** —— 使用手册与实现说明分离，各自面向不同读者
