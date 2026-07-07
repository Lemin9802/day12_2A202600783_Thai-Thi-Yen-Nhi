import React, { useEffect, useRef, useState, useMemo } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

// ── API config ────────────────────────────────────────────────────────────────
// VITE_API_BASE="" at build time → same-origin requests, no localhost leak.
const API_BASE = import.meta.env.VITE_API_BASE ?? "";

// API key notes:
// - When MAITHUYLAW_API_KEY is unset on the server, the server allows all
//   same-origin requests (rate limit is the guard). No key needed in JS.
// - When MAITHUYLAW_API_KEY is set to a strong value in production, build
//   the frontend with VITE_MAITHUYLAW_API_KEY=<same value> so the bundle
//   carries a matching key. That key is NOT a secret — it's the public-
//   facing access key for this web UI (rate-limited, domain-guarded).
// - For truly secret admin/external API access, use a separate endpoint
//   that is never called from the browser.
const API_KEY = import.meta.env.VITE_MAITHUYLAW_API_KEY || "";

function apiHeaders(extra = {}) {
  const h = { "Content-Type": "application/json", ...extra };
  if (API_KEY) h["x-api-key"] = API_KEY;
  return h;
}

async function apiFetch(path, options = {}, userId = null) {
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 90000);
  try {
    const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
    const headers = isFormData
      ? { "x-api-key": API_KEY, ...(userId ? { "x-user-id": userId } : {}), ...(options.headers || {}) }
      : apiHeaders({ ...(userId ? { "x-user-id": userId } : {}), ...(options.headers || {}) });
    if (isFormData) delete headers["Content-Type"];
    const res = await fetch(url, { ...options, headers, signal: controller.signal });
    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      throw new Error(`API ${res.status}: ${detail || res.statusText}`);
    }
    const ct = res.headers.get("content-type") || "";
    return ct.includes("application/json") ? res.json() : res.text();
  } finally {
    clearTimeout(timer);
  }
}

// ── User ID (auto, never shown) ───────────────────────────────────────────────
function getOrCreateUserId() {
  const KEY = "maithuylaw_user_id";
  const ex = localStorage.getItem(KEY);
  if (ex) return ex;
  const id = `web-${crypto.randomUUID?.() || Math.random().toString(16).slice(2)}`;
  localStorage.setItem(KEY, id);
  return id;
}

function extractUrls(text) {
  return [...(text.match(/https?:\/\/[^\s)]+/g) || [])].map(u => u.replace(/[.,;!?]+$/, ""));
}

