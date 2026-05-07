#从主脚本抽离 Agent 初始化、检索和问答事件流，保持入口脚本清爽]
from qwen_agent.agents.assistant import Assistant, format_knowledge_to_source_and_content

from qwen_agent_multi_files_config import (
    es_debug_status,
    llm_cfg,
    load_doc_files,
    rag_cfg,
    system_instruction,
    tavily_mcp_info,
    tools,
)


# modified by gq [2026-05-06：封装文档加载与智能体初始化，供终端模式和 GUI 模式复用]
def init_agent_service() -> Assistant:
    files = load_doc_files()
    print('files=', files)

    # return Assistant(llm=llm_cfg,
    #                  system_message=system_instruction,
    #                  function_list=tools,
    #                  files=files)
    return Assistant(llm=llm_cfg,
                     system_message=system_instruction,
                     function_list=tools,
                     files=files,
                     rag_cfg=rag_cfg)
# mod end


# add by gq [2026-05-06：兼容 reasoning_content 与多消息返回，提取真正的助手正文]
def assistant_answer_text(response_messages) -> str:
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


# add by gq [2026-05-08：识别 Tavily MCP 工具调用，便于 GUI 展示是否发生联网搜索]
def _message_function_name(message) -> str:
    function_call = message.get('function_call') if isinstance(message, dict) else getattr(message, 'function_call', None)
    if not function_call:
        return ''
    if isinstance(function_call, dict):
        return function_call.get('name', '') or ''
    return getattr(function_call, 'name', '') or ''


def _message_role_name(message) -> tuple[str, str]:
    if isinstance(message, dict):
        return message.get('role', '') or '', message.get('name', '') or ''
    return getattr(message, 'role', '') or '', getattr(message, 'name', '') or ''


def _is_tavily_tool_name(tool_name: str) -> bool:
    return 'tavily' in (tool_name or '').lower()


def _tavily_tool_events(response_messages, seen_tool_calls: set[str], seen_tool_results: set[str]) -> list[dict]:
    events = []
    for message in response_messages:
        function_name = _message_function_name(message)
        if _is_tavily_tool_name(function_name) and function_name not in seen_tool_calls:
            seen_tool_calls.add(function_name)
            events.append({'type': 'web_search', 'status': 'called', 'tool': function_name})

        role, name = _message_role_name(message)
        if role == 'function' and _is_tavily_tool_name(name) and name not in seen_tool_results:
            seen_tool_results.add(name)
            events.append({'type': 'web_search', 'status': 'completed', 'tool': name})
    return events
# add end


# add by gq [2026-05-07：将检索结果同时用于参考展示和答案生成，避免重复检索]
def retrieve_reference_docs(bot: Assistant, messages: list[dict]) -> tuple[str, list[dict]]:
    last = None
    for last in bot.mem.run(messages=messages, lang='zh'):
        pass
    if not last:
        return '', []
    knowledge = last[-1]['content'] if isinstance(last[-1], dict) else last[-1].content
    if not knowledge:
        return '', []
    refs = []
    for item in format_knowledge_to_source_and_content(knowledge):
        refs.append({
            'source': item.get('source', '未知文档'),
            'content': item.get('content', ''),
        })
    return knowledge, refs
# add end


# add by gq [2026-05-06：统一生成调试日志、参考文档和流式答案事件]
def run_qa_events(bot: Assistant, query: str, history: list[dict]):
    messages = []
    for message in history:
        if message.get('role') in ('user', 'assistant') and message.get('content'):
            messages.append({'role': message['role'], 'content': message['content']})
    messages.append({'role': 'user', 'content': query.strip()})

    yield {'type': 'log', 'message': '收到问题，开始准备检索。'}
    yield {'type': 'log', 'message': f'当前知识库文件数：{len(load_doc_files())}'}
    tavily_info = tavily_mcp_info()
    if tavily_info['enabled']:
        yield {'type': 'web_search', 'status': 'enabled', 'tool': 'Tavily MCP'}
        yield {'type': 'log', 'message': '联网搜索：Tavily MCP 已启用，模型仅在需要时调用。'}
    else:
        yield {'type': 'web_search', 'status': 'disabled', 'tool': 'Tavily MCP'}
        yield {'type': 'log', 'message': '联网搜索：未启用 Tavily MCP，本轮只使用本地文档检索。'}
    if rag_cfg.get('rag_backend') == 'elasticsearch':
        for message in es_debug_status():
            yield {'type': 'log', 'message': message}
    try:
        knowledge, refs = retrieve_reference_docs(bot, messages)
        yield {'type': 'refs', 'items': refs}
        if refs:
            ref_names = '、'.join(ref['source'] for ref in refs)
            yield {'type': 'log', 'message': f'检索完成，参考文档：{ref_names}'}
        else:
            yield {'type': 'log', 'message': '检索完成，但未找到明显相关片段。'}

        yield {'type': 'log', 'message': '开始调用模型生成回答。'}
        printed_answer = ''
        seen_tool_calls = set()
        seen_tool_results = set()
        for response in bot.run(messages=messages, knowledge=knowledge, lang='zh'):
            for event in _tavily_tool_events(response, seen_tool_calls, seen_tool_results):
                yield event
            answer_text = assistant_answer_text(response)
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


# add by gq [2026-05-07：抽离终端演示流程，主入口只负责模式分发]
def run_tui_demo():
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

        answer_text = assistant_answer_text(response)
        if answer_text.startswith(printed_answer):
            current_response = answer_text[len(printed_answer):]
        else:
            current_response = answer_text
        if current_response:
            print(current_response, end='')
            printed_answer = answer_text
