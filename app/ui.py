from fastapi.responses import HTMLResponse


def render_home() -> HTMLResponse:
    html = r"""
<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Day 12 Production Agent</title>
  <style>
    :root {
      --bg: #0f172a;
      --panel: #111827;
      --panel2: #1f2937;
      --text: #e5e7eb;
      --muted: #9ca3af;
      --accent: #22c55e;
      --danger: #ef4444;
      --border: rgba(255,255,255,.12);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(34,197,94,.18), transparent 30%),
        radial-gradient(circle at bottom right, rgba(59,130,246,.16), transparent 30%),
        var(--bg);
      color: var(--text);
      min-height: 100vh;
      display: flex;
      justify-content: center;
      padding: 32px 16px;
    }
    .app {
      width: min(980px, 100%);
      display: grid;
      grid-template-columns: 280px 1fr;
      gap: 18px;
    }
    .sidebar, .chat {
      background: rgba(17,24,39,.88);
      border: 1px solid var(--border);
      border-radius: 24px;
      box-shadow: 0 24px 80px rgba(0,0,0,.28);
      backdrop-filter: blur(16px);
    }
    .sidebar { padding: 22px; height: fit-content; }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 20px;
    }
    .logo {
      width: 44px;
      height: 44px;
      border-radius: 14px;
      background: linear-gradient(135deg, #22c55e, #06b6d4);
      display: grid;
      place-items: center;
      font-weight: 900;
      color: #052e16;
    }
    h1 { font-size: 20px; margin: 0; }
    .subtitle { color: var(--muted); font-size: 13px; line-height: 1.45; margin-top: 4px; }
    label { display: block; font-size: 13px; color: var(--muted); margin: 14px 0 7px; }
    input, textarea {
      width: 100%;
      border: 1px solid var(--border);
      background: rgba(31,41,55,.9);
      color: var(--text);
      border-radius: 14px;
      padding: 12px 13px;
      outline: none;
      font: inherit;
    }
    textarea { min-height: 104px; resize: vertical; }
    button {
      border: 0;
      background: linear-gradient(135deg, #22c55e, #14b8a6);
      color: #052e16;
      font-weight: 800;
      border-radius: 14px;
      padding: 13px 16px;
      cursor: pointer;
      width: 100%;
      margin-top: 14px;
    }
    button:disabled { opacity: .6; cursor: not-allowed; }
    .hint {
      margin-top: 16px;
      padding: 13px;
      border-radius: 16px;
      background: rgba(34,197,94,.08);
      border: 1px solid rgba(34,197,94,.18);
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }
    .chat {
      min-height: 720px;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    .chat-header {
      padding: 20px 22px;
      border-bottom: 1px solid var(--border);
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
    }
    .status { color: var(--muted); font-size: 13px; }
    .messages {
      flex: 1;
      padding: 22px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .msg {
      max-width: 82%;
      padding: 14px 16px;
      border-radius: 18px;
      line-height: 1.55;
      white-space: pre-wrap;
    }
    .user {
      align-self: flex-end;
      background: #2563eb;
      color: white;
      border-bottom-right-radius: 6px;
    }
    .bot {
      align-self: flex-start;
      background: rgba(31,41,55,.95);
      border: 1px solid var(--border);
      border-bottom-left-radius: 6px;
    }
    .error {
      align-self: flex-start;
      background: rgba(239,68,68,.12);
      border: 1px solid rgba(239,68,68,.3);
      color: #fecaca;
    }
    .composer {
      padding: 18px 22px 22px;
      border-top: 1px solid var(--border);
      display: grid;
      grid-template-columns: 1fr 140px;
      gap: 12px;
    }
    .composer textarea { min-height: 56px; max-height: 160px; }
    .composer button { margin-top: 0; }
    .pill {
      display: inline-flex;
      border: 1px solid var(--border);
      color: var(--muted);
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 12px;
    }
    @media (max-width: 780px) {
      body { padding: 12px; }
      .app { grid-template-columns: 1fr; }
      .chat { min-height: 620px; }
      .composer { grid-template-columns: 1fr; }
      .msg { max-width: 94%; }
    }
  </style>
</head>
<body>
  <main class="app">
    <aside class="sidebar">
      <div class="brand">
        <div class="logo">D12</div>
        <div>
          <h1>Day 12 Production Agent</h1>
          <div class="subtitle">Demo production agent cho bài lab cloud deployment.</div>
        </div>
      </div>

      <label>API Key</label>
      <input id="apiKey" type="password" placeholder="Nhập X-API-Key của backend" />

      <label>User ID</label>
      <input id="userId" value="demo-user" />

      <button onclick="checkHealth()">Check health</button>

      <div class="hint">
        Demo UI gọi endpoint <b>/ask</b> của final lab mock agent để kiểm tra authentication, rate limiting, history và budget guard.
      </div>
    </aside>

    <section class="chat">
      <div class="chat-header">
        <div>
          <b>Chat</b>
          <div class="status" id="status">Ready</div>
        </div>
        <span class="pill">Lab Mock Agent</span>
      </div>

      <div class="messages" id="messages">
        <div class="msg bot">Xin chào. Hãy nhập API key rồi đặt câu hỏi để kiểm tra final lab backend.</div>
      </div>

      <div class="composer">
        <textarea id="question" placeholder="Ví dụ: Hệ thống hiện đang hoạt động thế nào?"></textarea>
        <button id="sendBtn" onclick="sendQuestion()">Send</button>
      </div>
    </section>
  </main>

  <script>
    const messages = document.getElementById("messages");
    const statusEl = document.getElementById("status");
    const questionEl = document.getElementById("question");
    const sendBtn = document.getElementById("sendBtn");

    function addMessage(text, cls) {
      const div = document.createElement("div");
      div.className = "msg " + cls;
      div.textContent = text;
      messages.appendChild(div);
      messages.scrollTop = messages.scrollHeight;
    }

    function getHeaders() {
      const apiKey = document.getElementById("apiKey").value.trim();
      const userId = document.getElementById("userId").value.trim() || "demo-user";
      const headers = { "Content-Type": "application/json", "X-User-ID": userId };
      if (apiKey) headers["X-API-Key"] = apiKey;
      return headers;
    }

    async function checkHealth() {
      statusEl.textContent = "Checking health...";
      try {
        const res = await fetch("/health");
        const data = await res.json();
        statusEl.textContent = "Health: " + (data.status || "ok");
        addMessage("Health check OK:\n" + JSON.stringify(data, null, 2), "bot");
      } catch (err) {
        statusEl.textContent = "Health check failed";
        addMessage("Không gọi được /health: " + err.message, "error");
      }
    }

    async function sendQuestion() {
      const question = questionEl.value.trim();
      if (!question) return;

      addMessage(question, "user");
      questionEl.value = "";
      sendBtn.disabled = true;
      statusEl.textContent = "Thinking...";

      try {
        const res = await fetch("/ask", {
          method: "POST",
          headers: getHeaders(),
          body: JSON.stringify({ question })
        });

        const text = await res.text();
        let data;
        try { data = JSON.parse(text); } catch { data = { raw: text }; }

        if (!res.ok) {
          addMessage("Error " + res.status + ":\n" + JSON.stringify(data, null, 2), "error");
        } else {
          const answer = data.answer || data.response || JSON.stringify(data, null, 2);
          addMessage(answer, "bot");
        }
      } catch (err) {
        addMessage("Request failed: " + err.message, "error");
      } finally {
        sendBtn.disabled = false;
        statusEl.textContent = "Ready";
      }
    }

    questionEl.addEventListener("keydown", function(e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendQuestion();
      }
    });
  </script>
</body>
</html>
"""
    return HTMLResponse(html)
