import os
import logging
import argparse
import urllib.parse
from pathlib import Path

import json5
from dotenv import load_dotenv
from qwen_agent.agents.assistant import Assistant, format_knowledge_to_source_and_content
from qwen_agent.tools.base import BaseTool, register_tool
from qwen_agent_multi_files_gui import run_web_app  # add by gq [2026-05-07: move GUI display layer to a separate module]

logging.disable(logging.INFO)  # add by gq [2026-05-06：减少 Qwen Agent INFO 日志干扰，终端主要显示最终问答结果]

# modified by gq [2026-05-06：从项目根目录加载 .env，与脚本同目录]
_PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(_PROJECT_ROOT / ".env")
# mod end


# add by gq [2026-05-06：将 AGICTO 文档中的 Base URL 规范为 OpenAI SDK 所需地址（含 /v1），参见 https://docs.agicto.com/]
def _agicto_openai_base_url() -> str:
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
    'model_server': _agicto_openai_base_url(),
    'api_key': _agicto_key,
    'generate_cfg': {
        'top_p': 0.8
    }
}
# mod end

# 步骤 3：创建一个智能体。这里我们以 `Assistant` 智能体为例，它能够读取文件并回答问题。
# modified by gq [2026-05-06：文档问答 demo 不启用工具调用，避免兼容模型只返回工具流程不输出正文]
system_instruction = '''你是一个乐于助人的AI文档问答助手。
请优先根据给定文档回答用户问题；如果文档中没有相关信息，请明确说明未在文档中找到依据。
你总是用中文回复用户。'''
tools = []
# mod end
# modified by gq [2026-05-06：封装文档加载与智能体初始化，供终端模式和 GUI 模式复用]
def _load_doc_files() -> list[str]:
    file_dir = _PROJECT_ROOT / 'docs'
    files = []
    if file_dir.exists():
        for file_path in file_dir.iterdir():
            if file_path.is_file():
                files.append(str(file_path))
    return files


def init_agent_service() -> Assistant:
    files = _load_doc_files()
    print('files=', files)
    return Assistant(llm=llm_cfg,
                     system_message=system_instruction,
                     function_list=tools,
                     files=files)
# mod end


# add by gq [2026-05-06：兼容 reasoning_content 与多消息返回，提取真正的助手正文]
def _assistant_answer_text(response_messages) -> str:
    contents = []
    for message in response_messages:
        if isinstance(message, dict):
            content = message.get('content')
        else:
            content = getattr(message, 'content', None)
        if content:
            contents.append(content)
    return '\n\n'.join(contents)
# add end


# add by gq [2026-05-06：提取 RAG 参考文档，供 GUI 调试面板展示]
def _retrieve_reference_docs(bot: Assistant, messages: list[dict]) -> list[dict]:
    last = None
    for last in bot.mem.run(messages=messages, lang='zh'):
        pass
    if not last:
        return []
    knowledge = last[-1]['content'] if isinstance(last[-1], dict) else last[-1].content
    if not knowledge:
        return []
    refs = []
    for item in format_knowledge_to_source_and_content(knowledge):
        refs.append({
            'source': item.get('source', '未知文档'),
            'content': item.get('content', ''),
        })
    return refs
# add end


# add by gq [2026-05-06：统一生成调试日志、参考文档和流式答案事件]
def _run_qa_events(bot: Assistant, query: str, history: list[dict]):
    messages = []
    for message in history:
        if message.get('role') in ('user', 'assistant') and message.get('content'):
            messages.append({'role': message['role'], 'content': message['content']})
    messages.append({'role': 'user', 'content': query.strip()})

    yield {'type': 'log', 'message': '收到问题，开始准备检索。'}
    yield {'type': 'log', 'message': f'当前知识库文件数：{len(_load_doc_files())}'}
    try:
        refs = _retrieve_reference_docs(bot, messages)
        yield {'type': 'refs', 'items': refs}
        if refs:
            ref_names = '、'.join(ref['source'] for ref in refs)
            yield {'type': 'log', 'message': f'检索完成，参考文档：{ref_names}'}
        else:
            yield {'type': 'log', 'message': '检索完成，但未找到明显相关片段。'}

        yield {'type': 'log', 'message': '开始调用模型生成回答。'}
        printed_answer = ''
        for response in bot.run(messages=messages):
            answer_text = _assistant_answer_text(response)
            if answer_text and answer_text != printed_answer:
                printed_answer = answer_text
                yield {'type': 'answer', 'content': printed_answer}
        if not printed_answer:
            yield {'type': 'answer', 'content': '没有生成有效回答。'}
        yield {'type': 'log', 'message': '回答生成完成。'}
        yield {'type': 'done'}
    except Exception as exc:
        yield {'type': 'log', 'message': f'处理失败：{exc}'}
        yield {'type': 'answer', 'content': f'处理失败：{exc}'}
        yield {'type': 'done'}
# add end


# modified by gq [2026-05-06：增加 GUI 模式，同时保留终端演示模式]
def app_tui():
    """终端模式，运行一次文档问答示例。"""
    bot = init_agent_service()
    messages = []  # 这里储存聊天历史。
    query = "介绍下雇主责任险"
    messages.append({'role': 'user', 'content': query})
    printed_answer = ''
    retrieval_checked = False
    for response in bot.run(messages=messages):
        if not retrieval_checked:
            # 尝试获取并打印召回的文档内容
            if hasattr(bot, 'retriever') and bot.retriever:
                print("\n===== 召回的文档内容 =====")
                retrieved_docs = bot.retriever.retrieve(query)
                if retrieved_docs:
                    for i, doc in enumerate(retrieved_docs):
                        print(f"\n文档片段 {i+1}:")
                        print(f"内容: {doc.page_content}")
                        print(f"元数据: {doc.metadata}")
                else:
                    print("没有召回任何文档内容")
                print("===========================\n")
            retrieval_checked = True

        answer_text = _assistant_answer_text(response)
        if answer_text.startswith(printed_answer):
            current_response = answer_text[len(printed_answer):]
        else:
            current_response = answer_text
        if current_response:
            print(current_response, end='')
            printed_answer = answer_text


def app_gui():
    """Start the Web UI while keeping AI QA logic in this script."""
    bot = init_agent_service()

    def event_factory(query: str, history: list[dict]):
        return _run_qa_events(bot, query, history)

    run_web_app(event_factory, doc_count=len(_load_doc_files()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Qwen Agent 多文件文档问答 demo')
    parser.add_argument('--tui', action='store_true', help='使用终端模式运行一次示例问答')
    args = parser.parse_args()
    if args.tui:
        app_tui()
    else:
        app_gui()
# mod end
