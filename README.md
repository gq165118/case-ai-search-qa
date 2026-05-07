# Insurance Document QA Assistant

基于本地保险文档的 AI 检索问答系统。项目最初使用 Qwen Agent 自带文件 RAG 能力完成多文档问答；当前版本在保留 Qwen Agent `Assistant`、Memory、knowledge 注入和模型回答流程的基础上，增加了 Elasticsearch 检索后端，用于更清晰地演示“Qwen Agent + ES”的本地知识库问答链路。

## 核心能力

- **多文档问答**：自动加载 `docs/` 目录中的 `.txt`、`.pdf` 保险文档。
- **Qwen Agent RAG**：继续使用 Qwen Agent 组织文件、检索结果和模型回答。
- **Elasticsearch 检索后端**：通过 `rag_cfg.rag_backend = elasticsearch` 将底层 retrieval 扩展到 ES。
- **引用可追溯**：Web 页面展示本次回答参考的文档和片段。
- **过程可观测**：展示问题处理、ES 状态、文档检索、模型生成等关键步骤。
- **本地 Web 体验**：无需额外前端工程，启动脚本即可打开浏览器使用。
- **终端演示模式**：保留命令行运行方式，便于快速验证。

## 技术栈

- Python
- Qwen Agent
- Elasticsearch
- OpenAI-compatible API
- python-dotenv
- Python 标准库 HTTP Server
- 本地 TXT/PDF 文档知识库

## 项目结构

```text
.
├── qwen-agent-multi-files.py              # 主入口：参数解析，分发 Web/TUI 模式
├── qwen_agent_multi_files_config.py       # .env、LLM、RAG/ES 配置和 docs 文件加载
├── qwen_agent_multi_files_service.py      # Assistant 初始化、检索、流式问答事件
├── qwen_agent_multi_files_gui.py          # 本地 Web GUI 展示层
├── qwen_agent/                            # 本地 Qwen Agent 源码，加入 ES retrieval 扩展
│   ├── memory/memory.py                   # 根据 rag_backend 切换默认检索或 ES 检索
│   ├── tools/es_retrieval.py              # ES retrieval 工具
│   └── searcher/elasticsearch_searcher.py # ES 连接、索引、搜索
├── scripts/start-local-elasticsearch.ps1  # 本地 ES 启动辅助脚本
├── note/qwen-agent-es-rag-guide.md        # 本项目 Qwen Agent + ES 改造总结
├── docs/                                  # 本地保险文档知识库
├── requirements.txt                       # 项目依赖
├── .env.example                           # 环境变量模板
└── code-change-comment-guidelines.md      # 代码变更注释规范
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

### 4. 启动 Elasticsearch

当前配置默认连接：

```text
http://localhost:9200
```

如果你本机 Elasticsearch 安装在 `scripts/start-local-elasticsearch.ps1` 中配置的路径，可以运行：

```powershell
.\scripts\start-local-elasticsearch.ps1
```

如果 ES 安装路径不同，请先修改脚本中的：

```powershell
$EsHome = "D:\AI-App-Development\elastic\elasticsearch-9.4.0"
```

也可以自行用 Docker 或本机服务启动 ES，只要保证 `http://localhost:9200` 可访问即可。

## 运行项目

### Web 模式

```powershell
python .\qwen-agent-multi-files.py
```

默认启动本地 Web 服务，监听：

```text
http://127.0.0.1:7860
```

页面右侧会显示当前检索后端，例如：

```text
ES Elasticsearch 检索
地址：http://localhost:9200
索引：qwen_agent_rag_idx
模式：rag_cfg.rag_backend = elasticsearch
```

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

## ES 检索配置

ES 配置位于 `qwen_agent_multi_files_config.py`：

```python
rag_cfg = {
    "rag_backend": "elasticsearch",
    "max_ref_token": 20000,
    "parser_page_size": 500,
    "es": {
        "host": "http://localhost",
        "port": 9200,
        "index_name": "qwen_agent_rag_idx",
    },
}
```

当前实现会在检索时确保 `docs/` 中的文件已经写入 ES：

```text
docs 文件
  -> DocParser 解析分块
  -> Elasticsearch bulk 写入
  -> ES match / match_phrase / wildcard 检索
  -> Qwen Agent knowledge
  -> LLM 回答
```

详细改造说明见：

[note/qwen-agent-es-rag-guide.md](note/qwen-agent-es-rag-guide.md)

## 实现亮点

### 1. 保留 Qwen Agent 主流程

项目仍然使用 Qwen Agent 的 `Assistant` 完成问答组织，只是通过 `rag_cfg` 把底层 retrieval 扩展为 Elasticsearch。

### 2. ES 检索可观测

GUI 中会展示 ES 地址、索引名和运行模式；提问后调试过程会输出 ES 集群状态、索引文档块数和参考文档。

### 3. 配置、服务、GUI 分层

主入口保持轻量，配置、问答服务和 Web 展示分别拆分到独立文件，便于继续扩展。

### 4. 本地源码可改造

项目纳入了本地 `qwen_agent/` 源码，因此可以清楚演示 Memory 如何从默认 retrieval 切换到 `ESRetrievalTool`。

### 5. 为规模化检索预留空间

当前 ES 接入适合从少量文档 demo 走向更大知识库；后续可以继续做离线索引、metadata 过滤、向量检索和 rerank。

## 开发验证

修改 Python 脚本后，可先进行语法检查：

```powershell
python -m py_compile .\qwen-agent-multi-files.py .\qwen_agent_multi_files_config.py .\qwen_agent_multi_files_service.py .\qwen_agent_multi_files_gui.py .\qwen_agent\memory\memory.py .\qwen_agent\tools\es_retrieval.py .\qwen_agent\searcher\elasticsearch_searcher.py
```

运行 Web 或终端模式会发起真实模型调用；首次检索还会访问本地 ES，请确保 `.env` 和 Elasticsearch 都已正确配置。

## 后续优化方向

- 将 ES 索引流程拆成独立离线脚本，避免每次问答都遍历 `docs/`。
- 为每个 chunk 增加 metadata，例如险种、产品名、文件类型、更新时间。
- 增加更细粒度的引用定位，例如页码、段落编号或文件内位置。
- 增加向量检索和 rerank，提升口语化问题和语义问题的召回质量。
- 建立评测集，对比 Qwen Agent 默认检索、ES 检索、ES + 向量检索效果。
