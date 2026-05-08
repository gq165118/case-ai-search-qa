# add by gq [2026-05-07：总结本项目从 Qwen Agent 默认检索扩展到 Elasticsearch 检索的改造过程]
# 本项目 Qwen Agent + Elasticsearch 检索改造总结

## 1. 本项目原始模式

本项目最开始是一个基于 Qwen Agent 的本地文档问答 demo。

核心思路是：

```text
docs/ 本地文档
  -> qwen-agent-multi-files.py 加载文件
  -> Assistant(files=files)
  -> Qwen Agent 内置 Memory / retrieval
  -> 文档解析、分块、关键词检索
  -> 把召回内容拼到模型上下文
  -> LLM 生成中文回答
```

原始模式的优点是简单，适合教学和 demo：

1. 不需要额外部署检索服务。
2. 只要把文件放进 `docs/` 目录即可。
3. Qwen Agent 自动负责文档解析、RAG 检索和上下文拼接。
4. 代码入口清晰，适合演示“本地文件问答”的基本流程。

原始模式的主要限制是：它更适合少量文档。当文件变多、PDF 变大、检索频率变高时，每次问答都依赖本地进程解析和检索，性能、可维护性和可观测性都会变弱。

## 2. 本次改造目标

本次改造不是推翻 Qwen Agent，而是在原来的 Qwen Agent 文件问答模式上增加 Elasticsearch 检索后端。

改造后的目标是：

1. 保留 Qwen Agent 的 `Assistant`、消息组织、knowledge 拼接和模型回答流程。
2. 保留 `docs/` 目录作为本地知识库来源。
3. 把底层 retrieval 从默认进程内检索扩展为 Elasticsearch 检索。
4. 在 GUI 上明确展示当前使用的是 ES 检索。
5. 为后续更大规模文档、离线索引、metadata 过滤、向量混合检索留下扩展空间。

改造后的整体链路：

```text
docs/ 本地文档
  -> qwen_agent_multi_files_config.py 加载配置和文件
  -> Assistant(files=files, rag_cfg=rag_cfg)
  -> Memory 发现 rag_backend = elasticsearch
  -> 使用 ESRetrievalTool 替换默认 retrieval
  -> scripts/index_docs_to_es.py 独立写入 ES
  -> ElasticsearchSearcher 只负责 ES 检索
  -> ES match / match_phrase 检索相关 chunk
  -> Qwen Agent 格式化 knowledge
  -> LLM 基于召回内容回答
```

一句话总结：

**项目仍然是 Qwen Agent 问答项目，只是把 Qwen Agent 内部的 retrieval 后端扩展成了 Elasticsearch。**

## 3. 本次改造涉及的文件

| 文件 | 改造后的职责 |
|---|---|
| `qwen-agent-multi-files.py` | 主入口，只负责参数解析和 GUI/TUI 分发 |
| `qwen_agent_multi_files_config.py` | `.env`、AGICTO 模型配置、`rag_cfg`、`docs/` 文件加载、ES 状态信息 |
| `qwen_agent_multi_files_service.py` | 初始化 `Assistant`、执行检索、生成流式问答事件、TUI demo |
| `qwen_agent_multi_files_gui.py` | Web GUI 展示层，显示聊天、调试过程、参考文档和 ES 检索后端 |
| `qwen_agent/memory/memory.py` | 根据 `rag_cfg.rag_backend` 选择默认 retrieval 或 ES retrieval |
| `qwen_agent/tools/es_retrieval.py` | 新增/使用 ES retrieval 工具，保持工具名为 `retrieval` |
| `qwen_agent/searcher/elasticsearch_searcher.py` | 负责连接 ES、创建索引、解析文件、批量写入、执行搜索 |
| `requirements.txt` | 增加 `qwen-agent[rag]` 和 `elasticsearch` 依赖 |


## 4. 原来的 Qwen Agent 默认检索

Qwen Agent 内置 RAG 支持常见文档类型，例如：

```text
pdf / docx / pptx / txt / html / csv / tsv / xlsx / xls
```

