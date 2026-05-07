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
    bot = init_agent_service()

    def event_factory(query: str, history: list[dict]):
        return run_qa_events(bot, query, history)

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
