# qwen_agent/searcher/elasticsearch_searcher.py
import os
import json
import hashlib
import logging
from pathlib import Path
from elasticsearch import Elasticsearch, helpers
from elasticsearch.exceptions import BadRequestError # 导入特定的异常
from openai import OpenAI
from qwen_agent.tools.doc_parser import DocParser
from qwen_agent.searcher.es_index_state import build_docs_signature, load_es_index_state, save_es_index_state

# 为此模块设置一个日志记录器
logger = logging.getLogger(__name__)

ES_INDEX_SCHEMA_VERSION = 'hybrid_bm25_vector_v1'


class ElasticsearchSearcher:
    """一个使用 Elasticsearch 进行文档索引和搜索的搜索器。"""

    def __init__(self, cfg):
        self.cfg = cfg
        es_cfg = cfg.get('es', {})
        self.host = es_cfg.get('host', 'http://localhost')
        self.port = es_cfg.get('port', 9200)
        self.user = es_cfg.get('user')
        self.password = es_cfg.get('password')
        self.index_name = es_cfg.get('index_name', 'qwen_agent_rag_idx')
        self.index_state = load_es_index_state()
        embedding_cfg = cfg.get('embedding', {})
        self.embedding_enabled = embedding_cfg.get('enabled', False)
        self.embedding_model = embedding_cfg.get('model', 'text-embedding-v3')
        self.embedding_api_key = embedding_cfg.get('api_key')
        self.embedding_base_url = embedding_cfg.get('base_url')
        self.embedding_batch_size = int(embedding_cfg.get('batch_size', 8))
        self.embedding_max_chars = int(embedding_cfg.get('max_chars', 6000))
        self.vector_field = embedding_cfg.get('vector_field', 'embedding')
        self.bm25_candidate_size = int(embedding_cfg.get('bm25_candidate_size', 100))
        self.vector_candidate_size = int(embedding_cfg.get('vector_candidate_size', 100))
        self.rrf_k = int(embedding_cfg.get('rrf_k', 60))
        self._embedding_client = None
        
        # DocParser 用于解析和分块文档
        self.parser = DocParser(cfg=self.cfg)
        
        self.client = self._connect()
        if self.client:
            logger.info("成功连接到 Elasticsearch！")
            self._create_index_if_not_exists()
        else:
            logger.error("连接 Elasticsearch 失败。请检查您的配置、网络和 ES 服务状态。")

    # add by gq [2026-05-08：收口 ES mapping，正文只保留 text 检索字段，避免长文本写入 content.keyword 失败]
    def _index_properties(self, use_ik: bool = False) -> dict:
        content_mapping = {"type": "text"}
        if use_ik:
            content_mapping.update({
                "analyzer": "ik_max_word",
                "search_analyzer": "ik_smart",
            })
        properties = {
            "content": content_mapping,
            "source": {"type": "keyword"},
            "chunk_id": {"type": "integer"},
            "token": {"type": "integer"},
        }
        if self.embedding_enabled:
            properties[self.vector_field] = {
                "type": "dense_vector",
                "index": True,
                "similarity": "cosine",
            }
        return properties

    def _index_schema_state(self) -> dict:
        return {
            'schema_version': ES_INDEX_SCHEMA_VERSION,
            'embedding_enabled': self.embedding_enabled,
            'embedding_model': self.embedding_model if self.embedding_enabled else '',
            'vector_field': self.vector_field if self.embedding_enabled else '',
        }

    def _index_state_matches(self, docs_signature: str) -> bool:
        return (
            self.index_state.get('docs_signature') == docs_signature
            and self.index_state.get('index_name') == self.index_name
            and self.index_state.get('schema_version') == ES_INDEX_SCHEMA_VERSION
            and bool(self.index_state.get('embedding_enabled')) == self.embedding_enabled
            and self.index_state.get('embedding_model', '') == (self.embedding_model if self.embedding_enabled else '')
            and self.index_state.get('vector_field', '') == (self.vector_field if self.embedding_enabled else '')
        )

    def _save_index_state(self, status: str, files: list, docs_signature: str, extra: dict | None = None) -> dict:
        state = {
            'status': status,
            'index_name': self.index_name,
            'docs_signature': docs_signature,
            'doc_files': [str(Path(file).resolve()) for file in files],
            'doc_count': len(files),
            **self._index_schema_state(),
        }
        if extra:
            state.update(extra)
        self.index_state = save_es_index_state(state)
        return self.index_state

    def _embedding_field_exists(self) -> bool:
        if not self.embedding_enabled or not self.client:
            return False
        try:
            mapping = self.client.indices.get_mapping(index=self.index_name).body
            properties = mapping.get(self.index_name, {}).get('mappings', {}).get('properties', {})
            return self.vector_field in properties
        except Exception as exc:
            logger.warning(f"检查 ES 向量字段失败：{exc}")
            return False

    def _ensure_vector_mapping(self):
        if not self.embedding_enabled or not self.client:
            return
        if self._embedding_field_exists():
            return
        try:
            self.client.indices.put_mapping(
                index=self.index_name,
                body={
                    "properties": {
                        self.vector_field: {
                            "type": "dense_vector",
                            "index": True,
                            "similarity": "cosine",
                        }
                    }
                },
            )
            logger.info(f"已为索引 '{self.index_name}' 补充向量字段 '{self.vector_field}'。")
        except Exception as exc:
            logger.error(f"补充 ES 向量字段失败，请考虑使用 --recreate 重建索引：{exc}")

    def _get_embedding_client(self) -> OpenAI | None:
        if not self.embedding_enabled:
            return None
        if self._embedding_client is not None:
            return self._embedding_client
        if not self.embedding_api_key or not self.embedding_base_url:
            logger.error("未配置 embedding.api_key 或 embedding.base_url，无法生成向量。")
            return None
        self._embedding_client = OpenAI(api_key=self.embedding_api_key, base_url=self.embedding_base_url)
        return self._embedding_client

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not self.embedding_enabled:
            return []
        client = self._get_embedding_client()
        if not client:
            return []
        embeddings = []
        for start in range(0, len(texts), self.embedding_batch_size):
            batch = [self._normalize_embedding_text(text) for text in texts[start:start + self.embedding_batch_size]]
            response = client.embeddings.create(model=self.embedding_model, input=batch)
            batch_vectors = [item.embedding for item in response.data]
            embeddings.extend(batch_vectors)
        return embeddings

    def _normalize_embedding_text(self, text: str) -> str:
        normalized = (text or '').strip()
        if not normalized:
            return '空白文档片段'
        if len(normalized) > self.embedding_max_chars:
            return normalized[:self.embedding_max_chars]
        return normalized

    def recreate_index(self):
        if not self.client:
            logger.error("Elasticsearch 客户端不可用，无法重建索引。")
            return
        if self.client.indices.exists(index=self.index_name):
            logger.warning(f"正在删除旧索引 '{self.index_name}'，随后按当前 mapping 重建。")
            self.client.indices.delete(index=self.index_name)
        self._create_index_if_not_exists()
        self.index_state = {}
    # add end

    def _connect(self) -> Elasticsearch:
        """建立并返回到 Elasticsearch 的连接。"""
        try:
            # 根据提供的配置构建连接参数
            es_args = {
                'hosts': [{
                    'host': self.host.replace('https://', '').replace('http://', ''),
                    'port': self.port,
                    'scheme': 'https' if 'https' in self.host else 'http',
                }],
                'verify_certs': False, # 在生产环境中应设为 True 并提供证书
                'request_timeout': 60,
            }
            if self.user and self.password:
                es_args['basic_auth'] = (self.user, self.password)

            client = Elasticsearch(**es_args)
            
            # 检查连接
            if not client.ping():
                raise ConnectionError("Elasticsearch ping 失败。")
            
            return client
        except Exception as e:
            logger.error(f"无法连接到 Elasticsearch：{e}")
            return None

    def _create_index_if_not_exists(self):
        """
        如果索引不存在，则创建它。
        优先尝试使用 IK 中文分词器，如果失败则回退到标准分词器。
        """
        try:
            if not self.client.indices.exists(index=self.index_name):
                logger.info(f"索引 '{self.index_name}' 不存在，正在创建...")
                
                # 优先尝试使用 IK 分词器的配置
                ik_index_settings = {
                    "settings": {
                        "number_of_replicas": 0,
                        "analysis": {"analyzer": {"default": {"type": "ik_max_word"}}},
                    },
                    "mappings": {"properties": self._index_properties(use_ik=True)}
                }
                
                try:
                    # 首次尝试使用 IK 创建
                    self.client.indices.create(index=self.index_name, body=ik_index_settings)
                    logger.info(f"成功使用 IK 分词器创建索引 '{self.index_name}'。")
                except BadRequestError as e:
                    # 捕获因分词器不存在导致的错误
                    if 'Unknown analyzer type [ik_max_word]' in str(e):
                        logger.warning("未能找到 'ik_max_word' 分词器。这通常是因为 Elasticsearch 未安装 IK 中文分词插件。")
                        logger.warning("将回退使用标准分词器。对于中文搜索，强烈建议安装 IK 插件以获得更好效果。")
                        
                        # 回退配置：使用标准分词器
                        standard_index_settings = {
                            "settings": {"number_of_replicas": 0},
                            "mappings": {"properties": self._index_properties(use_ik=False)}
                        }
                        # 再次尝试使用标准配置创建
                        self.client.indices.create(index=self.index_name, body=standard_index_settings)
                        logger.info(f"成功使用标准分词器创建索引 '{self.index_name}'。")
                    else:
                        # 如果是其他类型的请求错误，则重新引发异常
                        raise e
            else:
                logger.info(f"索引 '{self.index_name}' 已存在。")
        except Exception as e:
            logger.error(f"创建或检查索引 '{self.index_name}' 时发生严重错误: {e}")

    def index_files(self, files: list):
        """
        高效地索引文件列表。
        它首先获取所有文件的所有文本块，然后通过一次 mget 请求过滤掉已存在的块，
        最后通过一次 bulk 请求批量索引所有新块。
        """
        if not self.client:
            logger.error("Elasticsearch 客户端不可用，无法执行索引。")
            return
            
        logger.info(f"开始处理 {len(files)} 个文件以进行索引...")
        current_signature = build_docs_signature(files)
        if self._index_state_matches(current_signature):
            logger.info("文档签名未变化，跳过重复索引。")
            return
        self._ensure_vector_mapping()
        chunks = self._get_chunks(files)
        logger.info(f"从文件中总共提取了 {len(chunks)} 个内容块。")

        if not chunks:
            logger.warning("未能从文件中提取任何内容块，索引过程终止。")
            return

        # 高效地筛选出需要索引的新块
        new_chunks = self._filter_existing_chunks_efficiently(chunks)

        if new_chunks:
            logger.info(f'发现 {len(new_chunks)} 个新的文档块，开始向 Elasticsearch 批量索引...')
            chunk_vectors = []
            if self.embedding_enabled:
                try:
                    chunk_vectors = self._embed_texts([chunk.get('content', '') for chunk in new_chunks])
                except Exception as exc:
                    logger.error(f"生成文档向量失败：{exc}")
                    self._save_index_state('failed', files, current_signature, {'error': str(exc)})
                    return
                if len(chunk_vectors) != len(new_chunks):
                    error_message = f"向量数量不匹配：chunks={len(new_chunks)}, embeddings={len(chunk_vectors)}"
                    logger.error(error_message)
                    self._save_index_state('failed', files, current_signature, {'error': error_message})
                    return

            actions = []
            for index, chunk in enumerate(new_chunks):
                source = {
                    "content": chunk['content'],
                    "source": chunk['metadata']['source'],
                    "chunk_id": chunk['metadata'].get('chunk_id', 0),
                    "token": chunk.get('token', 0)
                }
                if self.embedding_enabled:
                    source[self.vector_field] = chunk_vectors[index]
                actions.append({
                    "_op_type": "index",
                    "_index": self.index_name,
                    "_id": chunk['id'],
                    "_source": source,
                })
            
            try:
                successes, errors = helpers.bulk(self.client, actions, refresh=True, raise_on_error=False)
                logger.info(f"成功索引 {successes} 个新文档块。")
                if errors:
                    logger.error(f"批量索引过程中发生 {len(errors)} 个错误。第一个错误详情: {errors[0]}")
                    self._save_index_state('failed', files, current_signature, {'error_count': len(errors)})
                    return
                self._save_index_state('indexed', files, current_signature)
            except helpers.BulkIndexError as e:
                logger.error(f"批量索引时发生严重错误: {len(e.errors)} 个文档索引失败。")
        else:
            logger.info("所有文件内容均已在 Elasticsearch 中建立索引，无需更新。")
            self._save_index_state('indexed', files, current_signature)

    def index_state_summary(self) -> dict:
        state = self.index_state if isinstance(self.index_state, dict) else {}
        return {
            'status': state.get('status', 'unknown'),
            'index_name': state.get('index_name', self.index_name),
            'doc_count': state.get('doc_count', 0),
            'docs_signature': state.get('docs_signature', ''),
            'doc_files': state.get('doc_files', []),
            'schema_version': state.get('schema_version', ''),
            'embedding_enabled': state.get('embedding_enabled', False),
            'embedding_model': state.get('embedding_model', ''),
            'vector_field': state.get('vector_field', ''),
        }

    def _get_chunks(self, files: list) -> list:
        """从文件列表中提取并返回所有文本块。"""
        all_chunks = []
        for file_path in files:
            try:
                # 1. 准备 JSON 字符串参数
                params_str = json.dumps({'url': file_path})

                # 2. 调用 DocParser，它会返回一个 JSON 字符串
                parsed_content_str = self.parser.call(
                    params=params_str,
                    use_cache=False  # 强制重新解析，忽略缓存
                )

                # 3. 解析返回的 JSON 字符串
                parsed_record = json.loads(parsed_content_str)
                
                # 检查解析后的记录是否出错
                if 'error' in parsed_record:
                    logger.error(f"解析文件 '{file_path}' 时返回错误: {parsed_record['error']}")
                    continue

                # 从记录中提取 'raw' 块
                chunks_data = parsed_record.get('raw', [])
                
                # 为每个块添加源文件信息
                for chunk in chunks_data:
                    if 'metadata' in chunk and 'source' not in chunk['metadata']:
                         chunk['metadata']['source'] = os.path.basename(file_path)
                    all_chunks.append(chunk)

            except Exception as e:
                logger.error(f"处理文件 '{file_path}' 时出错: {e}", exc_info=True)
        return all_chunks

    def _filter_existing_chunks_efficiently(self, chunks: list) -> list:
        """
        使用 mget 高效地从块列表中筛选出尚未在ES中索引的块。
        """
        if not chunks:
            return []

        # 1. 为所有块生成 ID
        for chunk in chunks:
            chunk_content = chunk.get('content', '')
            chunk_source = chunk.get('source', 'unknown')
            sha256 = hashlib.sha256()
            sha256.update(chunk_content.encode('utf-8'))
            sha256.update(chunk_source.encode('utf-8'))
            chunk['id'] = sha256.hexdigest()

        doc_ids = [chunk['id'] for chunk in chunks]
        
        # 2. 使用 mget 一次性检查所有 ID 是否存在
        try:
            response = self.client.mget(index=self.index_name, body={'ids': doc_ids})
            existing_ids = set()
            for doc in response['docs']:
                if not doc['found']:
                    continue
                if self.embedding_enabled and not doc.get('_source', {}).get(self.vector_field):
                    continue
                existing_ids.add(doc['_id'])
            logger.info(f"在 Elasticsearch 中发现 {len(existing_ids)} 个已存在的文档块。")
        except Exception as e:
            logger.error(f"使用 mget 检查文档是否存在时出错: {e}。将假定所有块都是新的。")
            existing_ids = set()

        # 3. 筛选出新块
        new_chunks = [chunk for chunk in chunks if chunk['id'] not in existing_ids]
        logger.info(f"筛选出 {len(new_chunks)} 个新块需要索引。")
        return new_chunks

    def _bm25_search(self, query: str) -> list:
        search_body = {
            "query": {
                "bool": {
                    "should": [
                        {"match": {"content": {"query": query, "boost": 2}}},
                        {"match_phrase": {"content": {"query": query, "boost": 3}}},
                    ],
                    "minimum_should_match": 1,
                }
            },
            "size": self.bm25_candidate_size,
        }
        response = self.client.search(index=self.index_name, body=search_body)
        return response['hits']['hits']

    def _vector_search(self, query: str) -> list:
        if not self.embedding_enabled:
            return []
        try:
            query_vector = self._embed_texts([query])[0]
        except Exception as exc:
            logger.error(f"生成查询向量失败，将退回 BM25 检索：{exc}")
            return []
        search_body = {
            "knn": {
                "field": self.vector_field,
                "query_vector": query_vector,
                "k": self.vector_candidate_size,
                "num_candidates": max(self.vector_candidate_size * 3, 100),
            },
            "size": self.vector_candidate_size,
        }
        try:
            response = self.client.search(index=self.index_name, body=search_body)
            return response['hits']['hits']
        except Exception as exc:
            logger.error(f"ES 向量检索失败，将只使用 BM25 结果：{exc}")
            return []

    def _rrf_rerank(self, ranked_lists: list[list[dict]]) -> list:
        merged = {}
        for hits in ranked_lists:
            for rank, hit in enumerate(hits, start=1):
                doc_id = hit.get('_id')
                if not doc_id:
                    continue
                item = merged.setdefault(doc_id, {'hit': hit, 'score': 0.0})
                item['score'] += 1.0 / (self.rrf_k + rank)
                if hit.get('_score', 0) > item['hit'].get('_score', 0):
                    item['hit'] = hit
        reranked = sorted(merged.values(), key=lambda item: item['score'], reverse=True)
        for item in reranked:
            item['hit']['_rrf_score'] = item['score']
        return [item['hit'] for item in reranked]

    def search(self, query: str, max_ref_token: int) -> list:
        """
        在 Elasticsearch 中执行搜索，并根据 max_ref_token 限制返回结果。
        """
        if not self.client:
            logger.error("Elasticsearch 客户端不可用，无法执行搜索。")
            return []
        
        logger.info(f"正在使用查询语句在 Elasticsearch 中搜索: '{query}'")
        
        try:
            # modified by gq [2026-05-08：增加 text-embedding-v3 向量召回，并使用 RRF 融合重排 BM25 与向量结果]
            bm25_hits = self._bm25_search(query)
            vector_hits = self._vector_search(query)
            hits = self._rrf_rerank([bm25_hits, vector_hits]) if vector_hits else bm25_hits
            # mod end
            
            # 根据 max_ref_token 筛选结果
            selected_hits = []
            total_tokens = 0
            for hit in hits:
                token_count = hit['_source'].get('token', 1000) # 从 _source 中获取 token，如不存在则估算一个较大值
                if total_tokens + token_count > max_ref_token:
                    logger.info(f'已达到 max_ref_token ({max_ref_token}) 的上限，停止添加更多结果。')
                    break
                selected_hits.append(hit)
                total_tokens += token_count
            
            logger.info(f"搜索完成，从 {len(hits)} 个候选中筛选出 {len(selected_hits)} 个结果 (总计 an approximately {total_tokens} tokens)。")
            return selected_hits
            
        except Exception as e:
            logger.error(f"Elasticsearch 搜索失败: {e}")
            return []
