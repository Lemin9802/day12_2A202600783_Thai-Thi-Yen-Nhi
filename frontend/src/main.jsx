import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";
const API_KEY = import.meta.env.VITE_MAITHUYLAW_API_KEY || "";
const USER_KEY = "maithuylaw_user_id";
const userId = localStorage.getItem(USER_KEY) || `web-${crypto.randomUUID()}`;
localStorage.setItem(USER_KEY, userId);

const copy = {
  appName: "MaiThuyLaw AI",
  tagline: "Tra cứu pháp luật về ma túy",
  welcome: "Xin chào, mình là MaiThuyLaw AI",
  description: "Hỏi bằng ngôn ngữ tự nhiên. Câu trả lời sẽ nêu rõ mức độ căn cứ và nguồn chính thống khi có đủ dữ liệu.",
  safety: "MaiThuyLaw AI chỉ hỗ trợ tìm hiểu pháp luật và phòng tránh rủi ro. Hệ thống không hướng dẫn thực hiện, che giấu hoặc né tránh hành vi vi phạm.",
  examples: [
    "Sử dụng trái phép chất ma túy bị xử lý thế nào?",
    "Tàng trữ ma túy khác mua bán ma túy thế nào?",
    "Quy trình cai nghiện bắt buộc ra sao?",
    "Gia đình nên làm gì khi người thân nghiện ma túy?",
  ],
};

class ApiError extends Error {
  constructor(status, detail, retryAfter) {
    super(detail || `HTTP ${status}`);
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

function friendlyError(error) {
  if (error?.name === "AbortError") return "Yêu cầu mất quá nhiều thời gian. Nội dung của bạn vẫn được giữ để thử lại.";
  if (error?.status === 401) return "Phiên truy cập không hợp lệ. Vui lòng tải lại trang.";
  if (error?.status === 413) return "Tệp vượt quá giới hạn 2MB.";
  if (error?.status === 415) return "Định dạng tệp chưa được hỗ trợ.";
  if (error?.status === 429) return "Bạn đang gửi hơi nhanh. Vui lòng thử lại sau ít phút.";
  if (error?.status >= 500) return "Hệ thống chưa thể xử lý yêu cầu lúc này. Vui lòng thử lại.";
  return error?.message || "Không thể kết nối tới hệ thống. Vui lòng thử lại.";
}

async function request(path, options = {}, signal) {
  const isForm = options.body instanceof FormData;
  const headers = { ...(options.headers || {}) };
  if (!isForm) headers["Content-Type"] = "application/json";
  if (API_KEY) headers["X-API-Key"] = API_KEY;
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers, credentials: "include", signal });
  const raw = await response.text();
  let data = raw;
  try { data = raw ? JSON.parse(raw) : null; } catch { /* keep text */ }
  if (!response.ok) {
    const detail = typeof data === "object" ? data?.detail?.error || data?.detail || data?.error : data;
    throw new ApiError(response.status, typeof detail === "string" ? detail : JSON.stringify(detail), response.headers.get("Retry-After"));
  }
  return data;
}

function normalizeMessage(message) {
  return {
    id: message.id || crypto.randomUUID(),
    role: message.role,
    content: message.content || message.answer || "",
    sources: Array.isArray(message.sources) ? message.sources : [],
    refused: Boolean(message.refused),
    reason: message.reason || null,
    evidenceLevel: message.evidence_level || message.evidenceLevel || null,
    confidence: message.confidence ?? null,
    safety: message.safety || {},
    followups: message.follow_up_suggestions || message.followups || [],
    createdAt: message.created_at || new Date().toISOString(),
  };
}

function evidenceClass(level) {
  if (level === "Căn cứ rõ") return "evidence clear";
  if (level === "Cần kiểm tra thêm") return "evidence partial";
  if (level === "Chưa đủ căn cứ") return "evidence insufficient";
  if (level === "Câu hỏi nhạy cảm") return "evidence sensitive";
  return "evidence scope";
}

