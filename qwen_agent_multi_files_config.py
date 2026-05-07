import os
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

import json5
from dotenv import load_dotenv
from qwen_agent.tools.base import BaseTool, register_tool


# modified by gq [2026-05-06：从项目根目录加载 .env，与脚本同目录]
PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")
# mod end


# add by gq [2026-05-06：将 AGICTO 文档中的 Base URL 规范为 OpenAI SDK 所需地址（含 /v1），参见 https://docs.agicto.com/]
def agicto_openai_base_url() -> str:
    # 与 AGICTO「调用前你需要知道」中的 Base URL 对齐；未带 /v1 时自动拼接
    raw = (os.getenv('AGICTO_BASE_URL') or '').strip().rstrip('/')
    if not raw:
        raise ValueError(
            '请在 .env 中配置 AGICTO_BASE_URL，例如：https://api.agicto.cn（见 AGICTO 文档「调用前你需要知道」）'
        )
    if raw.endswith('/v1'):
        return raw
    return f'{raw}/v1'
# add end


# 步骤 1（可选）：添加一个名为 `my_image_gen` 的自定义工具。
@register_tool('my_image_gen')
class MyImageGen(BaseTool):
    # `description` 用于告诉智能体该工具的功能。
    description = 'AI 绘画（图像生成）服务，输入文本描述，返回基于文本信息绘制的图像 URL。'
    # `parameters` 告诉智能体该工具有哪些输入参数。
    parameters = [{
        'name': 'prompt',
        'type': 'string',
        'description': '期望的图像内容的详细描述',
        'required': True
    }]

    def call(self, params: str, **kwargs) -> str:
        # `params` 是由 LLM 智能体生成的参数。
        prompt = json5.loads(params)['prompt']
        prompt = urllib.parse.quote(prompt)
        return json5.dumps(
            {'image_url': f'https://image.pollinations.ai/prompt/{prompt}'},
            ensure_ascii=False)


# del by gq [2026-05-06：改为 AGICTO 网关，不再使用 DashScope 直连与兼容模式重复配置]
# # 步骤 2（旧）：配置您所使用的 LLM。
# llm_cfg = {
#     'model': 'qwen-max',
#     'model_server': 'dashscope',
#     'api_key': os.getenv('DASHSCOPE_API_KEY'),
#     'generate_cfg': {
#         'top_p': 0.8
#     }
# }
#
# llm_cfg = {
#     'model': 'deepseek-v3',
#     'model_server': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
#     'api_key': os.getenv('DASHSCOPE_API_KEY'),
#     'generate_cfg': {
#         'top_p': 0.8
#     }
# }
# del end

# add by gq [2026-05-06：步骤 2 改为 AGICTO OpenAI 兼容接入，密钥与 Base URL 来自 .env]
_agicto_key = (os.getenv('AGICTO_API_KEY') or '').strip()
if not _agicto_key:
    raise ValueError('请在 .env 中配置 AGICTO_API_KEY（AGICTO 控制台发放的 API Key）')
# add end

# modified by gq [2026-05-06：与 AGICTO OpenAI 示例一致：base_url 为 https://api.agicto.cn/v1，模型 deepseek-v4-flash]
llm_cfg = {
    # 等价于：OpenAI(api_key=..., base_url="https://api.agicto.cn/v1").chat.completions.create(model="deepseek-v4-flash", ...)
    'model': (os.getenv('AGICTO_MODEL') or 'deepseek-v4-flash').strip(),
    'model_server': agicto_openai_base_url(),
    'api_key': _agicto_key,
    'generate_cfg': {
        'top_p': 0.8
    }
}
# mod end


# 步骤 3：创建一个智能体。这里我们以 `Assistant` 智能体为例，它能够读取文件并回答问题。
# modified by gq [2026-05-07：文档问答默认不启用工具调用；Tavily MCP 仅在显式配置后加入工具列表]
system_instruction = '''你是一个乐于助人的AI文档问答助手。
请优先根据给定文档回答用户问题；如果文档中没有相关信息，请明确说明未在文档中找到依据。
如果启用了 Tavily MCP，且用户明确要求联网搜索、查询最新信息或文档中没有相关依据时，可以使用 Tavily 工具补充检索。
你总是用中文回复用户。'''


def _truthy_env(name: str) -> bool:
    return (os.getenv(name) or '').strip().lower() in ('1', 'true', 'yes', 'on')


def _resolve_tavily_mcp_command() -> str:
    configured = (os.getenv('TAVILY_MCP_COMMAND') or '').strip()
    if configured:
        return configured
    return shutil.which('npx') or shutil.which('npx.cmd') or 'npx'