// ── i18n ──────────────────────────────────────────────────────────────────────
const i18n = {
  vi: {
    appName: "MaiThuyLaw AI",
    tagline: "Trợ lý pháp luật ma túy",
    newChat: "Cuộc trò chuyện mới",
    newChatBtn: "Cuộc trò chuyện mới",
    historyLabel: "Lịch sử",
    emptyHistory: "Chưa có cuộc trò chuyện nào.",
    welcomeTitle: "Xin chào, mình là MaiThuyLaw AI",
    welcomeDesc: "Trợ lý hỗ trợ tra cứu và giải thích thông tin pháp luật, chính sách, tin tức chính thống liên quan đến ma túy tại Việt Nam.\nBạn có thể hỏi bằng ngôn ngữ tự nhiên. Mình sẽ cố gắng trả lời dễ hiểu, kèm căn cứ tham khảo từ các nguồn chính thống khi có đủ dữ liệu.",
    examples: [
      "Sử dụng trái phép chất ma túy bị xử lý thế nào?",
      "Tàng trữ ma túy khác gì mua bán ma túy?",
      "Cai nghiện bắt buộc được quy định như thế nào?",
      "Tin chính sách mới về phòng chống ma túy?",
      "Gia đình nên làm gì khi người thân nghiện ma túy?",
      "Khi nào hành vi liên quan ma túy bị xử lý hình sự?",
    ],
    placeholder: "Nhập câu hỏi hoặc dán link nguồn chính thống...",
    send: "Gửi",
    sending: "Đang trả lời...",
    attach: "Đính kèm tài liệu",
    uploaded: "Đã tải:",
    sourcesLabel: "Căn cứ tham khảo",
    followupLabel: "Câu hỏi liên quan",
    evidenceClear: "Căn cứ rõ",
    evidencePartial: "Cần kiểm tra thêm",
    evidenceInsufficient: "Chưa đủ căn cứ",
    evidenceOutOfScope: "Ngoài phạm vi hỗ trợ",
    evidenceSensitive: "Câu hỏi nhạy cảm",
    refusedLabel: "Không thể hỗ trợ",
    errorGeneric: "Đã có lỗi xảy ra. Vui lòng thử lại.",
    rename: "Đổi tên",
    delete: "Xóa",
    save: "Lưu",
    safetyNote: "MaiThuyLaw AI hỗ trợ mục đích tìm hiểu pháp luật và phòng tránh rủi ro. Hệ thống không cung cấp hướng dẫn hỗ trợ thực hiện, che giấu hoặc né tránh hành vi vi phạm pháp luật.",
    sourceTypeLegal: "Văn bản pháp luật",
    sourceTypeNews: "Tin chính thống",
    sourceTypePolicy: "Chính sách",
    sourceTypeOther: "Nguồn tham khảo",
    inputHint: "Enter để gửi · Shift+Enter xuống dòng",
    topbarTitle: "Không gian tra cứu pháp luật ma túy",
  },
  en: {
    appName: "MaiThuyLaw AI",
    tagline: "Drug law assistant",
    newChat: "New conversation",
    newChatBtn: "New conversation",
    historyLabel: "History",
    emptyHistory: "No conversations yet.",
    welcomeTitle: "Hello, I'm MaiThuyLaw AI",
    welcomeDesc: "I help you look up and understand Vietnamese drug-related law, policy, and verified official news.\nAsk freely in natural language. I'll answer clearly and cite official sources when available.",
    examples: [
      "What are the penalties for unlawful drug use?",
      "How does drug possession differ from drug trafficking?",
      "What is compulsory rehabilitation?",
      "Latest drug policy news in Vietnam?",
      "What should families do when a relative is addicted?",
      "When can drug-related behavior lead to criminal liability?",
    ],
    placeholder: "Ask a question or paste an official source link...",
    send: "Send",
    sending: "Thinking...",
    attach: "Attach document",
    uploaded: "Attached:",
    sourcesLabel: "References",
    followupLabel: "Related questions",
    evidenceClear: "Clear evidence",
    evidencePartial: "Needs verification",
    evidenceInsufficient: "Insufficient evidence",
    evidenceOutOfScope: "Out of scope",
    evidenceSensitive: "Sensitive question",
    refusedLabel: "Cannot assist",
    errorGeneric: "Something went wrong. Please try again.",
    rename: "Rename",
    delete: "Delete",
    save: "Save",
    safetyNote: "MaiThuyLaw AI supports legal research and risk awareness only. It does not provide guidance that could facilitate, conceal, or circumvent illegal activity.",
    sourceTypeLegal: "Legal document",
    sourceTypeNews: "Official news",
    sourceTypePolicy: "Policy",
    sourceTypeOther: "Reference",
    inputHint: "Enter to send · Shift+Enter for new line",
    topbarTitle: "Vietnamese drug law research",
  },
};

// ── Helpers ───────────────────────────────────────────────────────────────────
function cx(...args) { return args.filter(Boolean).join(" "); }

function sourceTypeLabel(src, lang) {
  const t = i18n[lang] || i18n.vi;
  const raw = (src.source_type || src.type || "").toLowerCase();
  if (raw.includes("legal")) return { label: t.sourceTypeLegal, cls: "source-type-legal" };
  if (raw.includes("news")) return { label: t.sourceTypeNews, cls: "source-type-news" };
  if (raw.includes("policy") || raw.includes("chinh sach")) return { label: t.sourceTypePolicy, cls: "source-type-policy" };
  return { label: t.sourceTypeOther, cls: "source-type-other" };
}

