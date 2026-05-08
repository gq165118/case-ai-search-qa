import hashlib
import json
from pathlib import Path
from typing import Iterable

from qwen_agent.settings import DEFAULT_WORKSPACE


# add by gq [2026-05-08：为 ES 离线索引维护本地状态文件，便于 GUI 展示和增量判断]
def es_index_state_path() -> Path:
    path = Path(DEFAULT_WORKSPACE) / 'es_index_state.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _normalized_file_list(files: Iterable[str]) -> list[str]:
    unique_files = []
    seen = set()
    for file_path in files:
        if not file_path:
            continue
        normalized = str(Path(file_path).resolve())
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_files.append(normalized)
    return sorted(unique_files)


def build_docs_signature(files: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for file_path in _normalized_file_list(files):
        path = Path(file_path)
        if not path.exists():
            digest.update(f'{file_path}|missing'.encode('utf-8'))
            continue
        stat = path.stat()
        digest.update(f'{file_path}|{stat.st_size}|{int(stat.st_mtime_ns)}'.encode('utf-8'))
    return digest.hexdigest()


def load_es_index_state() -> dict:
    path = es_index_state_path()
    if not path.exists():
        return {}
    try:
        state = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}
    return state if isinstance(state, dict) else {}


def save_es_index_state(state: dict) -> dict:
    payload = dict(state or {})
    payload.setdefault('status', 'indexed')
    path = es_index_state_path()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload
# add end
