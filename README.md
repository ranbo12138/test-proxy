# 🚀 LLM Proxy - 智能 API 代理服务

一个轻量级、高可用的 LLM API 代理服务，支持自动错误重试、流式输出和实时监控面板。同时兼容 OpenAI 和 Anthropic (Claude) 两种 API 格式。

[![GitHub Actions](https://img.shields.io/badge/CI-GitHub%20Actions-blue)](https://github.com/features/actions)
[![Docker](https://img.shields.io/badge/Docker-Ready-brightgreen)](https://www.docker.com/)
[![License](https://img.shields.io/badge/License-Apache%202.0-yellow.svg)](LICENSE)

---

## ✨ 核心特性

### 🔄 智能错误重试
- **自动重试机制**：检测到 `rate limit` 错误时自动切换上游 API
- **可配置重试次数**：通过环境变量灵活调整（默认 3 次）
- **快速重试**：无延迟，充分利用上游的高额度

### 🌊 完整流式输出支持
- **SSE 协议**：完美支持 Server-Sent Events 流式传输
- **打字机效果**：实时显示 AI 回复，提升用户体验
- **兼容性强**：支持所有标准 OpenAI 和 Anthropic 客户端

### 🔐 安全认证
- **自定义 API Key**：使用你自己的密钥保护服务
- **权限隔离**：上游密钥与客户端密钥分离，更安全
- **多种认证方式**：支持 `Authorization: Bearer` 和 `x-api-key`

### 🎯 多 API 格式支持
- **OpenAI 格式**：`/v1/chat/completions` 接口
- **Anthropic 格式**：`/v1/messages` 接口
- **模型列表**：`/v1/models` 接口

### 📊 实时监控面板
- **可视化统计**：总请求数、成功率、失败率一目了然
- **请求日志**：最近 50 条请求的详细记录，包括重试次数
- **运行状态**：服务运行时间、限流错误次数实时监控
- **详细错误信息**：每条失败请求都有详细的错误说明

### ☁️ 云原生部署
- **容器化**：基于 Docker，一键部署
- **多平台支持**：Zeabur、Railway、Render、Fly.io 等
- **自动构建**：GitHub Actions 自动构建镜像

---

## 🎯 快速开始

### 1️⃣ Fork 本仓库

点击右上角的 **Fork** 按钮，将项目复制到你的 GitHub 账号下。

### 2️⃣ 配置环境变量

在你的云平台（如 Zeabur）中设置以下环境变量：

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `PROXY_URL` | 上游 API 地址 | `https://api.example.com/v1` |
| `API_KEY` | 上游 API 密钥 | `sk-xxxxxxxxxxxxx` |
| `MY_ACCESS_KEY` | 你自定义的访问密钥 | `my-secret-key-12345` |
| `MAX_RETRIES` | 最大重试次数（可选） | `3` |

### 3️⃣ 部署到云平台

#### 使用 Zeabur 部署

1. 登录 [Zeabur](https://zeabur.com)
2. 创建新项目，选择 "从 GitHub 导入"
3. 选择你 Fork 的仓库
4. 添加上述环境变量
5. 点击部署，等待完成

#### 使用 Docker 本地部署

```bash
docker build -t llm-proxy .
docker run -d \
  -p 8000:8000 \
  -e PROXY_URL="https://api.example.com/v1" \
  -e API_KEY="sk-xxxxxxxxxxxxx" \
  -e MY_ACCESS_KEY="my-secret-key-12345" \
  -e MAX_RETRIES="3" \
  llm-proxy
```

### 4️⃣ 配置你的 LLM 客户端

部署成功后，在你的 AI 客户端（如 ChatBox、OpenCat、Claude Desktop 等）中配置：

#### OpenAI 格式客户端
- **API 地址**：`https://你的域名/v1/chat/completions`
- **API Key**：你在 `MY_ACCESS_KEY` 中设置的密钥

#### Anthropic 格式客户端
- **API 地址**：`https://你的域名/v1/messages`
- **API Key**：你在 `MY_ACCESS_KEY` 中设置的密钥

#### 模型列表
- **地址**：`https://你的域名/v1/models`

---

## 📊 管理面板

直接访问你的部署域名（如 `https://你的域名`），即可查看实时监控面板。

### 面板功能

- ✅ **实时统计**：总请求数、成功/失败数、成功率
- ✅ **错误监控**：限流错误次数统计
- ✅ **请求日志**：最近 50 条请求的详细记录
- ✅ **重试追踪**：每条请求的实际重试次数
- ✅ **错误详情**：失败请求的详细错误信息
- ✅ **运行状态**：服务启动时间和运行时长

---

## 🛠️ 技术栈

- **后端框架**：Flask (Python)
- **HTTP 客户端**：Requests
- **容器化**：Docker
- **CI/CD**：GitHub Actions
- **部署平台**：Zeabur / Railway / Render 等

---

## 📁 项目结构

```
test-proxy/
├── app.py                 # 主应用代码
├── requirements.txt       # Python 依赖
├── Dockerfile            # Docker 镜像配置
├── .github/
│   └── workflows/
│       └── docker.yml    # 自动构建配置
└── README.md             # 项目文档
```

---

## 🔧 高级配置

### 自定义重试次数

在环境变量中设置 `MAX_RETRIES`：

```bash
MAX_RETRIES=5  # 最多重试 5 次
```

### 修改监听端口

默认端口为 `8000`，如需修改，编辑 `app.py` 最后一行：

```python
app.run(host='0.0.0.0', port=你的端口)
```

---

## 🐛 常见问题

### Q1: 为什么返回 "Permission Denied"？

**A:** 检查你的 `MY_ACCESS_KEY` 是否正确配置，以及客户端的 API Key 是否与之匹配。

### Q2: 流式输出不工作？

**A:** 确保你的客户端支持 SSE（Server-Sent Events），并且在请求中设置了 `"stream": true`。

### Q3: 重试后仍然失败？

**A:** 如果所有重试都遇到限流，说明上游所有 API 都暂时不可用，请稍后再试。你会收到错误信息：`错误重试全都rate limit,请再次重试.`

### Q4: 数据会持久化吗？

**A:** 当前版本的统计数据存储在内存中，服务重启后会清空。如需持久化，可以自行添加数据库支持（如 SQLite）。

### Q5: 支持哪些 API 格式？

**A:** 目前支持：
- OpenAI Chat Completions API (`/v1/chat/completions`)
- Anthropic Messages API (`/v1/messages`)
- OpenAI Models API (`/v1/models`)

### Q6: 如何查看详细的错误信息？

**A:** 访问管理面板（你的域名首页），在"最近请求日志"表格中，鼠标悬停在"详细信息"列即可查看完整错误。

---

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建你的特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交你的改动 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启一个 Pull Request

---

## 📄 开源协议

本项目采用 [Apache License 2.0](LICENSE) 开源协议。

---

## 🙏 致谢

- 感谢所有开源贡献者
- 感谢 Flask 和 Requests 项目
- 感谢各大云平台提供的免费额度

---

## 📮 联系方式

如有问题或建议，欢迎通过以下方式联系：

- 提交 [GitHub Issue](https://github.com/ranbo12138/test-proxy/issues)
- 在 GitHub 上 Star 和 Fork 本项目

---

<div align="center">

**⭐ 如果这个项目对你有帮助，请给个 Star 支持一下！⭐**

Made with ❤️ by [ranbo12138](https://github.com/ranbo12138)

</div>