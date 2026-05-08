# qwen_agent/tools/es_retrieval.py
import json
from qwen_agent.tools.base import BaseTool, register_tool
from qwen_agent.searcher.elasticsearch_searcher import ElasticsearchSearcher
from qwen_agent.settings import DEFAULT_MAX_REF_TOKEN

class ESRetrievalTool(BaseTool):
    """
    一个使用 Elasticsearch 作为后端的检索工具。
    在线问答阶段只负责搜索；文档写入请使用 scripts/index_docs_to_es.py。
    """
    name = 'retrieval'  # 保持名称为 'retrieval' 以便在 Memory 中进行替换
    description = '从 Elasticsearch 索引的文档中检索与用户查询相关的内容。'
    parameters = [{
        'name': 'query',
        'type': 'string',
        'description': '用户查询的关键词或问题',
        'required': True
    }, {
        'name': 'files',
        'type': 'list',
        'description': '兼容 Qwen Agent Memory 的文件列表参数；ES 在线检索阶段不会解析这些文件',
        'required': True
    }]

    def __init__(self, cfg: dict = None):
        super().__init__(cfg)
        self.cfg = cfg or {}
        self.max_ref_token = self.cfg.get('max_ref_token', DEFAULT_MAX_REF_TOKEN)
        # 初始化 ES 搜索器，它内部会管理文档解析
        self.searcher = ElasticsearchSearcher(cfg=self.cfg)

    def call(self, params: dict, **kwargs) -> str:
        """
        工具调用的主入口。
        1. 解析 Memory 传入的查询。
        2. 只查询 Elasticsearch，不在问答链路中解析或写入文件。
        3. 返回 Qwen Agent 期望的检索结果格式。
        """
        query_input = params.get('query', '')

        # 1. 如果没有查询，直接返回空列表
        if not query_input:
            return json.dumps([], ensure_ascii=False)

        # 2. 解析来自 Memory 模块的复杂 JSON 查询
        try:
            # 尝试将输入解析为 JSON 对象
            query_obj = json.loads(query_input)
            if isinstance(query_obj, dict):
                # 优先使用 'text' 字段作为查询
                query = query_obj.get('text', '')
                # 如果 'text' 为空，尝试使用中文关键词列表
                if not query and 'keywords_zh' in query_obj and query_obj['keywords_zh']:
                    query = ' '.join(query_obj['keywords_zh'])
                # 如果还是空，则退回使用原始输入
                if not query:
                    query = query_input
            else:
                # 如果是 JSON 但不是字典（例如列表），则按原样使用
                query = query_input
        except (json.JSONDecodeError, TypeError):
            # 如果输入不是有效的 JSON，则按原样使用它
            query = query_input
            
        # 3. 执行搜索
        search_results = self.searcher.search(query, max_ref_token=self.max_ref_token)

        # 4. 格式化并返回结果
        # 将结果格式化为 Agent 期望的 {'url': ..., 'text': ...} 格式
        formatted_results = [
            {
                'url': hit.get('_source', {}).get('source', 'N/A'),
                'text': [hit.get('_source', {}).get('content', '')]
            } for hit in search_results
        ]
        
        return json.dumps(formatted_results, ensure_ascii=False)

    def _format_error(self, error_message: str) -> str:
        return json.dumps([{'error': error_message}], ensure_ascii=False) 


# add by gq [2026-05-08：离线索引工具独立出来，便于问答和索引解耦]
@register_tool('es_indexer')
class ESIndexerTool(BaseTool):
    name = 'es_indexer'
    description = '将文件列表写入 Elasticsearch 索引，用于离线或增量索引。'
    parameters = [{
        'name': 'files',
        'type': 'list',
        'description': '需要写入 Elasticsearch 的文件列表',
        'required': True
    }]

    def __init__(self, cfg: dict = None):
        super().__init__(cfg)
        self.cfg = cfg or {}
        self.searcher = ElasticsearchSearcher(cfg=self.cfg)

    def call(self, params: dict, **kwargs) -> str:
        files = params.get('files', [])
        if not files or not isinstance(files, list):
            return json.dumps({'status': 'skipped', 'message': '未提供文件，无需索引。'}, ensure_ascii=False)
        self.searcher.index_files(files)
        state = self.searcher.index_state_summary()
        status = state.get('status', 'unknown')
        message = 'Elasticsearch 索引完成。' if status == 'indexed' else 'Elasticsearch 索引未完成，请查看日志。'
        return json.dumps({
            'status': status,
            'message': message,
            'doc_count': state.get('doc_count', len(files)),
            'index_name': state.get('index_name', self.searcher.index_name),
            'docs_signature': state.get('docs_signature', ''),
        }, ensure_ascii=False)
# add end
