# add by gq [2026-05-07：拆分 Web GUI，避免主脚本混入界面代码]
import html
import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


DEFAULT_EXAMPLES = [
    '介绍下雇主责任险',
    '雇主责任险和团体意外险有什么区别？',
    '上下班途中发生事故是否属于雇主责任险保障范围？',
]


# add by gq [2026-05-07：在 GUI 中显式展示 ES 检索后端、地址和索引名]
def _build_rag_panel_html(rag_label: str, rag_info: dict | None) -> str:
    info = rag_info or {}
    backend = html.escape(str(info.get('backend') or rag_label))
    badge = html.escape(str(info.get('badge') or 'RAG'))
    address = html.escape(str(info.get('address') or '-'))
    index_name = html.escape(str(info.get('index_name') or '-'))
    mode = html.escape(str(info.get('mode') or '-'))
    label = html.escape(str(info.get('label') or rag_label))
    return f'''
          <div class="backend-summary">
            <span class="backend-badge">{badge}</span>
            <div>
              <strong>{backend} 检索</strong>
              <p>{label}</p>
            </div>
          </div>
          <dl class="backend-list">
            <div><dt>地址</dt><dd>{address}</dd></div>
            <div><dt>索引</dt><dd>{index_name}</dd></div>
            <div><dt>模式</dt><dd>{mode}</dd></div>
          </dl>'''
# add end


# modified by gq [2026-05-08：在 GUI 中展示 Tavily MCP 可用状态，并提供本轮联网开关]
def _build_tavily_panel_html(tavily_info: dict | None) -> str:
    info = tavily_info or {}
    available = bool(info.get('available'))
    has_key = bool(info.get('has_key'))
    badge = html.escape(str(info.get('badge') or 'WEB'))
    status = '可用' if available else '未配置'
    status_class = 'online' if available else 'offline'
    command = html.escape(str(info.get('command') or '-'))
    package = html.escape(str(info.get('package') or '-'))
    mode = html.escape(str(info.get('mode') or '-'))
    key_status = '已配置' if has_key else '未配置'
    disabled_attr = '' if available else ' disabled'
    initial_state = '已关闭，本轮只使用本地文档检索。' if available else '未配置 TAVILY_API_KEY，无法打开联网搜索。'
    return f'''
          <div class="backend-summary {status_class}">
            <span class="backend-badge">{badge}</span>
            <div>
              <strong>Tavily MCP：{status}</strong>
              <p>打开本轮开关后，模型需要时才会真正调用 Tavily。</p>
            </div>
          </div>
          <div class="web-toggle-row">
            <span>本轮联网</span>
            <label class="switch" title="控制本轮问答是否允许调用 Tavily MCP">
              <input id="web-search-toggle" type="checkbox"{disabled_attr}>
              <span class="slider"></span>
            </label>
          </div>
          <dl class="backend-list">
            <div><dt>模式</dt><dd>{mode}</dd></div>
            <div><dt>Key</dt><dd>{key_status}</dd></div>
            <div><dt>命令</dt><dd>{command}</dd></div>
            <div><dt>包</dt><dd>{package}</dd></div>
          </dl>
          <div id="web-search-state" class="web-search-state {status_class}">{initial_state}</div>'''
# mod end