function inlineContent(text, sources) {
  const parts = String(text || "").split(/(\[[\d,\s]+\])/g);
  return parts.map((part, index) => {
    const match = part.match(/^\[([\d,\s]+)\]$/);
    if (!match) return <React.Fragment key={index}>{part}</React.Fragment>;
    const refs = match[1].split(",").map(v => Number(v.trim())).filter(v => v >= 1 && v <= sources.length);
    if (!refs.length) return null;
    return <span className="citation" key={index} aria-label={`Nguồn ${refs.join(", ")}`}>{refs.join(",")}</span>;
  });
}

function AnswerBody({ text, sources }) {
  const lines = String(text || "").split("\n");
  return <div className="answer-body">{lines.map((line, index) => {
    const value = line.trim();
    if (!value) return <div className="answer-space" key={index} />;
    if (value.startsWith("## ")) return <h3 key={index}>{inlineContent(value.slice(3), sources)}</h3>;
    if (/^[-*•]\s+/.test(value)) return <div className="answer-point" key={index}><span aria-hidden="true">•</span><p>{inlineContent(value.replace(/^[-*•]\s+/, ""), sources)}</p></div>;
    return <p key={index}>{inlineContent(value, sources)}</p>;
  })}</div>;
}

function SourceCard({ source, index }) {
  const href = source.canonical_url || source.url;
  const body = <>
    <span className="source-index">{index + 1}</span>
    <span className="source-content">
      <strong>{source.title || `Nguồn ${index + 1}`}</strong>
      <span className="source-meta">{source.source_type_label || "Nguồn tham khảo"}{source.publisher ? ` · ${source.publisher}` : ""}</span>
      {source.snippet && <span className="source-snippet">{source.snippet}</span>}
    </span>
    {href && <span className="source-open" aria-hidden="true">↗</span>}
  </>;
  return href ? <a className="source-card" href={href} target="_blank" rel="noreferrer">{body}</a> : <div className="source-card">{body}</div>;
}

function AssistantMessage({ message, onFollowup }) {
  return <article className="message assistant-message">
    <div className="assistant-heading"><span className={evidenceClass(message.evidenceLevel)}>{message.evidenceLevel || "Chưa đủ căn cứ"}</span>{message.confidence != null && <span className="confidence">Độ tin cậy {Math.round(message.confidence * 100)}%</span>}</div>
    <AnswerBody text={message.content} sources={message.sources} />
    {message.sources.length > 0 && <section className="sources" aria-label="Căn cứ tham khảo"><h4>Căn cứ tham khảo</h4>{message.sources.map((source, index) => <SourceCard source={source} index={index} key={`${source.doc_id || source.url || index}`} />)}</section>}
    {message.followups.length > 0 && <section className="followups"><h4>Bạn có thể làm gì tiếp theo</h4><div>{message.followups.map(item => <button type="button" key={item} onClick={() => onFollowup(item)}>{item}</button>)}</div></section>}
    <p className="legal-note">Thông tin mang tính tham khảo. Với vụ việc cụ thể, hãy đối chiếu văn bản gốc hoặc hỏi người có chuyên môn.</p>
  </article>;
}

function AttachmentChip({ item, onRemove }) {
  const label = item.status === "uploading" ? "Đang đọc" : item.verdict === "accepted" ? "Đã xác minh" : item.verdict === "needs_review" ? "Cần kiểm tra" : item.verdict === "rejected" ? "Không sử dụng" : "Sẵn sàng";
  return <div className={`attachment ${item.verdict || item.status || "pending"}`}><span><strong>{item.name}</strong><small>{label}</small></span><button type="button" aria-label={`Bỏ tệp ${item.name}`} onClick={() => onRemove(item.localId || item.id)}>×</button></div>;
}

