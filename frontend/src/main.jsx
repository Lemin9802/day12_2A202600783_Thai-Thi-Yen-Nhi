import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8020";

const API_KEY = import.meta.env.VITE_MAITHUYLAW_API_KEY || "dev-maithuylaw-key";

function apiHeaders(extra = {}, includeJson = true) {
  const headers = includeJson
    ? { "Content-Type": "application/json" }
    : {};

  return {
    ...headers,
    "x-api-key": API_KEY,
    ...extra,
  };
}

async function apiFetch(path, options = {}, userOrTimeout = undefined, maybeTimeoutMs = 90000) {
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;

  let timeoutMs = 90000;
  let userId = null;

  if (typeof userOrTimeout === "number") {
    timeoutMs = userOrTimeout;
  } else if (typeof userOrTimeout === "string") {
    userId = userOrTimeout;
  }

  if (typeof maybeTimeoutMs === "number") {
    timeoutMs = maybeTimeoutMs;
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const body = options.body;
    const isFormData = typeof FormData !== "undefined" && body instanceof FormData;
    const extraHeaders = {
      ...(userId ? { "x-user-id": userId } : {}),
      ...(options.headers || {}),
    };

    const headers = apiHeaders(extraHeaders, !isFormData);
    if (isFormData) delete headers["Content-Type"];

    const response = await fetch(url, {
      ...options,
      headers,
      signal: controller.signal,
    });

    if (!response.ok) {
      const detail = await response.text().catch(() => "");
      throw new Error(`API ${response.status}: ${detail || response.statusText}`);
    }

    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      return await response.json();
    }

    return await response.text();
  } finally {
    clearTimeout(timer);
  }
}


const DEFAULT_TITLE_VI = "Cuộc trò chuyện mới";
const DEFAULT_TITLE_EN = "New conversation";
const ACTIVE_CHAT_KEY = "maithuylaw_active_chat_id";

const i18n = {
  vi: {
    appName: "MaiThuyLaw AI",
    brandSub: "Trợ lý thông tin pháp luật",
    topTitle: "Không gian tra cứu pháp luật",
    topSub: "Phạm vi: pháp luật, chính sách và nguồn tin chính thống về ma túy tại Việt Nam.",
    newChat: "Cuộc trò chuyện mới",
    newChatBtn: "Tạo cuộc trò chuyện",
    history: "Lịch sử trò chuyện",
    emptyHistory: "Chưa có cuộc trò chuyện nào.",
    heroTitle1: "Tra cứu pháp luật,",
    heroTitle2: "chính sách và tin tức về ma túy",
    heroSub: "Hỏi đáp trực tiếp, dán link hoặc tải file lên để kiểm tra nguồn và tóm tắt.",
    sample1: "Tóm tắt quy định về cơ sở cai nghiện bắt buộc",
    sample2: "Tin chính thống mới nhất về phòng chống ma túy",
    sample3: "Kiểm tra một đường dẫn hoặc tài liệu pháp luật",
    placeholder: "Nhập câu hỏi, dán link nguồn chính thống hoặc hỏi tiếp nội dung trước đó...",
    send: "Gửi",
    sending: "Đang trả lời...",
    attach: "Đính kèm",
    uploaded: "Đã tải lên",
    sources: "Nguồn tham khảo",
    moreSources: "nguồn khác",
    rename: "Đổi tên",
    delete: "Xóa",
    cancel: "Hủy",
    save: "Lưu",
    language: "Ngôn ngữ",
    theme: "Giao diện",
    dark: "Tối",
    light: "Sáng",
    realtimeNotice:
      "Mình sẽ ưu tiên nguồn chính thống và nguồn đã được kiểm chứng khi cần tra cứu thông tin mới.",
    technicalError:
      "Xin lỗi, hiện có sự cố kỹ thuật tạm thời. Bạn vui lòng thử lại sau ít phút.",
    userAvatar: "Bạn",
    aiAvatar: "AI",
  },
  en: {
    appName: "MaiThuyLaw AI",
    brandSub: "Legal information assistant",
    topTitle: "Legal research workspace",
    topSub:
      "Scope: Vietnamese law, policy, and verified official sources on drug-related matters.",
    newChat: "New conversation",
    newChatBtn: "New conversation",
    history: "Chat history",
    emptyHistory: "No conversations yet.",
    heroTitle1: "Research Vietnamese law,",
    heroTitle2: "policy and official drug-related news",
    heroSub:
      "Ask questions, paste links, or upload files to check sources and summarize verified information.",
    sample1: "Summarize compulsory rehabilitation rules",
    sample2: "Latest official drug prevention updates",
    sample3: "Review a legal source or document",
    placeholder:
      "Ask a question, paste an official link, or continue the previous topic...",
    send: "Send",
    sending: "Thinking...",
    attach: "Attach",
    uploaded: "Uploaded",
    sources: "References",
    moreSources: "more sources",
    rename: "Rename",
    delete: "Delete",
    cancel: "Cancel",
    save: "Save",
    language: "Language",
    theme: "Theme",
    dark: "Dark",
    light: "Light",
    realtimeNotice:
      "I will prioritize official and verified sources when current information is needed.",
    technicalError:
      "Sorry, a temporary technical issue occurred. Please try again shortly.",
    userAvatar: "You",
    aiAvatar: "AI",
  },
};