function evidenceBadgeProps(msg, lang) {
  const t = i18n[lang] || i18n.vi;
  const sources = Array.isArray(msg?.sources) ? msg.sources : [];
  const refused = msg?.refused === true;
  const text = `${msg?.content || ""} ${msg?.reason || ""}`.toLowerCase();

  if (refused) {
    const unsafe =
      text.includes("che giấu") ||
      text.includes("che giau") ||
      text.includes("lách luật") ||
      text.includes("lach luat") ||
      text.includes("né tránh") ||
      text.includes("ne tranh") ||
      text.includes("qua mặt") ||
      text.includes("qua mat") ||
      text.includes("phi tang") ||
      text.includes("hướng dẫn thực hiện") ||
      text.includes("huong dan thuc hien") ||
      text.includes("vi phạm pháp luật") ||
      text.includes("vi pham phap luat") ||
      text.includes("mua bán") ||
      text.includes("mua ban") ||
      text.includes("vận chuyển") ||
      text.includes("van chuyen") ||
      text.includes("sử dụng ma túy") ||
      text.includes("su dung ma tuy") ||
      text.includes("xét nghiệm") ||
      text.includes("xet nghiem");

    if (unsafe) {
      return { label: t.evidenceSensitive, cls: "evidence-badge-sensitive" };
    }

    return { label: t.evidenceOutOfScope, cls: "evidence-badge-out-of-scope" };
  }

  if (!sources.length) {
    return { label: t.evidenceInsufficient, cls: "evidence-badge-insufficient" };
  }

  const hasLegal = sources.some(s => (s.source_type || "").toLowerCase().includes("legal"));
  if (hasLegal && sources.length >= 2) {
    return { label: t.evidenceClear, cls: "evidence-badge-clear" };
  }

  return { label: t.evidencePartial, cls: "evidence-badge-partial" };
}

