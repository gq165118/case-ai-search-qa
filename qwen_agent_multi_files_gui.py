# add by gq [2026-05-07：拆分 Web GUI，避免主脚本混入界面代码]
import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


DEFAULT_EXAMPLES = [
    '介绍下雇主责任险',
    '雇主责任险和团体意外险有什么区别？',
    '上下班途中发生事故是否属于雇主责任险保障范围？',
]


def _build_page_html(doc_count: int, examples: list[str]) -> str:
    return f'''<!doctype html>
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
      <div class="status">知识库已加载：{doc_count} 个文件</div>
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
        let streamFinished = false;
        readLoop:
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
            if (event.type === 'done') {{
              streamFinished = true;
              await reader.cancel();
              break readLoop;
            }}
          }}
        }}
        if (!streamFinished) addLog('响应流已结束。');
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


def run_web_app(event_factory, doc_count: int, host: str = '127.0.0.1', port: int = 7860, examples=None):
    examples = examples or DEFAULT_EXAMPLES
    page_html = _build_page_html(doc_count, examples)

    class QAHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ('/', '/index.html'):
                self.send_error(404)
                return
            body = page_html.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != '/api/chat-stream':
                self.send_error(404)
                return
            length = int(self.headers.get('Content-Length', '0'))
            payload = json.loads(self.rfile.read(length).decode('utf-8'))
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'close')
            self.end_headers()
            try:
                for event in event_factory(payload.get('query', ''), payload.get('history', [])):
                    data = json.dumps(event, ensure_ascii=False).encode('utf-8')
                    self.wfile.write(b'data: ' + data + b'\n\n')
                    self.wfile.flush()
            finally:
                self.close_connection = True

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer((host, port), QAHandler)
    url = f'http://{host}:{port}'
    print(f'Web 界面准备就绪：{url}')
    webbrowser.open(url)
    server.serve_forever()
# add end