官方文档：

- https://qwenlm.github.io/Qwen-Agent/en/guide/core_moduls/rag/
- https://github.com/QwenLM/Qwen-Agent

默认检索链路：

```text
Assistant
  -> FnCallAgent
    -> Memory
      -> retrieval tool
        -> DocParser
        -> KeywordSearch / HybridSearch
        -> 返回 [{'url': ..., 'text': [...]}]
```

本地关键代码：

- `qwen_agent/memory/memory.py`
- `qwen_agent/tools/retrieval.py`
- `qwen_agent/tools/search_tools/base_search.py`
- `qwen_agent/agents/assistant.py`

默认检索的特点：

| 项目 | 说明 |
|---|---|
| 部署复杂度 | 低，不需要 ES |
| 文档来源 | 直接来自 `files` 参数或用户上传文件 |
| 检索方式 | 默认 BM25 关键词检索 |
| 存储方式 | 当前进程内处理，不是独立检索服务 |
| 召回限制 | 由 `max_ref_token` 控制最终进入模型的参考内容 |
| 适合场景 | 少量文件、教学 demo、临时文件问答 |

## 5. Qwen Agent 默认检索最多支持多少文件

结论：**官方文档没有给出“最多支持 N 个文件”的硬性限制，本地代码也没有固定文件数量上限。**

但是默认检索的实际瓶颈比较明确：

1. 文件越多，解析和分块越慢。
2. chunk 越多，进程内 BM25 排序越慢。
3. PDF 越复杂，解析成本越高。
4. 最终能送给模型的内容仍受 `max_ref_token` 和模型上下文窗口限制。

所以默认 Qwen Agent 检索更适合下面的规模：

| 文件规模 | 是否适合默认检索 | 说明 |
|---|---|---|
| 1-10 个小文件 | 很适合 | 简单、稳定、适合教学 |
| 10-50 个中小文件 | 可以使用 | 取决于文件大小和 PDF 复杂度 |
| 50-200 个文件 | 开始吃力 | 检索耗时、内存和解析成本会上升 |
| 200+ 文件或大量 PDF | 不建议只用默认检索 | 应考虑 ES、向量库、离线索引 |

这些数字是本项目的工程建议，不是 Qwen Agent 官方限制。

## 6. 本项目如何增加 ES 检索

### 6.1 配置层增加 `rag_cfg`

文件：`qwen_agent_multi_files_config.py`

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

含义：

| 参数 | 作用 |
|---|---|
| `rag_backend` | 指定检索后端，本项目设置为 `elasticsearch` |
| `max_ref_token` | 控制最多返回多少 token 的参考片段给模型 |
| `parser_page_size` | 文档分块大小，当前每块约 500 tokens |
| `es.host` | ES 服务地址 |
| `es.port` | ES 服务端口 |
| `es.index_name` | 文档 chunk 写入的 ES 索引 |

### 6.2 初始化 Assistant 时传入 `rag_cfg`

文件：`qwen_agent_multi_files_service.py`

```python
return Assistant(llm=llm_cfg,
                 system_message=system_instruction,
                 function_list=tools,
                 files=files,
                 rag_cfg=rag_cfg)
```

这里仍然使用 Qwen Agent 的 `Assistant`，只是多传了 `rag_cfg`。

### 6.3 Memory 根据配置切换检索工具

文件：`qwen_agent/memory/memory.py`

```python
if self.rag_backend == 'elasticsearch':
    from qwen_agent.tools.es_retrieval import ESRetrievalTool
    retrieval_tool = ESRetrievalTool(cfg=self.cfg)
    function_list.append(retrieval_tool)
else:
    function_list.append({
        'name': 'retrieval',
        'max_ref_token': self.max_ref_token,
        'parser_page_size': self.parser_page_size,
        'rag_searchers': self.rag_searchers,
    })
```

关键点：

```python
ESRetrievalTool.name = 'retrieval'
```