function getOrCreateUserId() {
  const key = "maithuylaw_user_id";
  const existing = localStorage.getItem(key);
  if (existing) return existing;

  const id = `web-${crypto.randomUUID?.() || Math.random().toString(16).slice(2)}`;
  localStorage.setItem(key, id);
  return id;
}

function cx(...items) {
  return items.filter(Boolean).join(" ");
}


function BrandLogo({ className = "", title = "MaiThuyLaw AI" }) {
  
  // CHAT_HISTORY_LOADING_GUARD
  useEffect(() => {
    const timer = setTimeout(() => {
      try { setChatsLoading(false); } catch {}
      try { setIsChatsLoading(false); } catch {}
      try { setLoadingChats(false); } catch {}
    }, 12000);

    return () => clearTimeout(timer);
  }, []);

return (
    <span className={`brand-logo ${className}`} aria-label={title}>
      <img src="/maithuylaw-logo.png" alt={title} />
    </span>
  );
}


function LogoMark({ className = "" }) {
  return (
    <div className={className} aria-hidden="true">
      <svg viewBox="0 0 64 64" role="img" className="logo-svg">
        <path className="logo-stem" d="M32 12v38" />
        <path className="logo-top" d="M18 22h28" />
        <path className="logo-arm logo-arm-left" d="M32 22 18 30" />
        <path className="logo-arm logo-arm-right" d="M32 22 46 30" />
        <path className="logo-bowl" d="M12 34h14c-.8 5.5-3.6 8.5-7 8.5S12.8 39.5 12 34Z" />
        <path className="logo-bowl" d="M38 34h14c-.8 5.5-3.6 8.5-7 8.5S38.8 39.5 38 34Z" />
        <path className="logo-base" d="M22 52h20" />
      </svg>
    </div>
  );
}

function extractUrls(text) {
  return Array.from(text.matchAll(/https?:\/\/[^\s)]+/gi)).map((m) =>
    m[0].replace(/[.,;!?]+$/, "")
  );
}

function normalizeMessage(message) {
  return {
    id: message.id || `${message.role || "assistant"}-${Date.now()}-${Math.random()}`,
    role: message.role || "assistant",
    content: message.content || message.answer || message.message || "",
    sources: message.sources || [],
    created_at: message.created_at,
  };
}

function sourceTypeLabel(source, lang) {
  const raw = String(
    source.source_type || source.type || source.kind || source.category || ""
  ).toLowerCase();

  if (raw.includes("legal")) return lang === "en" ? "Legal" : "Pháp luật";
  if (raw.includes("news")) return lang === "en" ? "News" : "Tin tức";
  if (raw.includes("realtime")) return lang === "en" ? "Current source" : "Nguồn mới";
  if (raw.includes("attachment")) return lang === "en" ? "Attachment" : "Đính kèm";
  return lang === "en" ? "Source" : "Nguồn";
}

