import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from qwen_agent.searcher.elasticsearch_searcher import ElasticsearchSearcher
from qwen_agent.tools.retrieval import Retrieval
from qwen_agent_multi_files_config import load_doc_files, rag_cfg


# add by gq [2026-05-08：建立检索评测脚本，用固定问题集比较默认检索、ES BM25、ES 向量和融合重排效果]
DEFAULT_EVAL_FILE = PROJECT_ROOT / 'eval' / 'eval_questions.jsonl'
DEFAULT_OUTPUT_FILE = PROJECT_ROOT / 'workspace' / 'eval_retrieval_results.json'


def load_eval_cases(eval_file: Path) -> list[dict]:
    cases = []
    with eval_file.open('r', encoding='utf-8') as file:
        for line_no, line in enumerate(file, start=1):
            line = line.strip()
            if not line:
                continue
            case = json.loads(line)
            case.setdefault('id', f'case_{line_no}')
            cases.append(case)
    return cases


def normalize_expected_sources(expected_source) -> list[str]:
    if isinstance(expected_source, str):
        return [expected_source]
    if isinstance(expected_source, list):
        return [str(item) for item in expected_source]
    return []


def source_matches(source: str, expected_sources: list[str]) -> bool:
    source_name = Path(source or '').name
    return any(expected in source or expected in source_name for expected in expected_sources)


def limit_hits_by_token(hits: list[dict], max_ref_token: int) -> list[dict]:
    selected_hits = []
    total_tokens = 0
    for hit in hits:
        token_count = hit.get('_source', {}).get('token', 1000)
        if total_tokens + token_count > max_ref_token:
            break
        selected_hits.append(hit)
        total_tokens += token_count
    return selected_hits


def es_hits_to_sources(hits: list[dict]) -> list[str]:
    return [hit.get('_source', {}).get('source', '') for hit in hits]


def default_retrieval_sources(query: str, files: list[str], max_ref_token: int) -> list[str]:
    retrieval = Retrieval({
        'max_ref_token': max_ref_token,
        'parser_page_size': rag_cfg.get('parser_page_size', 500),
        'rag_searchers': ['keyword_search'],
    })
    results = retrieval.call({'query': query, 'files': files})
    return [item.get('url', '') for item in results if item.get('url')]


def run_mode(mode: str, query: str, searcher: ElasticsearchSearcher, files: list[str], max_ref_token: int) -> list[str]:
    if mode == 'qwen_default':
        return default_retrieval_sources(query, files, max_ref_token)
    if mode == 'es_bm25':
        return es_hits_to_sources(limit_hits_by_token(searcher._bm25_search(query), max_ref_token))
    if mode == 'es_vector':
        return es_hits_to_sources(limit_hits_by_token(searcher._vector_search(query), max_ref_token))
    if mode == 'es_hybrid':
        return es_hits_to_sources(searcher.search(query, max_ref_token=max_ref_token))
    raise ValueError(f'未知评测模式：{mode}')


def evaluate_cases(cases: list[dict], modes: list[str], top_k: int, max_ref_token: int) -> dict:
    files = load_doc_files()
    searcher = ElasticsearchSearcher(rag_cfg)
    mode_results = {mode: [] for mode in modes}

    for case in cases:
        expected_sources = normalize_expected_sources(case.get('expected_source'))
        for mode in modes:
            sources = run_mode(mode, case['question'], searcher, files, max_ref_token)
            top_sources = sources[:top_k]
            hit_rank = 0
            for rank, source in enumerate(top_sources, start=1):
                if source_matches(source, expected_sources):
                    hit_rank = rank
                    break
            mode_results[mode].append({
                'id': case['id'],
                'question': case['question'],
                'expected_source': expected_sources,
                'hit': bool(hit_rank),
                'hit_rank': hit_rank,
                'top_sources': top_sources,
            })

    summary = {}
    total = len(cases)
    for mode, rows in mode_results.items():
        hit_count = sum(1 for row in rows if row['hit'])
        reciprocal_rank_sum = sum((1 / row['hit_rank']) for row in rows if row['hit_rank'])
        summary[mode] = {
            'total': total,
            f'hit@{top_k}': hit_count / total if total else 0,
            'hit_count': hit_count,
            'mrr': reciprocal_rank_sum / total if total else 0,
        }
    return {'summary': summary, 'details': mode_results}


def print_summary(result: dict, top_k: int):
    print(f'评测指标：Hit@{top_k} / MRR')
    for mode, metrics in result['summary'].items():
        print(
            f"- {mode}: Hit@{top_k}={metrics[f'hit@{top_k}']:.2%} "
            f"({metrics['hit_count']}/{metrics['total']}), MRR={metrics['mrr']:.4f}"
        )


def main():
    parser = argparse.ArgumentParser(description='评测本项目检索召回是否命中预期文档来源')
    parser.add_argument('--eval-file', default=str(DEFAULT_EVAL_FILE), help='JSONL 评测集路径')
    parser.add_argument('--output', default=str(DEFAULT_OUTPUT_FILE), help='评测结果 JSON 输出路径')
    parser.add_argument('--top-k', type=int, default=3, help='只看前 K 个召回来源是否命中')
    parser.add_argument('--max-ref-token', type=int, default=rag_cfg.get('max_ref_token', 20000))
    parser.add_argument(
        '--modes',
        nargs='+',
        default=['es_bm25', 'es_vector', 'es_hybrid'],
        choices=['qwen_default', 'es_bm25', 'es_vector', 'es_hybrid'],
        help='要比较的检索模式',
    )
    args = parser.parse_args()

    cases = load_eval_cases(Path(args.eval_file))
    result = evaluate_cases(cases, args.modes, args.top_k, args.max_ref_token)
    print_summary(result, args.top_k)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'详细结果已写入：{output_path}')


if __name__ == '__main__':
    main()
# add end