// ── Markdown-lite renderer ────────────────────────────────────────────────────
function renderMarkdownLite(text, sources = []) {
  if (!text) return null;
  // Clean meta phrases
  const clean = text
    .replace(/\n?Previous conversation context was used to understand the follow-up question\./g, "")
    .replace(/\[(\d+)\]/g, (_, n) => {
      const i = parseInt(n, 10);
      if (i >= 1 && i <= sources.length) return `【${n}】`;
      return "";
    })
    .trim();

  const lines = clean.split("\n");
  const nodes = [];
  let listBuf = [];

  function flushList() {
    if (!listBuf.length) return;
    nodes.push(<ul key={`ul-${nodes.length}`}>{listBuf.map((li, i) => <li key={i}>{inlineFmt(li)}</li>)}</ul>);
    listBuf = [];
  }

  function inlineFmt(s) {
    // bold, italic, citation refs
    const parts = [];
    let rem = s;
    let k = 0;
    while (rem) {
      const bold = rem.match(/\*\*(.+?)\*\*/);
      const cite = rem.match(/【(\d+)】/);
      if (!bold && !cite) { parts.push(<React.Fragment key={k++}>{rem}</React.Fragment>); break; }
      const bIdx = bold ? rem.indexOf(bold[0]) : Infinity;
      const cIdx = cite ? rem.indexOf(cite[0]) : Infinity;
      if (bIdx < cIdx) {
        if (bIdx > 0) parts.push(<React.Fragment key={k++}>{rem.slice(0, bIdx)}</React.Fragment>);
        parts.push(<strong key={k++}>{bold[1]}</strong>);
        rem = rem.slice(bIdx + bold[0].length);
      } else {
        if (cIdx > 0) parts.push(<React.Fragment key={k++}>{rem.slice(0, cIdx)}</React.Fragment>);
        parts.push(<span key={k++} className="citation-inline">[{cite[1]}]</span>);
        rem = rem.slice(cIdx + cite[0].length);
      }
    }
    return parts;
  }

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) { flushList(); nodes.push(<br key={`br-${nodes.length}`} />); continue; }
    if (/^[-*•]\s/.test(trimmed)) { listBuf.push(trimmed.replace(/^[-*•]\s/, "")); continue; }
    if (/^\d+\.\s/.test(trimmed)) { listBuf.push(trimmed.replace(/^\d+\.\s/, "")); continue; }
    if (/^#{1,3}\s/.test(trimmed)) {
      flushList();
      const lvl = (trimmed.match(/^(#{1,3})/)?.[1] || "#").length;
      const htxt = trimmed.replace(/^#{1,3}\s/, "");
      const H = `h${lvl + 2}`;
      nodes.push(<H key={`h-${nodes.length}`}>{inlineFmt(htxt)}</H>);
      continue;
    }
    flushList();
    nodes.push(<p key={`p-${nodes.length}`}>{inlineFmt(trimmed)}</p>);
  }
  flushList();
  return <>{nodes}</>;
}

// ── Follow-up suggestions (derive from answer) ────────────────────────────────
function deriveFollowups(answer, lang) {
  if (!answer || answer.length < 50) return [];
  const t = i18n[lang] || i18n.vi;
  if (lang === "en") {
    return [
      "What are the specific penalties?",
      "Are there any exceptions?",
      "What should I do next?",
    ].slice(0, 2);
  }
  // Simple heuristic: suggest related questions based on keywords in answer
  const suggestions = [];
  if (/hình sự|truy tố|khởi tố/.test(answer)) suggestions.push("Mức hình phạt cụ thể là bao nhiêu?");
  if (/hành chính|phạt tiền/.test(answer)) suggestions.push("Thủ tục xử phạt hành chính như thế nào?");
  if (/cai nghiện|điều trị/.test(answer)) suggestions.push("Quy trình cai nghiện bắt buộc ra sao?");
  if (/gia đình|người thân/.test(answer)) suggestions.push("Gia đình có trách nhiệm pháp lý gì không?");
  if (/tàng trữ|mang theo/.test(answer)) suggestions.push("Tàng trữ bao nhiêu gam thì bị truy tố hình sự?");
  if (/vận chuyển|đường dây/.test(answer)) suggestions.push("Vận chuyển ma túy bị xử lý thế nào?");
  return suggestions.slice(0, 3);
}

function isGreetingOnly(text) {
  const q = (text || "").trim().toLowerCase();
  return [
    "hi",
    "hello",
    "hey",
    "chào",
    "chao",
    "xin chào",
    "xin chao",
    "alo",
    "hi bot",
    "hello bot",
  ].includes(q);
}

function greetingReply(lang) {
  if (lang === "en") {
    return "Hello, I'm MaiThuyLaw AI. I can help you look up and understand Vietnamese drug-related law, policy, and verified official news. You can ask a legal question, paste an official source link, or choose one of the example prompts.";
  }

  return "Xin chào, mình là MaiThuyLaw AI. Mình có thể hỗ trợ bạn tra cứu và giải thích thông tin pháp luật, chính sách, tin tức chính thống liên quan đến ma túy tại Việt Nam. Bạn có thể đặt câu hỏi pháp lý cụ thể, dán link nguồn chính thống, hoặc chọn một câu hỏi gợi ý.";
}

// ── Source card component ─────────────────────────────────────────────────────
function SourceCards({ sources, lang }) {
  const t = i18n[lang] || i18n.vi;
  if (!sources?.length) return null;
  return (
    <div className="sources-section">
      <div className="sources-label">{t.sourcesLabel}</div>
      <div className="source-cards">
        {sources.map((src, i) => {
          const { label, cls } = sourceTypeLabel(src, lang);
          const title = src.title || src.source_title || src.doc_id || `Nguồn ${i + 1}`;
          const url = src.canonical_url || src.url || src.source_url || src.link || null;
          const publisher = src.publisher || src.official_domain || null;
          const card = (
            <>
              <div className="source-card-index">{i + 1}</div>
              <div className="source-card-body">
                <span className="source-card-title">{title}</span>
                <div className="source-card-meta">
                  <span className={cx("source-type-badge", cls)}>{label}</span>
                  {publisher && <span>{publisher}</span>}
                  {url && <span>↗ mở nguồn</span>}
                </div>
              </div>
            </>
          );
          return url
            ? <a key={i} className="source-card" href={url} target="_blank" rel="noreferrer">{card}</a>
            : <div key={i} className="source-card">{card}</div>;
        })}
      </div>
    </div>
  );
}

// ── Message component ─────────────────────────────────────────────────────────
function Message({ msg, lang, onFollowup }) {
  const t = i18n[lang] || i18n.vi;
  const isUser = msg.role === "user";
  const sources = msg.sources || [];
  const refused = msg.refused === true;
  const followups = !isUser && !refused ? deriveFollowups(msg.content, lang) : [];
  const isGreeting = msg.kind === "greeting";
  const { label: evLabel, cls: evCls } = !isUser && !isGreeting ? evidenceBadgeProps(msg, lang) : {};

  return (
    <div className={cx("message", isUser ? "message-user" : "message-assistant")}>
      {isUser ? (
        <div className="message-bubble">{msg.content}</div>
      ) : (
        <div className="message-bubble">
          {refused && (
            <div className="refused-block">
              🚫 {msg.content}
            </div>
          )}
          {!refused && renderMarkdownLite(msg.content, sources)}
          {!isUser && !isGreeting && (
            <div className="evidence-badge" style={{ marginTop: 10 }}>
              <span className={cx("evidence-badge", evCls)}>{evLabel}</span>
            </div>
          )}
          <SourceCards sources={sources} lang={lang} />
          {followups.length > 0 && (
            <div className="followup-section">
              <div className="followup-label">{t.followupLabel}</div>
              <div className="followup-chips">
                {followups.map((f, i) => (
                  <button key={i} className="followup-chip" onClick={() => onFollowup(f)}>{f}</button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── App ───────────────────────────────────────────────────────────────────────
const ACTIVE_CHAT_KEY = "maithuylaw_active_chat_id";
const DEFAULT_TITLE_VI = "Cuộc trò chuyện mới";
const DEFAULT_TITLE_EN = "New conversation";

function App() {
  const [userId] = useState(getOrCreateUserId);
  const [lang, setLang] = useState(localStorage.getItem("maithuylaw_language") || "vi");
  const t = i18n[lang] || i18n.vi;

  const [chats, setChats] = useState([]);
  const [activeChatId, setActiveChatId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState([]);
  const [busy, setBusy] = useState(false);
  const [loadingChats, setLoadingChats] = useState(true);
  const [error, setError] = useState("");
  const [editingChatId, setEditingChatId] = useState(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const fileRef = useRef(null);
  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  const defaultTitle = lang === "en" ? DEFAULT_TITLE_EN : DEFAULT_TITLE_VI;

  useEffect(() => { localStorage.setItem("maithuylaw_language", lang); }, [lang]);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [messages, busy]);

  useEffect(() => { loadChats(); }, []);

  // ── Chat management ──
  async function loadChats() {
    setLoadingChats(true);
    try {
      const data = await apiFetch(`/api/chats?user_id=${encodeURIComponent(userId)}`, {}, userId);
      const items = Array.isArray(data) ? data : data.chats || [];
      setChats(items);
      const hashMatch = window.location.hash.match(/chat=([^&]+)/);
      const preferred = hashMatch?.[1] || localStorage.getItem(ACTIVE_CHAT_KEY);
      const found = preferred ? items.find(c => c.id === preferred) : null;
      if (found) {
        try {
          const detail = await apiFetch(`/api/chats/${found.id}?user_id=${encodeURIComponent(userId)}`, {}, userId);
          if ((detail.messages || []).length > 0) {
            setActiveChatId(found.id);
            localStorage.setItem(ACTIVE_CHAT_KEY, found.id);
            window.history.replaceState(null, "", `#chat=${found.id}`);
            setMessages(detail.messages || []);
            return;
          }
        } catch {}
      }
      startNewChat();
    } catch {
      setError(t.errorGeneric);
    } finally {
      setLoadingChats(false);
    }
  }

  function startNewChat() {
    setActiveChatId(null);
    setMessages([]);
    setAttachments([]);
    setError("");
    setEditingChatId(null);
    localStorage.removeItem(ACTIVE_CHAT_KEY);
    window.history.replaceState(null, "", "#new");
    setSidebarOpen(false);
  }

  async function createChat() {
    const created = await apiFetch("/api/chats", {
      method: "POST",
      headers: apiHeaders(),
      body: JSON.stringify({ user_id: userId, title: defaultTitle }),
    }, userId);
    setChats(prev => [created, ...prev.filter(c => c.id !== created.id)]);
    setActiveChatId(created.id);
    localStorage.setItem(ACTIVE_CHAT_KEY, created.id);
    window.history.replaceState(null, "", `#chat=${created.id}`);
    return created;
  }

  async function openChat(chatId) {
    const data = await apiFetch(`/api/chats/${chatId}?user_id=${encodeURIComponent(userId)}`, {}, userId);
    setActiveChatId(chatId);
    localStorage.setItem(ACTIVE_CHAT_KEY, chatId);
    window.history.replaceState(null, "", `#chat=${chatId}`);
    setMessages(data.messages || []);
    setAttachments([]);
    setError("");
    setSidebarOpen(false);
  }

  async function renameChat(chatId, title) {
    const clean = title.trim();
    if (!clean) return;
    const updated = await apiFetch(`/api/chats/${chatId}`, {
      method: "PATCH",
      headers: apiHeaders(),
      body: JSON.stringify({ user_id: userId, title: clean }),
    }, userId);
    setChats(prev => prev.map(c => c.id === chatId ? { ...c, title: updated.title || clean } : c));
  }

  async function deleteChat(chatId) {
    await apiFetch(`/api/chats/${chatId}?user_id=${encodeURIComponent(userId)}`, { method: "DELETE" }, userId);
    const next = chats.filter(c => c.id !== chatId);
    setChats(next);
    if (activeChatId === chatId) {
      next.length ? await openChat(next[0].id) : startNewChat();
    }
  }

  async function maybeGenerateTitle(chatId, firstMessage) {
    const chat = chats.find(c => c.id === chatId);
    const cur = chat?.title || "";
    if (cur && cur !== DEFAULT_TITLE_VI && cur !== DEFAULT_TITLE_EN) return;
    try {
      const data = await apiFetch(`/api/chats/${chatId}/generate-title`, {
        method: "POST",
        headers: apiHeaders(),
        body: JSON.stringify({ user_id: userId, message: firstMessage, language: lang }),
      }, userId);
      if (data.title) {
        setChats(prev => prev.map(c => c.id === chatId ? { ...c, title: data.title } : c));
      }
    } catch {}
  }

  // ── Send message ──
  async function sendMessage(overrideText) {
    const text = (overrideText || input).trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);
    setError("");
    let chatId = activeChatId;
    if (!chatId) {
      const created = await createChat();
      chatId = created.id;
    }
    const prevMessages = messages;
    setMessages(prev => [...prev, { id: `user-${Date.now()}`, role: "user", content: text, sources: [] }]);

    if (isGreetingOnly(text)) {
      setMessages(prev => [...prev, {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content: greetingReply(lang),
        sources: [],
        refused: false,
        kind: "greeting",
      }]);
      setBusy(false);
      return;
    }

    try {
      const links = extractUrls(text);
      const attachmentIds = attachments.map(a => a.id).filter(Boolean);
      const data = await apiFetch("/api/chat", {
        method: "POST",
        headers: apiHeaders(),
        body: JSON.stringify({ user_id: userId, chat_id: chatId, message: text, links, attachment_ids: attachmentIds, language: lang }),
      }, userId);
      setMessages(prev => [...prev, {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content: data.answer || "",
        sources: data.sources || [],
        refused: data.refused || false,
        reason: data.reason || "",
      }]);
      setAttachments([]);
      if (prevMessages.filter(m => m.role === "user").length === 0) {
        await maybeGenerateTitle(chatId, text);
      }
      setChats(prev => prev.map(c => c.id === chatId ? { ...c, updated_at: new Date().toISOString() } : c));
    } catch (err) {
      setError(t.errorGeneric);
      setMessages(prev => [...prev, { id: `err-${Date.now()}`, role: "assistant", content: t.errorGeneric, sources: [], refused: false }]);
    } finally {
      setBusy(false);
    }
  }

  // ── Upload file ──
  async function uploadFile(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setError("");
    let chatId = activeChatId;
    if (!chatId) { const c = await createChat(); chatId = c.id; }
    const form = new FormData();
    form.append("file", file);
    form.append("user_id", userId);
    form.append("chat_id", chatId);
    try {
      const uploadHeaders = { "x-user-id": userId };
      if (API_KEY) uploadHeaders["x-api-key"] = API_KEY;
      const data = await apiFetch("/api/attachments/upload", {
        method: "POST",
        headers: uploadHeaders,
        body: form,
      });
      setAttachments(prev => [...prev, data]);
    } catch { setError(t.errorGeneric); }
  }

  function switchLang(l) {
    if (l === lang) return;
    localStorage.setItem("maithuylaw_language", l);
    window.location.reload();
  }

  const activeChat = useMemo(() => chats.find(c => c.id === activeChatId) || null, [chats, activeChatId]);

  // ── Render ──
  return (
    <div className="layout">
      {/* ── Sidebar ── */}
      <aside className={cx("sidebar", sidebarOpen && "mobile-open")}>
        <div className="sidebar-header">
          <div className="brand" onClick={startNewChat} style={{ cursor: "pointer" }}>
            <div className="brand-logo">
              <svg viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round">
                <path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>
              </svg>
            </div>
            <div>
              <div className="brand-name">{t.appName}</div>
              <div className="brand-tagline">{t.tagline}</div>
            </div>
          </div>
          <button className="new-chat-btn" onClick={startNewChat}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="M12 5v14M5 12h14"/>
            </svg>
            {t.newChatBtn}
          </button>
        </div>

        <div className="sidebar-section-label">{t.historyLabel}</div>
        <div className="chat-history">
          {loadingChats && <div className="chat-history-empty">...</div>}
          {!loadingChats && !chats.length && <div className="chat-history-empty">{t.emptyHistory}</div>}
          {chats.map(c => (
            <div key={c.id}>
              {editingChatId === c.id ? (
                <div style={{ padding: "4px 8px", display: "flex", gap: 4 }}>
                  <input
                    value={editingTitle}
                    onChange={e => setEditingTitle(e.target.value)}
                    autoFocus
                    style={{ flex: 1, fontSize: 13, border: "1px solid #c3d9f7", borderRadius: 6, padding: "4px 8px" }}
                    onKeyDown={async e => {
                      if (e.key === "Enter") { await renameChat(c.id, editingTitle); setEditingChatId(null); }
                      if (e.key === "Escape") setEditingChatId(null);
                    }}
                  />
                  <button onClick={async () => { await renameChat(c.id, editingTitle); setEditingChatId(null); }}
                    style={{ fontSize: 12, padding: "4px 8px", background: "#1a6fdb", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer" }}>
                    {t.save}
                  </button>
                </div>
              ) : (
                <button
                  className={cx("chat-history-item", c.id === activeChatId && "active")}
                  onClick={() => openChat(c.id)}
                  onDoubleClick={() => { setEditingChatId(c.id); setEditingTitle(c.title || ""); }}
                  title={`${t.rename}: double-click`}
                >
                  {c.title || defaultTitle}
                </button>
              )}
            </div>
          ))}
        </div>

        <div className="sidebar-footer">
          <div className="safety-note">{t.safetyNote}</div>
        </div>
      </aside>

      {/* ── Main ── */}
      <div className="main">
        {/* Topbar */}
        <div className="chat-topbar">
          <button className="menu-btn" onClick={() => setSidebarOpen(o => !o)}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 12h18M3 6h18M3 18h18"/>
            </svg>
          </button>
          <div className="chat-topbar-title">
            {activeChat?.title || t.topbarTitle}
          </div>
          <div className="lang-toggle">
            <button className={cx("lang-btn", lang === "vi" && "active")} onClick={() => switchLang("vi")}>VI</button>
            <button className={cx("lang-btn", lang === "en" && "active")} onClick={() => switchLang("en")}>EN</button>
          </div>
        </div>

        {/* Messages */}
        <div className="messages">
          {messages.length === 0 && !busy && (
            <div className="welcome">
              <div className="welcome-logo">
                <svg viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" style={{ width: 30, height: 30 }}>
                  <path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>
                </svg>
              </div>
              <h1 className="welcome-title">{t.welcomeTitle}</h1>
              <p className="welcome-desc">
                {t.welcomeDesc.split("\n").map((line, i) => (
                  <React.Fragment key={i}>{line}{i === 0 && <br />}</React.Fragment>
                ))}
              </p>
              <div className="example-prompts">
                {t.examples.map((ex, i) => (
                  <button key={i} className="example-prompt-btn" onClick={() => sendMessage(ex)}>
                    {ex}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map(msg => (
            <Message key={msg.id} msg={msg} lang={lang} onFollowup={text => {
              setInput(text);
              inputRef.current?.focus();
            }} />
          ))}

          {busy && (
            <div className="message message-assistant">
              <div className="loading-bubble">
                <div className="loading-dots">
                  <div className="loading-dot" /><div className="loading-dot" /><div className="loading-dot" />
                </div>
                <span>{t.sending}</span>
              </div>
            </div>
          )}

          {error && !busy && (
            <div className="message message-assistant">
              <div className="error-block">{error}</div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Input area */}
        <div className="input-area">
          {attachments.length > 0 && (
            <div className="attachment-chips">
              {attachments.map(a => (
                <div key={a.id || a.name} className="attachment-chip">
                  📎 {a.name || a.filename}
                  <button onClick={() => setAttachments(prev => prev.filter(x => (x.id || x.name) !== (a.id || a.name)))}>×</button>
                </div>
              ))}
            </div>
          )}
          <div className="input-wrap">
            <textarea
              ref={inputRef}
              className="chat-input"
              value={input}
              placeholder={t.placeholder}
              rows={1}
              onChange={e => {
                setInput(e.target.value);
                e.target.style.height = "auto";
                e.target.style.height = Math.min(e.target.scrollHeight, 160) + "px";
              }}
              onKeyDown={e => {
                if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
              }}
            />
            <div className="input-actions">
              <button className="attach-btn" onClick={() => fileRef.current?.click()} title={t.attach}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/>
                </svg>
              </button>
              <input ref={fileRef} type="file" hidden onChange={uploadFile} accept=".pdf,.doc,.docx,.txt,.md" />
              <button
                className="send-btn"
                disabled={busy || !input.trim()}
                onClick={() => sendMessage()}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/>
                </svg>
              </button>
            </div>
          </div>
          <div className="input-hint">{t.inputHint}</div>
        </div>
      </div>

      {/* Mobile overlay */}
      {sidebarOpen && (
        <div onClick={() => setSidebarOpen(false)}
          style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.3)", zIndex: 99 }} />
      )}
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
