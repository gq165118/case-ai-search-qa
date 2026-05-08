# Insurance Document QA Assistant

基于本地保险文档的 AI 检索问答系统。项目最初使用 Qwen Agent 自带文件 RAG 能力完成多文档问答；当前版本在保留 Qwen Agent `Assistant`、Memory、knowledge 注入和模型回答流程的基础上，增加了 Elasticsearch 检索后端，用于更清晰地演示“Qwen Agent + ES”的本地知识库问答链路。

## 核心能力

- **多文档问答**：自动加载 `docs/` 目录中的 `.txt`、`.pdf` 保险文档。
- **Qwen Agent RAG**：继续使用 Qwen Agent 组织文件、检索结果和模型回答。
- **Elasticsearch 混合检索后端**：通过 `rag_cfg.rag_backend = elasticsearch` 将底层 retrieval 扩展为 BM25 + 向量融合检索。
- **text-embedding-v3 向量召回**：索引阶段写入 chunk embedding，查询阶段补充语义召回并做 RRF 融合重排。
- **Tavily MCP 可选联网搜索**：配置 `TAVILY_API_KEY` 后，可在 GUI 中按本轮开关允许 Qwen Agent 调用 Tavily MCP。
- **引用可追溯**：Web 页面展示本次回答参考的文档和片段。
- **过程可观测**：展示问题处理、ES 状态、文档检索、模型生成等关键步骤。
- **本地 Web 体验**：无需额外前端工程，启动脚本即可打开浏览器使用。
- **终端演示模式**：保留命令行运行方式，便于快速验证。

## 技术栈

- Python
- Qwen Agent
- Elasticsearch
- Tavily MCP
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
│   ├── tools/es_retrieval.py              # ES retrieval 与离线索引工具
│   ├── searcher/es_index_state.py         # ES 索引状态文件读写和文档签名
│   └── searcher/elasticsearch_searcher.py # ES 连接、索引、搜索
├── scripts/index_docs_to_es.py            # docs 离线写入 ES 的索引脚本
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

### 5. 可选配置 Tavily MCP

默认情况下，文档问答不会打开联网搜索。是否联网不再通过 `.env` 开关控制，而是在 GUI 里按每一轮提问单独打开或关闭。

如需让 Qwen Agent 在用户明确要求联网搜索、查询最新信息，或本地文档没有依据时调用 Tavily，可在 `.env` 中配置：

```text
TAVILY_API_KEY=your_tavily_api_key
```

Tavily MCP 通过 `npx -y tavily-mcp@0.1.3` 启动，因此本机需要安装 Node.js/npm，并能执行 `npx`。如果 `npx` 不在 PATH，可额外配置：

```text
TAVILY_MCP_COMMAND=C:\Program Files\nodejs\npx.cmd
```

GUI 右侧会显示“联网搜索”面板和“本轮联网”开关：开关关闭时本轮只使用本地文档检索；开关打开后，模型仍只会在需要时调用 Tavily。只有当调试过程出现“联网搜索调用/联网搜索完成”时，才表示本轮真的使用了 Tavily 联网搜索。

### 6. 建立 ES 索引

当前版本已经将“写入索引”和“在线问答”拆开：问答时只查询 ES，不再重复解析 `docs/`。

首次运行或 `docs/` 文件变化后，先执行：

```powershell
python .\scripts\index_docs_to_es.py
```

只想查看待索引文件，不写入 ES：

```powershell
python .\scripts\index_docs_to_es.py --dry-run
```

如果 ES mapping 调整过，需要删除旧索引并重建：

```powershell
python .\scripts\index_docs_to_es.py --recreate
```

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
    "embedding": {
        "enabled": True,
        "model": "text-embedding-v3",
        "base_url": "https://api.agicto.cn/v1",
        "vector_field": "embedding",
    },
}
```

当前实现通过独立脚本先把 `docs/` 写入 ES，在线问答阶段只查询 ES：

```text
docs 文件
  -> DocParser 解析分块
  -> text-embedding-v3 生成 chunk 向量
  -> Elasticsearch bulk 写入
  -> ES BM25 + dense_vector 向量召回
  -> RRF 融合重排
  -> Qwen Agent knowledge
  -> LLM 回答
```

向量模型默认复用 AGICTO OpenAI 兼容配置：

```text
AGICTO_BASE_URL=https://api.agicto.cn
AGICTO_API_KEY=your_api_key
AGICTO_EMBEDDING_MODEL=text-embedding-v3
```

新增或调整向量 mapping 后，建议重建索引：

```powershell
python .\scripts\index_docs_to_es.py --recreate
```

详细改造说明见：

[note/qwen-agent-es-rag-guide.md](note/qwen-agent-es-rag-guide.md)

## Tavily MCP 配置

Tavily MCP 在 `qwen_agent_multi_files_config.py` 中只读取 `TAVILY_API_KEY` 和可选的 `TAVILY_MCP_COMMAND`。是否把 Tavily 工具加入 Qwen Agent 的 `function_list`，由 GUI 本轮开关传给后端决定。

本轮联网关闭时：

```python
build_agent_tools(enable_tavily=False)
```

本轮联网打开且已配置 `TAVILY_API_KEY` 时，会追加：

```python
{
    "mcpServers": {
        "tavily-mcp": {
            "command": "npx",
            "args": ["-y", "tavily-mcp@0.1.3"],
            "env": {
                "TAVILY_API_KEY": "...",
            },
        },
    },
}
```

这样项目仍以本地保险文档 QA 为主，Tavily MCP 只作为需要联网搜索时的补充工具。

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

当前 ES 接入适合从少量文档 demo 走向更大知识库；已经支持 BM25 + text-embedding-v3 向量召回 + RRF 融合重排，后续可以继续做 metadata 过滤和更专业的 reranker。

## 开发验证

修改 Python 脚本后，可先进行语法检查：

```powershell
python -m py_compile .\qwen-agent-multi-files.py .\qwen_agent_multi_files_config.py .\qwen_agent_multi_files_service.py .\qwen_agent_multi_files_gui.py .\qwen_agent\memory\memory.py .\qwen_agent\tools\es_retrieval.py .\qwen_agent\searcher\es_index_state.py .\qwen_agent\searcher\elasticsearch_searcher.py .\scripts\index_docs_to_es.py
```

运行 Web 或终端模式会发起真实模型调用；检索会访问本地 ES，请确保 `.env`、Elasticsearch 和索引都已正确配置。

## 后续优化方向

- 为离线索引增加更完整的增量更新、失败重试和索引版本治理。
- 为每个 chunk 增加 metadata，例如险种、产品名、文件类型、更新时间。
- 增加更细粒度的引用定位，例如页码、段落编号或文件内位置。
- 接入专门 reranker 模型，对 BM25 + 向量召回后的候选片段做二次精排。
- 建立评测集，对比 Qwen Agent 默认检索、ES BM25 检索、ES 混合检索效果。