因此对 Qwen Agent 来说，仍然是在调用 `retrieval` 工具；只是这个工具的底层实现从默认检索换成了 ES。

### 6.4 ES 工具与离线索引职责分离

文件：`qwen_agent/tools/es_retrieval.py`

```python
search_results = self.searcher.search(query, max_ref_token=self.max_ref_token)
```

当前实现在线问答阶段只查询 ES，不再在问答链路中解析文件或写入索引。
离线或增量写入由 `scripts/index_docs_to_es.py` 负责。

### 6.5 ES 搜索器负责底层细节

文件：`qwen_agent/searcher/elasticsearch_searcher.py`

主要能力：

1. 连接 ES。
2. 索引不存在时自动创建。
3. 优先尝试 IK 中文分词器。
4. 没有 IK 时回退到标准分词器。
5. 使用 `DocParser` 解析文件并分块。
6. 使用 hash 生成 chunk ID，避免重复写入。
7. 使用 `_mget` 检查已存在 chunk。
8. 使用 `helpers.bulk` 批量写入 ES。
9. 使用 `match`、`match_phrase` 检索。

当前查询方式：

```python
"should": [
    {"match": {"content": {"query": query, "boost": 2}}},
    {"match_phrase": {"content": {"query": query, "boost": 3}}},
]
```

## 7. GUI 现在如何体现 ES 检索

文件：`qwen_agent_multi_files_gui.py`

当前 GUI 已经增加了明显的 ES 提示：

```text
ES Elasticsearch 检索
地址：http://localhost:9200
索引：qwen_agent_rag_idx
模式：rag_cfg.rag_backend = elasticsearch
```

右侧调试过程在提问时也会输出：

```text
检索后端：Elasticsearch
ES 地址：http://localhost:9200
ES 索引：qwen_agent_rag_idx
ES 集群状态：green/yellow/red
ES 当前索引文档块数：xxx
```

这样可以直观看到：当前不是 Qwen Agent 默认内存检索，而是 Qwen Agent + ES 检索。

## 8. 搭配 ES 后可以提升到多少文件

ES 后也不能简单按“文件数”判断容量，更应该按 chunk 数判断。

原因：

1. 一个大 PDF 可能切出上千个 chunk。
2. 很多短 txt 可能总共只有几百个 chunk。
3. ES 实际检索的是 chunk，不是原始文件。

本项目可以按下面方式估算：

| 方案 | 建议规模 | 说明 |
|---|---:|---|
| 原始 Qwen Agent 默认检索 | 1-50 个中小文件 | demo、教学、临时文件问答 |
| 当前 ES 单机模式 | 100-5,000 个中小文件 | 适合从 demo 走向较大知识库 |
| ES + 离线索引 | 5,000-50,000 个中小文件 | 需要独立索引脚本、增量更新 |
| ES 集群 + 数据管道 | 10 万级文件以上 | 需要生产级运维、监控和索引治理 |

这些是工程估算，不是官方硬限制。

Elasticsearch 官方文档也强调 bulk API 的批量大小需要按业务压测调优；默认 HTTP 请求大小限制为 100MB，大文档应先拆分再写入。

官方参考：

- Bulk API: https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-bulk
- Index settings: https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules

## 9. 当前实现还存在的优化点

当前 ES 检索已经能工作，但仍然是 demo 到工程化之间的状态。

最关键的优化已经拆出来了：

1. 独立索引脚本负责把 `docs/` 写入 ES。
2. 问答服务只查 ES，不在问答链路里做文件解析和写入。
3. 文件变更时通过文档签名做增量判断。
4. GUI 显示索引状态、文档数和签名，方便确认当前知识库是否已更新。
5. ES mapping 只保留正文检索字段，避免 `content.keyword` 这类长文本子字段带来的写入风险。

推荐结构：

```text
scripts/index_docs_to_es.py       # 手动/离线索引 docs
qwen_agent/tools/es_retrieval.py  # 查询时只 search
qwen_agent/searcher/...           # 保留 ES 建索引、状态和搜索能力
qwen_agent_multi_files_gui.py     # 展示 ES 状态、索引名、文档块数、签名
```