function sourceTitle(source, fallback) {
  return (
    source.title ||
    source.name ||
    source.filename ||
    source.source ||
    source.doc_id ||
    source.url ||
    fallback
  );
}


function sourcePublisherLabel(source = {}) {
  const publisher = source.publisher || source.official_domain || "";
  if (/vbpl\.vn/i.test(String(source.url || source.canonical_url || source.source_url || source.link || publisher))) {
    return "Cơ sở dữ liệu quốc gia về văn bản pháp luật (VBPL)";
  }
  return publisher || "Nguồn chính thức";
}

function getSourceUrl(source) {
  if (!source) return "";
  return (
    source.url ||
    source.href ||
    source.link ||
    source.source_url ||
    source.web_url ||
    source.metadata?.url ||
    source.metadata?.source_url ||
    source.metadata?.link ||
    ""
  );
}

function buildSourceMap(sources = []) {
  const map = {};
  sources.forEach((source, index) => {
    const key = `S${index + 1}`;
    map[key] = {
      ...source,
      _title: sourceTitle(source, key),
      _url: getSourceUrl(source),
      _publisherLabel: sourcePublisherLabel(source),
    };
  });
  return map;
}


function cleanAssistantText(text) {
  return String(text || "")
    .replace(/\n?_Ngữ cảnh hội thoại trước đó đã được dùng để hiểu câu hỏi tiếp theo\._/g, "")
    .replace(/\n?Previous conversation context was used to understand the follow-up question\./g, "")
    .trim();
}


function normalizeCitationText(text, sources = []) {
  const sourceCount = Array.isArray(sources) ? sources.length : 0;
  let output = String(text || "");

  const groupPattern = /\[(?:S\d+\s*(?:,\s*S\d+\s*)*)\]/g;

  if (sourceCount <= 0) {
    return output.replace(groupPattern, "");
  }

  output = output.replace(groupPattern, (token) => {
    const nums = [...token.matchAll(/S(\d+)/g)].map((m) => Number(m[1]));

    if (sourceCount === 1) {
      return "[S1]";
    }

    const valid = [];
    nums.forEach((n) => {
      if (n >= 1 && n <= sourceCount && !valid.includes(n)) valid.push(n);
    });

    if (!valid.length) return "";
    return `[${valid.map((n) => `S${n}`).join(", ")}]`;
  });

  if (sourceCount === 1) {
    output = output.replace(/\[S1\](?:\s*,\s*\[S1\])+/g, "[S1]");
    output = output.replace(/(\[S1\]\s*){2,}/g, "[S1] ");
  }

  output = output.replace(/\s+([,.])/g, "$1");
  output = output.replace(/,\s*,/g, ",");
  return output;
}


function renderReferenceCards(sources = []) {
  const sourceMap = buildSourceMap(sources);
  const entries = Object.entries(sourceMap);

  if (!entries.length) return null;

  return (
    <div className="reference-card-list">
      {entries.map(([key, source]) => {
        const content = (
          <>
            <span className="reference-card-key">[{key}]</span>
            <span className="reference-card-main">
              <span className="reference-card-title">{source._title}</span>
              <span className="reference-card-publisher">{source._publisherLabel || "Nguồn chính thức"}</span>
            </span>
          </>
        );

        return source._url ? (
          <a key={key} className="reference-card" href={source._url} target="_blank" rel="noreferrer" title={source._url}>
            {content}
          </a>
        ) : (
          <div key={key} className="reference-card">
            {content}
          </div>
        );
      })}
    </div>
  );
}

