import os
import logging
import argparse
import json
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import json5
from dotenv import load_dotenv
from qwen_agent.agents.assistant import Assistant, format_knowledge_to_source_and_content
from qwen_agent.tools.base import BaseTool, register_tool

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
    """图形界面模式，提供 Web 文档问答界面。"""
    bot = init_agent_service()

    def _history_to_messages(history):
        messages = []
        for message in history:
            if message.get('role') in ('user', 'assistant') and message.get('content'):
                messages.append({'role': message['role'], 'content': message['content']})
        return messages

    def _answer(query, history):
        if not query or not query.strip():
            return ''
        answer = ''
        for event in _run_qa_events(bot, query, _history_to_messages(history)):
            if event['type'] == 'answer':
                answer = event['content']
        return answer

    examples = [
        '介绍下雇主责任险',
        '雇主责任险和团体意外险有什么区别？',
        '上下班途中发生事故是否属于雇主责任险保障范围？',
    ]
    page_html = f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>保险文档问答助手</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: "Microsoft YaHei", "Segoe UI", sans-serif; color: #172033; background: #f4f6fa; }}
    .shell {{ max-width: 1280px; margin: 0 auto; min-height: 100vh; padding: 28px 22px; display: flex; flex-direction: column; gap: 16px; }}
    header {{ display: flex; align-items: flex-end; justify-content: space-between; gap: 18px; }}
    h1 {{ margin: 0; font-size: 28px; line-height: 1.2; }}
    .subtitle {{ margin: 8px 0 0; color: #667085; font-size: 14px; }}
    .status {{ color: #14804a; background: #eaf7ef; border: 1px solid #c9ead5; padding: 7px 10px; border-radius: 6px; font-size: 13px; white-space: nowrap; }}
    .main-grid {{ display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 14px; align-items: stretch; }}
    .chat {{ min-height: 520px; max-height: 66vh; overflow-y: auto; background: #fff; border: 1px solid #dfe4ec; border-radius: 8px; padding: 18px; }}
    .side {{ min-height: 520px; max-height: 66vh; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; }}
    .panel {{ background: #fff; border: 1px solid #dfe4ec; border-radius: 8px; padding: 14px; }}
    .panel h2 {{ margin: 0 0 10px; font-size: 15px; }}
    .debug-list {{ margin: 0; padding-left: 18px; color: #475467; font-size: 13px; line-height: 1.6; }}
    .ref-item {{ border-top: 1px solid #edf0f5; padding-top: 10px; margin-top: 10px; }}
    .ref-source {{ font-weight: 700; color: #2557d6; font-size: 13px; }}
    .ref-content {{ margin-top: 6px; color: #475467; font-size: 12px; line-height: 1.55; white-space: pre-wrap; max-height: 150px; overflow: auto; }}
    .empty {{ height: 100%; min-height: 460px; display: grid; place-items: center; color: #98a2b3; text-align: center; }}
    .msg {{ max-width: 82%; margin: 0 0 14px; padding: 12px 14px; border-radius: 8px; line-height: 1.7; white-space: pre-wrap; word-break: break-word; }}
    .user {{ margin-left: auto; color: #fff; background: #2557d6; }}
    .assistant {{ margin-right: auto; color: #172033; background: #f0f3f8; border: 1px solid #e2e7f0; }}
    .quick {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }}
    .quick button {{ min-height: 48px; text-align: left; padding: 10px 12px; color: #172033; background: #fff; border: 1px solid #d8dee9; border-radius: 8px; cursor: pointer; font-weight: 600; }}
    .quick button:hover {{ border-color: #2557d6; color: #2557d6; }}
    .composer {{ display: grid; grid-template-columns: 1fr 96px; gap: 10px; }}
    textarea {{ width: 100%; min-height: 54px; max-height: 140px; resize: vertical; padding: 14px; border: 1px solid #d8dee9; border-radius: 8px; font: inherit; outline: none; }}
    textarea:focus {{ border-color: #2557d6; box-shadow: 0 0 0 3px rgba(37, 87, 214, .12); }}
    .send {{ border: 0; border-radius: 8px; color: #fff; background: #2557d6; font-size: 16px; font-weight: 700; cursor: pointer; }}
    .send:disabled {{ background: #9aa9d6; cursor: not-allowed; }}
    .toolbar {{ display: flex; justify-content: flex-end; }}
    .clear {{ border: 1px solid #d8dee9; background: #fff; color: #475467; border-radius: 6px; padding: 7px 12px; cursor: pointer; }}
    @media (max-width: 760px) {{
      header {{ align-items: flex-start; flex-direction: column; }}
      .quick {{ grid-template-columns: 1fr; }}
      .main-grid {{ grid-template-columns: 1fr; }}
      .composer {{ grid-template-columns: 1fr; }}
      .send {{ min-height: 48px; }}
      .msg {{ max-width: 100%; }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <div>
        <h1>保险文档问答助手</h1>
        <p class="subtitle">基于 docs 目录中的本地保险文档回答问题</p>
      </div>
      <div class="status">知识库已加载：{len(_load_doc_files())} 个文件</div>
    </header>
    <section class="main-grid">
      <div id="chat" class="chat"><div class="empty">选择一个推荐问题，或在下方输入你的问题</div></div>
      <aside class="side">
        <div class="panel">
          <h2>调试过程</h2>
          <ol id="debug" class="debug-list"><li>等待提问。</li></ol>
        </div>
        <div class="panel">
          <h2>参考文档</h2>
          <div id="refs" class="refs">暂无参考文档。</div>
        </div>
      </aside>
    </section>
    <section class="quick">
      {''.join(f'<button type="button" class="quick-question">{question}</button>' for question in examples)}
    </section>
    <section class="composer">
      <textarea id="query" placeholder="请输入保险文档相关问题..."></textarea>
      <button id="send" class="send">发送</button>
    </section>
    <div class="toolbar"><button id="clear" class="clear">清空对话</button></div>
  </main>
  <script>
    const chat = document.getElementById('chat');
    const query = document.getElementById('query');
    const send = document.getElementById('send');
    const clear = document.getElementById('clear');
    const debug = document.getElementById('debug');
    const refs = document.getElementById('refs');
    const history = [];

    function render() {{
      if (!history.length) {{
        chat.innerHTML = '<div class="empty">选择一个推荐问题，或在下方输入你的问题</div>';
        return;
      }}
      chat.innerHTML = history.map(m => `<div class="msg ${{m.role}}">${{escapeHtml(m.content)}}</div>`).join('');
      chat.scrollTop = chat.scrollHeight;
    }}

    function escapeHtml(text) {{
      return text.replace(/[&<>"']/g, ch => ({{'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}}[ch]));
    }}

    function resetDebug() {{
      debug.innerHTML = '';
      refs.innerHTML = '暂无参考文档。';
    }}

    function addLog(message) {{
      const item = document.createElement('li');
      item.textContent = message;
      debug.appendChild(item);
    }}

    function renderRefs(items) {{
      if (!items || !items.length) {{
        refs.innerHTML = '暂无参考文档。';
        return;
      }}
      refs.innerHTML = items.map((item, index) => `
        <div class="ref-item">
          <div class="ref-source">${{index + 1}}. ${{escapeHtml(item.source)}}</div>
          <div class="ref-content">${{escapeHtml((item.content || '').slice(0, 900))}}</div>
        </div>
      `).join('');
    }}

    async function ask(text) {{
      const content = text.trim();
      if (!content || send.disabled) return;
      history.push({{role: 'user', content}});
      history.push({{role: 'assistant', content: '正在检索文档并生成回答...'}});
      query.value = '';
      send.disabled = true;
      resetDebug();
      addLog('提交问题。');
      render();
      try {{
        const res = await fetch('/api/chat-stream', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{query: content, history: history.slice(0, -2)}})
        }});
        const reader = res.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';
        while (true) {{
          const {{value, done}} = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, {{stream: true}});
          const chunks = buffer.split('\\n\\n');
          buffer = chunks.pop();
          for (const chunk of chunks) {{
            if (!chunk.startsWith('data: ')) continue;
            const event = JSON.parse(chunk.slice(6));
            if (event.type === 'log') addLog(event.message);
            if (event.type === 'refs') renderRefs(event.items);
            if (event.type === 'answer') {{
              history[history.length - 1].content = event.content;
              render();
            }}
          }}
        }}
      }} catch (err) {{
        history[history.length - 1].content = '请求失败：' + err;
      }} finally {{
        send.disabled = false;
        render();
        query.focus();
      }}
    }}

    send.addEventListener('click', () => ask(query.value));
    query.addEventListener('keydown', e => {{
      if (e.key === 'Enter' && !e.shiftKey) {{
        e.preventDefault();
        ask(query.value);
      }}
    }});
    clear.addEventListener('click', () => {{ history.length = 0; resetDebug(); addLog('等待提问。'); render(); query.focus(); }});
    document.querySelectorAll('.quick-question').forEach(btn => btn.addEventListener('click', () => ask(btn.textContent)));
  </script>
</body>
</html>'''

    class QAHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ('/', '/index.html'):
                self.send_error(404)
                return
            body = page_html.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path not in ('/api/chat', '/api/chat-stream'):
                self.send_error(404)
                return
            length = int(self.headers.get('Content-Length', '0'))
            payload = json.loads(self.rfile.read(length).decode('utf-8'))

            if self.path == '/api/chat-stream':
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Connection', 'keep-alive')
                self.end_headers()
                for event in _run_qa_events(bot, payload.get('query', ''), payload.get('history', [])):
                    data = json.dumps(event, ensure_ascii=False).encode('utf-8')
                    self.wfile.write(b'data: ' + data + b'\n\n')
                    self.wfile.flush()
                return

            answer = _answer(payload.get('query', ''), payload.get('history', []))
            body = json.dumps({'answer': answer}, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(('127.0.0.1', 7860), QAHandler)
    url = 'http://127.0.0.1:7860'
    print(f'Web 界面准备就绪：{url}')
    webbrowser.open(url)
    server.serve_forever()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Qwen Agent 多文件文档问答 demo')
    parser.add_argument('--tui', action='store_true', help='使用终端模式运行一次示例问答')
    args = parser.parse_args()
    if args.tui:
        app_tui()
    else:
        app_gui()
# mod end