## 10. 使用场景总结

### 10.1 继续使用原始 Qwen Agent 检索

适合：

1. 教学 demo。
2. 文件数量少。
3. 临时上传文件。
4. 不想部署 ES。
5. 对检索速度要求不高。

不适合：

1. 文档数量持续增长。
2. 多用户共享知识库。
3. 需要权限过滤。
4. 需要稳定低延迟。
5. 需要可观测的索引状态。

### 10.2 使用本项目当前 ES 检索

适合：

1. 保险条款、产品说明、FAQ、制度文档。
2. 关键词比较明确的中文业务文档。
3. 文件量从十几个增长到几百、几千。
4. 需要展示参考文档和调试过程。
5. 后续计划扩展 metadata、过滤条件、离线索引。

不适合：

1. 用户问法和原文表达差异特别大。
2. 需要强语义匹配。
3. 需要跨多个文档做复杂推理。

### 10.3 后续增加向量检索

如果用户问题越来越口语化，可以考虑向量检索。

可选方向：

| 方案 | 特点 |
|---|---|
| FAISS | 本地轻量，适合 demo |
| Chroma | 简单易用，适合小型知识库 |
| Qdrant | 部署简单，过滤能力较好 |
| Milvus | 更偏生产级向量库 |
| Elasticsearch dense_vector | 可以在 ES 内做关键词 + 向量混合 |

### 10.4 ES + 向量 + Rerank

更完整的生产级检索链路可以是：

```text
用户问题
  -> ES BM25 召回 topN
  -> 向量检索召回 topN
  -> 合并去重
  -> reranker 重排
  -> 取 topK
  -> 拼入 Qwen Agent knowledge
  -> LLM 回答
```

这种方式适合保险、法务、客服、制度问答等正式知识库场景。

## 11. 本项目后续可以讨论的方向

### 方向 A：离线索引

新增脚本：

```text
scripts/index_docs_to_es.py
```

目标：

1. 手动或定时把 `docs/` 写入 ES。
2. 问答时不再重复解析所有文档。
3. GUI 显示索引状态。
4. 支持 `--recreate` 进行 mapping 调整后的全量重建。

### 方向 B：增加 metadata

写入 ES 时增加更多字段：

```json
{
  "content": "...",
  "source": "...",
  "file_type": "pdf",
  "product_name": "雇主责任险",
  "category": "责任险",
  "updated_at": "2026-05-07"
}
```

好处：

1. 可以按险种过滤。
2. 可以按文件类型过滤。
3. 可以在 GUI 中显示更准确的引用来源。

### 方向 C：答案引用

让回答中带上引用编号：

```text
上下班途中发生非本人主要责任的交通事故，通常属于工伤相关责任范围。[1]
```

右侧参考文档和答案引用可以对应起来。

### 方向 D：评测集

建立 `eval_questions.jsonl`：

```json
{"question": "上下班途中事故算不算？", "expected_source": "2-雇主责任险.txt"}
```

用于比较：

1. 原始 Qwen Agent 检索。
2. 当前 ES 检索。
3. ES + 向量。
4. ES + rerank。

## 12. 本项目当前结论

本项目不是从零重写 RAG，而是在原有 Qwen Agent 文件问答 demo 上做了增强：

1. **保留 Qwen Agent**：继续使用 `Assistant`、Memory、knowledge 注入和模型回答。
2. **增加 ES 后端**：通过 `rag_cfg.rag_backend = elasticsearch` 切换底层 retrieval。
3. **增强可观察性**：GUI 明确展示 ES 地址、索引名、检索模式和调试过程。
4. **为规模化做准备**：后续可以做离线索引、metadata、向量混合和 rerank。

当前最推荐的下一步是：**把 ES 索引流程从问答流程中拆出来，做成独立离线索引脚本。**

这样项目会从“能用 ES 检索的 demo”进一步变成“更接近生产结构的本地知识库问答系统”。
# add end