function renderMarkdownLite(text, sources = []) {
  text = cleanAssistantText(text);
  if (!text) return null;

  const sourceMap = buildSourceMap(sources);
  text = normalizeCitationText(text, sources);
  const lines = text.split("\n");
  const nodes = [];
  let list = [];

  const flushList = () => {
    if (!list.length) return;
    nodes.push(
      <ul key={`ul-${nodes.length}`}>
        {list.map((item, index) => (
          <li key={index}>{inlineFormat(item, sourceMap)}</li>
        ))}
      </ul>
    );
    list = [];
  };

  lines.forEach((raw, idx) => {
    const line = raw.trim();

    if (!line) {
      flushList();
      return;
    }

    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      flushList();
      const level = Math.min(heading[1].length, 4);
      const Tag = `h${level}`;
      nodes.push(<Tag key={idx}>{inlineFormat(heading[2], sourceMap)}</Tag>);
      return;
    }

    if (/^[-*]\s+/.test(line)) {
      list.push(line.replace(/^[-*]\s+/, ""));
      return;
    }

    flushList();
    nodes.push(<p key={idx}>{inlineFormat(line, sourceMap)}</p>);
  });

  flushList();
  return nodes;
}

function inlineFormat(text, sourceMap = {}) {
  const parts = [];
  const regex = /(\*\*[^*]+\*\*|\*[^*\n]+\*|\[[SA]\d+\])/g;
  let last = 0;
  let match;

  while ((match = regex.exec(text))) {
    if (match.index > last) parts.push(text.slice(last, match.index));

    const token = match[0];

    if (token.startsWith("**")) {
      parts.push(<strong key={`${match.index}-b`}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("*")) {
      parts.push(<em key={`${match.index}-i`}>{token.slice(1, -1)}</em>);
    } else {
      const refKey = token.slice(1, -1);
      const source = sourceMap[refKey];
      const tooltip = source
        ? `${source._title}${source._url ? " — " + source._url : ""}`
        : token;

      if (source?._url) {
        parts.push(
          <a
            className="cite-token cite-link"
            key={`${match.index}-c`}
            href={source._url}
            title={tooltip}
            target="_blank"
            rel="noreferrer"
          >
            {token}
          </a>
        );
      } else {
        parts.push(
          <span className="cite-token" key={`${match.index}-c`} title={tooltip}>
            {token}
          </span>
        );
      }
    }

    last = regex.lastIndex;
  }

  if (last < text.length) parts.push(text.slice(last));
  return parts;
}
function App() {
  const [userId] = useState(getOrCreateUserId);
  const [language, setLanguage] = useState(
    localStorage.getItem("maithuylaw_language") || "vi"
  );
  const [theme, setTheme] = useState(localStorage.getItem("maithuylaw_theme") || "dark");

  const t = i18n[language] || i18n.vi;
  const defaultTitle = language === "en" ? DEFAULT_TITLE_EN : DEFAULT_TITLE_VI;

  const [chats, setChats] = useState([]);
  const [activeChatId, setActiveChatId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [editingChatId, setEditingChatId] = useState(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [error, setError] = useState("");

  const fileRef = useRef(null);
  const bottomRef = useRef(null);

  const activeChat = useMemo(
    () => chats.find((chat) => chat.id === activeChatId) || null,
    [chats, activeChatId]
  );

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("maithuylaw_theme", theme);
  }, [theme]);

  useEffect(() => {
    localStorage.setItem("maithuylaw_language", language);
  }, [language]);

  useEffect(() => {
    loadChats();
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);

  async function loadChats() {
    setLoading(true);
    setError("");

    try {
      const data = await apiFetch(`/api/chats?user_id=${encodeURIComponent(userId)}`, {}, userId);
      const items = Array.isArray(data) ? data : data.chats || [];

      setChats(items);

      const hashMatch = window.location.hash.match(/chat=([^&]+)/);
      const preferredChatId = hashMatch?.[1] || localStorage.getItem(ACTIVE_CHAT_KEY);
      const preferredChat = preferredChatId
        ? items.find((chat) => chat.id === preferredChatId)
        : null;

      if (preferredChat) {
        try {
          const data = await apiFetch(
            `/api/chats/${preferredChat.id}?user_id=${encodeURIComponent(userId)}`,
            {},
            userId
          );

          if ((data.messages || []).length > 0) {
            setActiveChatId(preferredChat.id);
            localStorage.setItem(ACTIVE_CHAT_KEY, preferredChat.id);
            window.history.replaceState(null, "", `#chat=${preferredChat.id}`);
            setMessages((data.messages || []).map(normalizeMessage));
            setAttachments([]);
            return;
          }
        } catch (err) {
          console.warn("Could not restore previous chat:", err);
        }
      }

      startLocalNewChat();
    } catch (err) {
      console.error(err);
      if (window.location.hash === "#new") {
        startLocalNewChat();
      } else {
        setError(t.technicalError);
      }
    } finally {
      setLoading(false);
    }
  }


  function startLocalNewChat() {
    setError("");
    setActiveChatId(null);
    localStorage.removeItem(ACTIVE_CHAT_KEY);
    window.history.replaceState(null, "", "#new");
    setMessages([]);
    setAttachments([]);
    setEditingChatId(null);
    setEditingTitle("");
  }

  function handleBrandClick() {
    startLocalNewChat();
  }

  async function createChat() {
    setError("");
    const created = await apiFetch(
      "/api/chats",
      {
        method: "POST",
        headers: apiHeaders(),
        body: JSON.stringify({ user_id: userId, title: defaultTitle }),
      },
      userId
    );

    setChats((prev) => [created, ...prev.filter((chat) => chat.id !== created.id)]);
    setActiveChatId(created.id);
    localStorage.setItem(ACTIVE_CHAT_KEY, created.id);
    window.history.replaceState(null, "", `#chat=${created.id}`);
    setMessages([]);
    setAttachments([]);
    return created;
  }

  async function openChat(chatId, clearError = true) {
    if (clearError) setError("");

    const data = await apiFetch(
      `/api/chats/${chatId}?user_id=${encodeURIComponent(userId)}`,
      {},
      userId
    );

    setActiveChatId(chatId);
    localStorage.setItem(ACTIVE_CHAT_KEY, chatId);
    window.history.replaceState(null, "", `#chat=${chatId}`);
    setMessages((data.messages || []).map(normalizeMessage));
    setAttachments([]);
  }

  async function renameChat(chatId, title) {
    const clean = title.trim();
    if (!clean) return;

    const updated = await apiFetch(
      `/api/chats/${chatId}`,
      {
        method: "PATCH",
        headers: apiHeaders(),
        body: JSON.stringify({ user_id: userId, title: clean }),
      },
      userId
    );

    setChats((prev) =>
      prev.map((chat) => (chat.id === chatId ? { ...chat, title: updated.title || clean } : chat))
    );
  }

  async function deleteChat(chatId) {
    await apiFetch(`/api/chats/${chatId}?user_id=${encodeURIComponent(userId)}`, {
      method: "DELETE",
    }, userId);

    const next = chats.filter((chat) => chat.id !== chatId);
    setChats(next);

    if (activeChatId === chatId) {
      if (next.length) {
        await openChat(next[0].id);
      } else {
        startLocalNewChat();
      }
    }
  }

  async function maybeGenerateTitle(chatId, firstUserMessage) {
    const chat = chats.find((item) => item.id === chatId);
    const currentTitle = chat?.title || "";

    if (
      currentTitle &&
      currentTitle !== DEFAULT_TITLE_VI &&
      currentTitle !== DEFAULT_TITLE_EN &&
      currentTitle !== defaultTitle
    ) {
      return;
    }

    try {
      const data = await apiFetch(
        `/api/chats/${chatId}/generate-title`,
        {
          method: "POST",
          headers: apiHeaders(),
          body: JSON.stringify({
            user_id: userId,
            message: firstUserMessage,
            language,
          }),
        },
        userId
      );

      if (data.title) {
        setChats((prev) =>
          prev.map((item) =>
            item.id === chatId
              ? { ...item, title: data.title, updated_at: new Date().toISOString() }
              : item
          )
        );
      }
    } catch (err) {
      console.warn("Title generation skipped:", err);
    }
  }

  async function sendMessage(sampleText) {
    const text = (sampleText || input).trim();
    if (!text || busy) return;

    setInput("");
    setBusy(true);
    setError("");

    let chatId = activeChatId;
    if (!chatId) {
      const created = await createChat();
      chatId = created.id;
    }

    const previousMessages = messages;
    const userMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: text,
      sources: [],
    };

    setMessages((prev) => [...prev, userMessage]);

    try {
      const links = extractUrls(text);
      const attachmentIds = attachments.map((item) => item.id).filter(Boolean);

      const data = await apiFetch(
        "/api/chat",
        {
          method: "POST",
          headers: apiHeaders(),
          body: JSON.stringify({
            user_id: userId,
            chat_id: chatId,
            message: text,
            links,
            attachment_ids: attachmentIds,
            language,
          }),
        },
        userId
      );

      const assistantMessage = {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content: data.answer || "",
        sources: data.sources || [],
      };

      setMessages((prev) => [...prev, assistantMessage]);
      setAttachments([]);

      const isFirstUserMessage =
        previousMessages.filter((msg) => msg.role === "user").length === 0;

      if (isFirstUserMessage) {
        await maybeGenerateTitle(chatId, text);
      }

      setChats((prev) =>
        prev.map((chat) =>
          chat.id === chatId ? { ...chat, updated_at: new Date().toISOString() } : chat
        )
      );
    } catch (err) {
      console.error(err);
      setError(t.technicalError);
      setMessages((prev) => [
        ...prev,
        {
          id: `assistant-error-${Date.now()}`,
          role: "assistant",
          content: t.technicalError,
          sources: [],
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  async function uploadFile(event) {
    const file = event.target.files?.[0];
    event.target.value = "";

    if (!file) return;

    setError("");

    let chatId = activeChatId;
    if (!chatId) {
      const created = await createChat();
      chatId = created.id;
    }

    const form = new FormData();
    form.append("file", file);
    form.append("user_id", userId);
    form.append("chat_id", chatId);

    try {
      const data = await apiFetch(`/api/attachments/upload`, {
        method: "POST",
        headers: {
          "x-api-key": API_KEY,
          "x-user-id": userId,
        },
        body: form,
      });
      setAttachments((prev) => [...prev, data]);
    } catch (err) {
      console.error(err);
      setError(t.technicalError);
    }
  }

  function switchLanguage(nextLanguage) {
    if (nextLanguage === language) return;
    localStorage.setItem("maithuylaw_language", nextLanguage);
    window.location.reload();
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <button className="brand-logo-button" onClick={handleBrandClick} title={t.newChatBtn}><BrandLogo className="brand-logo-sidebar" /></button>
          <div>
            <div className="brand-name">{t.appName}</div>
            <div className="brand-sub">{t.brandSub}</div>
          </div>
        </div>

        <button className="new-chat" onClick={startLocalNewChat}>
          <span>＋</span>
          {t.newChatBtn}
        </button>

        <div className="sidebar-section-title">{t.history}</div>

        <div className="chat-list">
          {loading && <div className="muted">Loading...</div>}

          {!loading && !chats.length && <div className="muted">{t.emptyHistory}</div>}

          {chats.map((chat) => (
            <div
              className={cx("chat-item", chat.id === activeChatId && "active")}
              key={chat.id}
              onClick={() => openChat(chat.id)}
            >
              {editingChatId === chat.id ? (
                <div className="rename-box" onClick={(event) => event.stopPropagation()}>
                  <input
                    value={editingTitle}
                    onChange={(event) => setEditingTitle(event.target.value)}
                    autoFocus
                  />
                  <button
                    onClick={async () => {
                      await renameChat(chat.id, editingTitle);
                      setEditingChatId(null);
                    }}
                  >
                    {t.save}
                  </button>
                </div>
              ) : (
                <>
                  <div className="chat-title">{chat.title || defaultTitle}</div>
                  <div className="chat-actions">
                    <button
                      title={t.rename}
                      onClick={(event) => {
                        event.stopPropagation();
                        setEditingChatId(chat.id);
                        setEditingTitle(chat.title || "");
                      }}
                    >
                      ✎
                    </button>
                    <button
                      title={t.delete}
                      onClick={(event) => {
                        event.stopPropagation();
                        deleteChat(chat.id);
                      }}
                    >
                      ×
                    </button>
                  </div>
                </>
              )}
            </div>
          ))}
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <div className="top-title">{t.topTitle}</div>
            <div className="top-sub">{t.topSub}</div>
          </div>

          <div className="top-actions">
            <div className="segmented" aria-label={t.language}>
              <button
                className={language === "vi" ? "selected" : ""}
                onClick={() => switchLanguage("vi")}
              >
                VI
              </button>
              <button
                className={language === "en" ? "selected" : ""}
                onClick={() => switchLanguage("en")}
              >
                EN
              </button>
            </div>

            <button
              className="ghost-button"
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              {theme === "dark" ? t.light : t.dark}
            </button>
          </div>
        </header>

        <section className={cx("messages", messages.length === 0 && "empty")}>
          {messages.length === 0 ? (
            <div className="empty-state">
<div className="hero-logo-wrap"><BrandLogo className="hero-brand-logo" /></div>
              <div className="hero-kicker">MaiThuyLaw AI</div>
              <h1>
                {t.heroTitle1}
                <br />
                {t.heroTitle2}
              </h1>
              <p>{t.heroSub}</p>

              <div className="sample-grid">
                {[t.sample1, t.sample2, t.sample3].map((sample) => (
                  <button key={sample} onClick={() => sendMessage(sample)}>
                    {sample}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((message) => (
              <article
                className={cx("message-row", message.role === "user" ? "user" : "assistant")}
                key={message.id}
              >
                <div className="avatar">{message.role === "user" ? t.userAvatar : t.aiAvatar}</div>
                <div className="message-card">
                  <div className="message-content">{renderMarkdownLite(message.content, message.sources)}</div>
                </div>
              </article>
            ))
          )}

          {busy && (
            <article className="message-row assistant">
              <div className="avatar">{t.aiAvatar}</div>
              <div className="message-card thinking">
                <span />
                <span />
                <span />
              </div>
            </article>
          )}

          <div ref={bottomRef} />
        </section>

        <footer className="composer-wrap">
          {error && <div className="error-box">{error}</div>}

          {!!attachments.length && (
            <div className="attachment-strip">
              {attachments.map((item) => (
                <div className="attachment-pill" key={item.id || item.name}>
                  <span>{t.uploaded}</span>
                  {item.name || item.filename}
                  <button
                    onClick={() =>
                      setAttachments((prev) =>
                        prev.filter((att) => (att.id || att.name) !== (item.id || item.name))
                      )
                    }
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="composer">
            <button className="attach-button" onClick={() => fileRef.current?.click()}>
              ＋
            </button>
            <input ref={fileRef} type="file" hidden onChange={uploadFile} />
            <textarea
              value={input}
              placeholder={t.placeholder}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  sendMessage();
                }
              }}
            />
            <button className="send-button" disabled={busy || !input.trim()} onClick={() => sendMessage()}>
              {busy ? t.sending : t.send}
            </button>
          </div>
        </footer>
      </main>
    </div>
  );
}

function SourceList({ sources, lang, t }) {
  if (!sources?.length) return null;

  const visible = sources.slice(0, 4);
  const extra = sources.length - visible.length;

  return (
    <div className="sources">
      <div className="sources-title">{t.sources}</div>
      <div className="source-list">
        {visible.map((source, index) => {
          const label = sourceTypeLabel(source, lang);
          const title = sourceTitle(source, `[S${index + 1}]`);
          const url = source.url || source.href;

          const content = (
            <>
              <span className="source-index">S{index + 1}</span>
              <span className="source-type">{label}</span>
              <span className="source-name">{title}</span>
            </>
          );

          return url ? (
            <a className="source-chip" key={`${title}-${index}`} href={url} target="_blank" rel="noreferrer">
              {content}
            </a>
          ) : (
            <div className="source-chip" key={`${title}-${index}`}>
              {content}
            </div>
          );
        })}

        {extra > 0 && (
          <div className="source-chip muted-chip">
            +{extra} {t.moreSources}
          </div>
        )}
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
