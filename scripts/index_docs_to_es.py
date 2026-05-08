import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from qwen_agent_multi_files_config import load_doc_files, rag_cfg
from qwen_agent.tools.es_retrieval import ESIndexerTool


# add by gq [2026-05-08：提供独立的离线 ES 索引入口，避免问答过程重复扫描 docs]
def main():
    parser = argparse.ArgumentParser(description='将 docs 目录中的文件离线索引到 Elasticsearch')
    parser.add_argument('--dry-run', action='store_true', help='只打印待索引文件，不实际写入 ES')
    parser.add_argument('--recreate', action='store_true', help='先删除再重建 ES 索引，适合 mapping 调整后全量重建')
    args = parser.parse_args()

    files = load_doc_files()
    print(f'待索引文件数：{len(files)}')
    for file_path in files:
        print(f'- {file_path}')

    if args.dry_run:
        print('dry-run 模式，未执行 ES 写入。')
        return

    indexer = ESIndexerTool(cfg=rag_cfg)
    if args.recreate and hasattr(indexer.searcher, 'recreate_index'):
        print('检测到 --recreate，先删除旧索引并按当前 mapping 重建。')
        indexer.searcher.recreate_index()
    result = indexer.call({'files': files})
    print(result)


if __name__ == '__main__':
    main()
# add end