def _tavily_mcp_tool_config() -> dict | None:
    if not _truthy_env('ENABLE_TAVILY_MCP'):
        return None
    tavily_key = (os.getenv('TAVILY_API_KEY') or '').strip()
    if not tavily_key:
        raise ValueError('已启用 ENABLE_TAVILY_MCP，但未在 .env 中配置 TAVILY_API_KEY')
    return {
        'mcpServers': {
            'tavily-mcp': {
                'command': _resolve_tavily_mcp_command(),
                'args': ['-y', 'tavily-mcp@0.1.3'],
                'env': {
                    'TAVILY_API_KEY': tavily_key,
                },
            },
        },
    }


# add by gq [2026-05-08：给 GUI 和调试日志提供 Tavily MCP 启用状态]
def tavily_mcp_info() -> dict:
    enabled = _truthy_env('ENABLE_TAVILY_MCP')
    has_key = bool((os.getenv('TAVILY_API_KEY') or '').strip())
    return {
        'enabled': enabled,
        'has_key': has_key,
        'backend': 'Tavily MCP',
        'badge': 'WEB',
        'mode': 'ENABLE_TAVILY_MCP=true' if enabled else 'ENABLE_TAVILY_MCP=false',
        'command': _resolve_tavily_mcp_command() if enabled else '-',
        'package': 'tavily-mcp@0.1.3',
    }
# add end


tools = []
_tavily_mcp_cfg = _tavily_mcp_tool_config()
if _tavily_mcp_cfg:
    tools.append(_tavily_mcp_cfg)
# mod end


# modified by gq [2026-05-07：集中管理文档加载与 RAG 配置，避免主入口混入配置细节]
def load_doc_files() -> list[str]:
    file_dir = PROJECT_ROOT / 'docs'
    files = []
    if file_dir.exists():
        for file_path in file_dir.iterdir():
            if file_path.is_file():
                files.append(str(file_path))
    return files


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


def rag_backend_label() -> str:
    if rag_cfg.get('rag_backend') == 'elasticsearch':
        es_cfg = rag_cfg.get('es', {})
        return f"Elasticsearch ({es_cfg.get('host')}:{es_cfg.get('port')}/{es_cfg.get('index_name')})"
    return '默认内存检索'


# add by gq [2026-05-07：为 GUI 提供结构化检索后端信息，方便直观看到 ES 配置]
def rag_backend_info() -> dict:
    if rag_cfg.get('rag_backend') == 'elasticsearch':
        es_cfg = rag_cfg.get('es', {})
        host = es_cfg.get('host', 'http://localhost')
        port = es_cfg.get('port', 9200)
        index_name = es_cfg.get('index_name', 'qwen_agent_rag_idx')
        return {
            'backend': 'Elasticsearch',
            'badge': 'ES',
            'address': f'{host}:{port}',
            'index_name': index_name,
            'mode': 'rag_cfg.rag_backend = elasticsearch',
            'label': rag_backend_label(),
        }
    return {
        'backend': '默认内存检索',
        'badge': 'MEM',
        'address': '本地内存',
        'index_name': '-',
        'mode': 'rag_cfg.rag_backend = default',
        'label': rag_backend_label(),
    }
# add end


def es_debug_status() -> list[str]:
    es_cfg = rag_cfg.get('es', {})
    host = es_cfg.get('host', 'http://localhost')
    port = es_cfg.get('port', 9200)
    index_name = es_cfg.get('index_name', 'qwen_agent_rag_idx')
    base_url = f'{host}:{port}'
    messages = [
        f'检索后端：Elasticsearch',
        f'ES 地址：{base_url}',
        f'ES 索引：{index_name}',
    ]
    try:
        with urllib.request.urlopen(f'{base_url}/_cluster/health', timeout=3) as response:
            health = json5.loads(response.read().decode('utf-8'))
        messages.append(f"ES 集群状态：{health.get('status', 'unknown')}")
    except Exception as exc:
        messages.append(f'ES 集群状态获取失败：{exc}')
        return messages

    try:
        with urllib.request.urlopen(f'{base_url}/{index_name}/_count', timeout=3) as response:
            count = json5.loads(response.read().decode('utf-8'))
        messages.append(f"ES 当前索引文档块数：{count.get('count', 0)}")
    except Exception:
        messages.append('ES 当前索引文档块数：索引尚未创建，将在首次检索时创建')
    return messages
# mod end