function App() {
  const [chats, setChats] = useState([]);
  const [chatId, setChatId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [menuChatId, setMenuChatId] = useState(null);
  const abortRef = useRef(null);
  const fileRef = useRef(null);
  const inputRef = useRef(null);
  const endRef = useRef(null);

  async function loadChats() {
    const data = await request(`/api/chats?user_id=${encodeURIComponent(userId)}`);
    setChats(data?.chats || []);
  }

  useEffect(() => { loadChats().catch(() => setError("Không tải được lịch sử trò chuyện.")); }, []);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, busy]);
  useEffect(() => {
    if (!sidebarOpen) return;
    const close = event => { if (event.key === "Escape") setSidebarOpen(false); };
    document.addEventListener("keydown", close);
    document.body.classList.add("nav-open");
    return () => { document.removeEventListener("keydown", close); document.body.classList.remove("nav-open"); };
  }, [sidebarOpen]);

  async function openChat(id) {
    try {
      setError("");
      const data = await request(`/api/chats/${id}?user_id=${encodeURIComponent(userId)}`);
      setChatId(id);
      setMessages((data?.messages || []).map(normalizeMessage));
      setAttachments([]);
      setSidebarOpen(false);
    } catch (err) { setError(friendlyError(err)); }
  }

  function newChat() {
    setChatId(null); setMessages([]); setAttachments([]); setInput(""); setError(""); setSidebarOpen(false); inputRef.current?.focus();
  }

  async function ensureChat() {
    if (chatId) return chatId;
    const data = await request("/api/chats", { method: "POST", body: JSON.stringify({ user_id: userId, title: "Cuộc trò chuyện mới" }) });
    setChatId(data.id);
    return data.id;
  }

  async function sendMessage(value = input) {
    const message = String(value || "").trim();
    if (!message || busy) return;
    setBusy(true); setError(""); setInput("");
    const userMessage = normalizeMessage({ role: "user", content: message });
    setMessages(current => [...current, userMessage]);
    const controller = new AbortController(); abortRef.current = controller;
    try {
      const activeChatId = await ensureChat();
      const acceptedIds = attachments.filter(item => item.id && item.verdict === "accepted").map(item => item.id);
      const controlledSearch = message.toLowerCase() === "tìm thêm nguồn chính thống";
      const data = await request("/api/chat", { method: "POST", body: JSON.stringify({ message, user_id: userId, chat_id: activeChatId, attachment_ids: acceptedIds, language: "vi", controlled_search: controlledSearch }) }, controller.signal);
      setMessages(current => [...current, normalizeMessage({ role: "assistant", content: data.answer, ...data })]);
      setAttachments([]);
      await loadChats();
    } catch (err) {
      setInput(message);
      setMessages(current => current.filter(item => item.id !== userMessage.id));
      setError(friendlyError(err));
    } finally { setBusy(false); abortRef.current = null; inputRef.current?.focus(); }
  }

  async function uploadFile(file) {
    if (!file) return;
    const localId = crypto.randomUUID();
    setAttachments(current => [...current, { localId, name: file.name, status: "uploading" }]);
    try {
      const activeChatId = await ensureChat();
      const form = new FormData(); form.append("file", file); form.append("user_id", userId); form.append("chat_id", activeChatId);
      const data = await request("/api/attachments/upload", { method: "POST", body: form });
      setAttachments(current => current.map(item => item.localId === localId ? { ...data, localId, name: data.name || file.name } : item));
      if (data.verdict === "rejected") setError(data.reason || "Tệp không được sử dụng làm nguồn.");
    } catch (err) { setAttachments(current => current.filter(item => item.localId !== localId)); setError(friendlyError(err)); }
    finally { if (fileRef.current) fileRef.current.value = ""; }
  }

  async function renameChat(id) {
    const title = window.prompt("Tên cuộc trò chuyện mới:");
    if (!title?.trim()) return;
    try { await request(`/api/chats/${id}`, { method: "PATCH", body: JSON.stringify({ user_id: userId, title: title.trim() }) }); await loadChats(); }
    catch (err) { setError(friendlyError(err)); }
    finally { setMenuChatId(null); }
  }

  async function removeChat(id) {
    if (!window.confirm("Xóa cuộc trò chuyện này? Hành động không thể hoàn tác.")) return;
    try { await request(`/api/chats/${id}?user_id=${encodeURIComponent(userId)}`, { method: "DELETE" }); if (chatId === id) newChat(); await loadChats(); }
    catch (err) { setError(friendlyError(err)); }
    finally { setMenuChatId(null); }
  }

  return <div className="app-shell">
    <a className="skip-link" href="#main-content">Bỏ qua điều hướng</a>
    {sidebarOpen && <button className="nav-backdrop" type="button" aria-label="Đóng lịch sử" onClick={() => setSidebarOpen(false)} />}
    <aside className={`sidebar ${sidebarOpen ? "open" : ""}`} aria-label="Lịch sử trò chuyện">
      <div className="brand"><span className="brand-mark">M</span><span><strong>{copy.appName}</strong><small>{copy.tagline}</small></span></div>
      <button className="new-chat" type="button" onClick={newChat}>+ Cuộc trò chuyện mới</button>
      <div className="history-title">Lịch sử</div>
      <nav className="chat-list">{chats.length ? chats.map(chat => <div className={`chat-row ${chat.id === chatId ? "active" : ""}`} key={chat.id}>
        <button type="button" className="chat-open" onClick={() => openChat(chat.id)}><strong>{chat.title}</strong><small>{chat.message_count || 0} tin nhắn</small></button>
        <button type="button" className="chat-menu" aria-label={`Tùy chọn ${chat.title}`} onClick={() => setMenuChatId(menuChatId === chat.id ? null : chat.id)}>⋯</button>
        {menuChatId === chat.id && <div className="chat-actions"><button type="button" onClick={() => renameChat(chat.id)}>Đổi tên</button><button type="button" onClick={() => removeChat(chat.id)}>Xóa</button></div>}
      </div>) : <p className="empty-history">Chưa có cuộc trò chuyện.</p>}</nav>
    </aside>

    <main className="main" id="main-content">
      <header className="topbar"><button className="mobile-menu" type="button" aria-label="Mở lịch sử" aria-expanded={sidebarOpen} onClick={() => setSidebarOpen(true)}>☰</button><div><strong>{copy.appName}</strong><span>{chatId ? chats.find(item => item.id === chatId)?.title || "Cuộc trò chuyện" : copy.tagline}</span></div><button className="compact-new" type="button" onClick={newChat}>Cuộc trò chuyện mới</button></header>
      <section className="conversation" aria-live="polite">
        {!messages.length && <div className="welcome"><span className="welcome-mark">M</span><h1>{copy.welcome}</h1><p>{copy.description}</p><div className="example-grid">{copy.examples.map(item => <button type="button" key={item} onClick={() => sendMessage(item)}>{item}</button>)}</div><p className="safety-copy">{copy.safety}</p></div>}
        {messages.map(message => message.role === "user" ? <article className="message user-message" key={message.id}><p>{message.content}</p></article> : <AssistantMessage message={message} onFollowup={value => { setInput(value); inputRef.current?.focus(); }} key={message.id} />)}
        {busy && <div className="loading" role="status"><span /><span /><span /> Đang đối chiếu nguồn...</div>}
        <div ref={endRef} />
      </section>
      <footer className="composer">
        {error && <div className="error" role="alert"><span>{error}</span><button type="button" onClick={() => setError("")} aria-label="Đóng thông báo">×</button></div>}
        {attachments.length > 0 && <div className="attachments">{attachments.map(item => <AttachmentChip item={item} key={item.localId || item.id} onRemove={id => setAttachments(current => current.filter(value => (value.localId || value.id) !== id))} />)}</div>}
        <div className="composer-box"><label className="sr-only" htmlFor="chat-input">Nội dung câu hỏi</label><textarea id="chat-input" ref={inputRef} value={input} onChange={event => setInput(event.target.value)} onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendMessage(); } }} placeholder="Nhập câu hỏi pháp luật hoặc gửi văn bản để đối chiếu..." rows="1" disabled={busy} />
          <div className="composer-actions"><input ref={fileRef} type="file" accept=".txt,.md,.json,.csv,.pdf,.docx" hidden onChange={event => uploadFile(event.target.files?.[0])} /><button type="button" onClick={() => fileRef.current?.click()} disabled={busy} aria-label="Đính kèm tài liệu">Đính kèm</button>{busy ? <button type="button" className="stop" onClick={() => abortRef.current?.abort()}>Dừng</button> : <button type="button" className="send" disabled={!input.trim()} onClick={() => sendMessage()}>Gửi</button>}</div>
        </div><p className="input-note">Enter để gửi, Shift+Enter để xuống dòng. Không gửi dữ liệu cá nhân không cần thiết.</p>
      </footer>
    </main>
  </div>;
}

createRoot(document.getElementById("root")).render(<React.StrictMode><App /></React.StrictMode>);
