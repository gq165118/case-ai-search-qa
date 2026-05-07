import argparse
import logging

from qwen_agent_multi_files_config import load_doc_files, rag_backend_info, rag_backend_label, tavily_mcp_info
from qwen_agent_multi_files_gui import run_web_app  # add by gq [2026-05-07: move GUI display layer to a separate module]
from qwen_agent_multi_files_service import init_agent_service, run_qa_events, run_tui_demo


logging.disable(logging.INFO)  # add by gq [2026-05-06：减少 Qwen Agent INFO 日志干扰，终端主要显示最终问答结果]


# modified by gq [2026-05-07：主脚本瘦身为启动入口，配置与问答服务拆到独立模块]
def app_tui():
    run_tui_demo()


def app_gui():
    """Start the Web UI while keeping AI QA logic in the service module."""
    local_bot = init_agent_service(enable_tavily=False)
    web_bot = None

    # modified by gq [2026-05-08：由 GUI 本轮开关选择是否使用带 Tavily MCP 工具的 Agent，并把初始化异常返回页面]
    def event_factory(query: str, history: list[dict], web_search_enabled: bool = False):
        nonlocal web_bot
        tavily_available = tavily_mcp_info().get('available', False)
        if web_search_enabled and tavily_available:
            if web_bot is None:
                yield {'type': 'log', 'message': '本轮联网开关已打开，正在初始化 Tavily MCP。'}
                yield {'type': 'web_search', 'status': 'enabled', 'tool': 'Tavily MCP'}
                try:
                    web_bot = init_agent_service(enable_tavily=True)
                except Exception as exc:
                    yield {'type': 'log', 'message': f'Tavily MCP 初始化失败：{exc}'}
                    yield {'type': 'answer', 'content': f'Tavily MCP 初始化失败：{exc}\n\n请先关闭“本轮联网”开关继续使用本地 ES 文档检索，或检查 Node.js/npx、tavily-mcp 和 TAVILY_API_KEY 配置。'}
                    yield {'type': 'done'}
                    return
                yield {'type': 'log', 'message': 'Tavily MCP 初始化完成。'}
            yield from run_qa_events(web_bot, query, history, web_search_enabled=True)
            return
        yield from run_qa_events(local_bot, query, history, web_search_enabled=web_search_enabled)
    # mod end

    run_web_app(
        event_factory,
        doc_count=len(load_doc_files()),
        rag_label=rag_backend_label(),
        rag_info=rag_backend_info(),
        tavily_info=tavily_mcp_info(),
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Qwen Agent 多文件文档问答 demo')
    parser.add_argument('--tui', action='store_true', help='使用终端模式运行一次示例问答')
    args = parser.parse_args()
    if args.tui:
        app_tui()
    else:
        app_gui()
# mod end
