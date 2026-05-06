# Insurance Document QA Assistant

基于本地保险文档的 AI 检索问答系统。项目使用 Qwen Agent 构建 RAG（Retrieval-Augmented Generation）问答链路，支持从 `docs/` 目录中的多份保险文档中检索相关内容，并生成中文回答。系统提供 Web 交互界面，同时展示参考文档和处理日志，便于演示答案来源与检索过程。

## 核心能力

- **多文档问答**：自动加载本地 `.txt`、`.pdf` 保险文档作为知识库。
- **RAG 检索增强**：先检索相关文档片段，再结合大模型生成回答。
- **引用可追溯**：Web 页面展示本次回答参考的文档和片段。
- **过程可观测**：展示问题处理、文档检索、模型生成等关键步骤。
- **本地 Web 体验**：无需额外前端工程，启动脚本即可打开浏览器使用。
- **终端演示模式**：保留命令行运行方式，便于快速验证。

## 技术栈

- Python
- Qwen Agent
- OpenAI-compatible API
- python-dotenv
- Python 标准库 HTTP Server
- 本地 TXT/PDF 文档知识库

## 项目结构

```text
.
├── qwen-agent-multi-files.py       # 主程序：保险文档 RAG 问答 + Web 界面
├── assistant_ticket_bot-3.py       # 票务/订单分析助手示例
├── ai_bot-1.py                     # 早期文档问答示例
├── block_api_demo1.py              # 简单 Gradio 示例
├── docs/                           # 本地保险文档知识库
├── requirements.txt                # 项目依赖
├── .env.example                    # 环境变量模板
└── code-change-comment-guidelines.md
```

## 快速开始

### 1. 创建虚拟环境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. 安装依赖

```powershell
pip install -r requirements.txt
```

### 3. 配置环境变量

复制 `.env.example` 为 `.env`：

```powershell
Copy-Item .env.example .env
```

填写模型服务配置：

| 变量名 | 必填 | 说明 |
| --- | --- | --- |
| `AGICTO_BASE_URL` | 是 | OpenAI 兼容接口地址，脚本会自动补齐 `/v1` |
| `AGICTO_API_KEY` | 是 | 模型服务 API Key |
| `AGICTO_MODEL` | 是 | 使用的模型名称 |

示例：

```text
AGICTO_BASE_URL=https://api.agicto.cn
AGICTO_API_KEY=your_api_key
AGICTO_MODEL=deepseek-v4-flash
```

## 运行项目

### Web 模式

```powershell
python .\qwen-agent-multi-files.py
```

默认启动本地 Web 服务，监听 `127.0.0.1:7860`。

### 终端模式

```powershell
python .\qwen-agent-multi-files.py --tui
```

终端模式会运行一次内置示例问题，适合快速验证模型和文档检索链路。

## 示例问题

- 介绍下雇主责任险
- 雇主责任险和团体意外险有什么区别？
- 上下班途中发生事故是否属于雇主责任险保障范围？
- 雇主责任险的理赔流程是什么？

## 实现亮点

### 1. 完整 RAG 链路

系统从本地文档加载开始，经过文档解析、片段检索、上下文注入和模型生成，形成完整的本地知识库问答流程。

### 2. 多文件知识库

`docs/` 目录中可放置多份保险文档，主程序启动时自动扫描并传入 Qwen Agent，无需手动指定单个文件。

### 3. 答案来源可追溯

Web 页面展示本轮问答召回的参考文档和片段，方便判断回答是否有文档依据，也便于面试或演示时讲解 RAG 工作过程。

### 4. 轻量 Web 服务

主程序使用 Python 标准库提供本地 Web 页面，减少额外前端依赖，适合教学、演示和本地快速运行。

### 5. 配置与代码解耦

模型服务地址、API Key 和模型名称都通过 `.env` 管理，避免敏感配置写入代码。

## 开发验证

修改 Python 脚本后，可先进行语法检查：

```powershell
python -m py_compile qwen-agent-multi-files.py
```

运行 Web 或终端模式会发起真实模型调用，请确保 `.env` 已正确配置。

## 后续优化方向

- 增加更细粒度的引用定位，例如页码、段落编号或文件内位置。
- 优化检索排序，减少弱相关文档片段进入参考列表。
- 增加自动化测试，覆盖文档加载、环境变量校验和 API 输出格式。
- 将 Web 服务封装为更标准的应用结构，便于部署。
- 支持用户上传临时文档，扩展临时问答场景。