# modified by gq [2026-05-08：首屏增加 ES 状态和 Tavily MCP 状态，便于确认检索来源]
def _build_page_html(doc_count: int,
                     examples: list[str],
                     rag_label: str,
                     rag_info: dict | None = None,
                     tavily_info: dict | None = None) -> str:
    rag_badge = html.escape(str((rag_info or {}).get('badge') or 'RAG'))
    rag_backend = html.escape(str((rag_info or {}).get('backend') or rag_label))
    rag_panel_html = _build_rag_panel_html(rag_label, rag_info)
    tavily_panel_html = _build_tavily_panel_html(tavily_info)
    tavily_available = bool((tavily_info or {}).get('available'))
    tavily_badge = html.escape(str((tavily_info or {}).get('badge') or 'WEB'))
    tavily_status = 'Tavily 可用' if tavily_available else 'Tavily 未配置'
    tavily_status_class = 'status-web-on' if tavily_available else 'status-web-off'
    quick_buttons = ''.join(
        f'<button type="button" class="quick-question">{html.escape(question)}</button>'
        for question in examples
    )
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
    .header-status {{ display: flex; align-items: stretch; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }}
    .status {{ display: flex; align-items: center; gap: 8px; padding: 7px 10px; border-radius: 6px; font-size: 13px; white-space: nowrap; }}
    .status-doc {{ color: #14804a; background: #eaf7ef; border: 1px solid #c9ead5; }}
    .status-rag {{ color: #1849a9; background: #eef4ff; border: 1px solid #c7d7fe; }}
    .status-web-on {{ color: #9f1239; background: #fff1f2; border: 1px solid #fecdd3; }}
    .status-web-off {{ color: #667085; background: #f8fafc; border: 1px solid #d8dee9; }}
    .status-badge {{ display: inline-grid; place-items: center; min-width: 28px; height: 22px; padding: 0 6px; border-radius: 5px; color: #fff; background: #2557d6; font-weight: 800; font-size: 12px; }}
    .main-grid {{ display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 14px; align-items: stretch; }}
    .chat {{ min-height: 520px; max-height: 66vh; overflow-y: auto; background: #fff; border: 1px solid #dfe4ec; border-radius: 8px; padding: 18px; }}
    .side {{ min-height: 520px; max-height: 66vh; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; }}
    .panel {{ background: #fff; border: 1px solid #dfe4ec; border-radius: 8px; padding: 14px; }}
    .panel h2 {{ margin: 0 0 10px; font-size: 15px; }}
    .backend-summary {{ display: flex; gap: 10px; align-items: flex-start; padding: 10px; background: #f5f8ff; border: 1px solid #d6e4ff; border-radius: 8px; }}
    .backend-summary.online {{ background: #fff1f2; border-color: #fecdd3; }}
    .backend-summary.offline {{ background: #f8fafc; border-color: #d8dee9; }}
    .backend-summary p {{ margin: 4px 0 0; color: #475467; font-size: 12px; line-height: 1.45; word-break: break-all; }}
    .backend-badge {{ flex: 0 0 auto; display: inline-grid; place-items: center; min-width: 34px; height: 28px; padding: 0 7px; color: #fff; background: #2557d6; border-radius: 6px; font-size: 13px; font-weight: 800; }}
    .backend-list {{ display: grid; gap: 8px; margin: 12px 0 0; font-size: 12px; }}
    .backend-list div {{ display: grid; grid-template-columns: 42px minmax(0, 1fr); gap: 8px; }}
    .backend-list dt {{ color: #667085; }}
    .backend-list dd {{ margin: 0; color: #172033; word-break: break-all; }}
    .web-search-state {{ margin-top: 12px; padding: 8px 10px; border-radius: 6px; font-size: 12px; line-height: 1.45; }}
    .web-search-state.online {{ color: #9f1239; background: #fff1f2; border: 1px solid #fecdd3; }}
    .web-search-state.offline {{ color: #475467; background: #f8fafc; border: 1px solid #d8dee9; }}
    .web-search-state.called {{ color: #1849a9; background: #eef4ff; border: 1px solid #c7d7fe; }}
    .web-search-state.completed {{ color: #14804a; background: #eaf7ef; border: 1px solid #c9ead5; }}
    .web-toggle-row {{ display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 12px; padding: 10px; border-radius: 8px; background: #f8fafc; border: 1px solid #d8dee9; font-size: 13px; font-weight: 700; }}
    .switch {{ position: relative; display: inline-block; width: 44px; height: 24px; flex: 0 0 auto; }}
    .switch input {{ opacity: 0; width: 0; height: 0; }}
    .slider {{ position: absolute; cursor: pointer; inset: 0; background: #cbd5e1; border-radius: 999px; transition: .18s; }}
    .slider:before {{ content: ""; position: absolute; width: 18px; height: 18px; left: 3px; top: 3px; background: #fff; border-radius: 50%; transition: .18s; box-shadow: 0 1px 3px rgba(15, 23, 42, .24); }}
    .switch input:checked + .slider {{ background: #e11d48; }}
    .switch input:checked + .slider:before {{ transform: translateX(20px); }}
    .switch input:disabled + .slider {{ cursor: not-allowed; opacity: .55; }}
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
      .header-status {{ justify-content: flex-start; }}
      .status {{ white-space: normal; }}
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
      <div class="header-status">
        <div class="status status-doc">知识库：{doc_count} 个文件</div>
        <div class="status status-rag"><span class="status-badge">{rag_badge}</span>{rag_backend} 检索</div>
        <div class="status {tavily_status_class}"><span class="status-badge">{tavily_badge}</span>{tavily_status}</div>
      </div>
    </header>
    <section class="main-grid">
      <div id="chat" class="chat"><div class="empty">选择一个推荐问题，或在下方输入你的问题</div></div>
      <aside class="side">
        <div class="panel">
          <h2>检索后端</h2>
{rag_panel_html}
        </div>
        <div class="panel">
          <h2>联网搜索</h2>
{tavily_panel_html}
        </div>
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
      {quick_buttons}
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
    const webSearchState = document.getElementById('web-search-state');
    const webSearchToggle = document.getElementById('web-search-toggle');
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
      resetWebSearchState();
    }}

    function addLog(message) {{
      const item = document.createElement('li');
      item.textContent = message;
      debug.appendChild(item);
    }}

    function setWebSearchState(message, state) {{
      if (!webSearchState) return;
      webSearchState.textContent = message;
      webSearchState.className = 'web-search-state ' + state;
    }}

    function resetWebSearchState() {{
      if (!webSearchToggle) {{
        setWebSearchState('本轮未启用联网搜索，只使用本地文档检索。', 'offline');
        return;
      }}
      if (webSearchToggle.disabled) {{
        setWebSearchState('未配置 TAVILY_API_KEY，无法打开联网搜索。', 'offline');
        return;
      }}
      if (webSearchToggle.checked) {{
        setWebSearchState('本轮联网开关已打开，等待提问。', 'online');
      }} else {{
        setWebSearchState('本轮联网开关已关闭，只使用本地文档检索。', 'offline');
      }}
    }}

    function renderWebSearch(event) {{
      if (event.status === 'disabled') setWebSearchState('本轮未启用联网搜索，只使用本地文档检索。', 'offline');
      if (event.status === 'enabled') setWebSearchState('本轮联网开关已打开，等待模型判断是否需要联网。', 'online');
      if (event.status === 'called') {{
        setWebSearchState('正在调用联网搜索工具：' + event.tool, 'called');
        addLog('联网搜索调用：' + event.tool);
      }}
      if (event.status === 'completed') {{
        setWebSearchState('联网搜索已完成：' + event.tool, 'completed');
        addLog('联网搜索完成：' + event.tool);
      }}
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
          body: JSON.stringify({{
            query: content,
            history: history.slice(0, -2),
            web_search_enabled: webSearchToggle ? webSearchToggle.checked : false
          }})
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
            if (event.type === 'web_search') renderWebSearch(event);
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
        if (!streamFinished) {{
          addLog('响应流已提前结束。');
          if (history[history.length - 1].content === '正在检索文档并生成回答...') {{
            history[history.length - 1].content = '响应流提前结束，请查看终端日志或关闭“本轮联网”后重试。';
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
    if (webSearchToggle) webSearchToggle.addEventListener('change', resetWebSearchState);
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
# mod end


# modified by gq [2026-05-07：接收结构化 RAG 信息，在页面中突出显示 ES 检索配置]
def run_web_app(event_factory,
                doc_count: int,
                host: str = '127.0.0.1',
                port: int = 7860,
                examples=None,
                rag_label: str = '默认检索',
                rag_info: dict | None = None,
                tavily_info: dict | None = None):
    examples = examples or DEFAULT_EXAMPLES
    page_html = _build_page_html(doc_count, examples, rag_label, rag_info, tavily_info)

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
                for event in event_factory(
                    payload.get('query', ''),
                    payload.get('history', []),
                    bool(payload.get('web_search_enabled', False)),
                ):
                    data = json.dumps(event, ensure_ascii=False).encode('utf-8')
                    self.wfile.write(b'data: ' + data + b'\n\n')
                    self.wfile.flush()
            except Exception as exc:
                for event in (
                    {'type': 'log', 'message': f'后端处理异常：{exc}'},
                    {'type': 'answer', 'content': f'后端处理异常：{exc}'},
                    {'type': 'done'},
                ):
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
# mod end
