"use client";

import { useEffect, useMemo, useRef, useState } from "react";

type NavKey = "desk" | "chat" | "knowledge" | "strategy" | "logs";
type KnowledgeView = "design" | "enabled";
type Toast = { type: "ok" | "warn"; text: string } | null;
type ReplyPolicy = {
  simulate_human_typing: boolean;
  low_confidence_handoff: boolean;
  confidence_threshold: number;
  block_off_platform: boolean;
  night_auto_reply: boolean;
};
type ReplyPolicyToggleKey = Exclude<keyof ReplyPolicy, "confidence_threshold">;
type Conversation = {
  chat_id: string;
  item_id: string;
  buyer_user_id: string;
  last_message: string;
  timestamp: string;
  mode: "auto" | "manual";
  thread_id?: string;
  graph_status?: string;
  pending_reply?: string;
  graph_nodes?: { node: string; status: string; detail: string; at: number }[];
  turn_count: number;
  risk_level: "normal" | "high";
  risk_label?: string;
  risk_reason?: string;
  risk_marked_at?: string;
  last_topic_summary?: string;
};
type ConversationMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
};
type AgentMode = "legacy" | "shadow" | "langgraph";
type ShadowComparison = {
  id: number;
  comparison: {
    intent: { match: boolean };
    recall: { overlap: number };
    reply: { exact_match: boolean };
    latency: { legacy_ms: number; langgraph_ms: number; delta_ms: number };
  };
};
type Faq = {
  id: number;
  scene: string;
  question: string;
  answer: string;
  keywords: string;
  enabled: boolean;
};
type FaqDraft = Omit<Faq, "id">;
type FaqSuggestion = {
  id: number;
  question: string;
  occurrence_count: number;
  first_seen_at: string;
  last_seen_at: string;
  last_chat_id: string;
};
type FaqSearchResult = {
  retrieval_mode: string;
  embedding_status: string;
  items: (Faq & { bm25_score: number; vector_score: number; coarse_score: number })[];
  notice: string;
};
type ReplyPreview = {
  reply: string;
  tool_status?: string;
  handoff_required?: boolean;
  handoff_reason?: string;
  tool_calls?: { name: string; status: string; result: { retrieval_mode?: string; items?: Faq[] } }[];
};
type RuntimeEvent = {
  at?: number;
  type?: string;
  message?: string;
  [key: string]: unknown;
};
type DashboardMetrics = {
  connected?: boolean;
  reply_count?: number;
  average_response_ms?: number | null;
  response_latency_sample_count?: number;
  faq_query_count?: number;
  faq_hit_rate?: number;
  faq_vector_hit_rate?: number;
  faq_bm25_hit_rate?: number;
  faq_miss_rate?: number;
  faq_enabled_count?: number;
  intent_agreement_rate?: number | null;
  intent_agreement_sample_count?: number;
  takeover_rate?: number | null;
  takeover_conversation_count?: number;
  buyer_conversation_count?: number;
  takeover_tracking_started_at?: string;
  pending_handoff_count?: number;
  pending_handoffs?: Array<{
    chat_id: string;
    message: string;
    reason: string;
    updated_at: string | number;
  }>;
};

const demoFaqs = [
  {
    id: 1,
    scene: "发货时效",
    question: "今天拍下什么时候发货？",
    answer: "正常 72 小时内发出，急用可以提前告诉我。",
    keywords: "发货 快递 今天",
    enabled: true,
  },
  {
    id: 2,
    scene: "商品成色",
    question: "状态如何？",
    answer: "状态和手感以实拍图为准，默认瑕疵。",
    keywords: "成色 瑕疵 划痕 磕碰",
    enabled: true,
  },
  {
    id: 3,
    scene: "售后边界",
    question: "可以退货吗？",
    answer: "二手闲置非物流和数量问题不退，签收后请及时验货。",
    keywords: "退货 售后 质量",
    enabled: true,
  },
];

const navItems: { key: NavKey; icon: string; label: string }[] = [
  { key: "desk", icon: "⌁", label: "工作台" },
  { key: "chat", icon: "◌", label: "实时会话" },
  { key: "knowledge", icon: "▦", label: "知识库" },
  { key: "strategy", icon: "⌘", label: "策略中心" },
  { key: "logs", icon: "≣", label: "运行日志" },
];

function Icon({ children }: { children: React.ReactNode }) {
  return (
    <span className="icon-box" aria-hidden="true">
      {children}
    </span>
  );
}

function formatRuntimeEvent(event: RuntimeEvent) {
  const time = new Date((event.at ?? Date.now() / 1000) * 1000).toLocaleTimeString(
    "zh-CN",
    { hour12: false },
  );
  const source = String(event.type || "event").slice(0, 10).padEnd(10, " ");
  const details = Object.fromEntries(
    Object.entries(event).filter(([key]) => !["at", "type", "message"].includes(key)),
  );
  const detail = event.message || (Object.keys(details).length ? JSON.stringify(details) : "事件已完成");
  return `${time}  ${source}${detail}`;
}

function Metric({
  icon,
  label,
  value,
  unit,
  trend,
}: {
  icon: string;
  label: string;
  value: string;
  unit?: string;
  trend: string;
}) {
  return (
    <article className="metric-card">
      <div className="metric-top">
        <Icon>{icon}</Icon>
        <span className="trend">{trend}</span>
      </div>
      <div className="metric-label">{label}</div>
      <div className="metric-value">
        {value}
        <small>{unit}</small>
      </div>
    </article>
  );
}

export default function AgentDesk() {
  const [nav, setNav] = useState<NavKey>("desk");
  const [knowledgeView, setKnowledgeView] = useState<KnowledgeView>("design");
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [showConnect, setShowConnect] = useState(false);
  const [gateway, setGateway] = useState(() =>
    typeof window === "undefined"
      ? "http://127.0.0.1:8787"
      : window.localStorage.getItem("xianyu-agent-gateway") || "http://127.0.0.1:8787",
  );
  const [cookie, setCookie] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [modelBase, setModelBase] = useState("https://api.deepseek.com");
  const [modelName, setModelName] = useState("deepseek-v4-flash");
  const [toast, setToast] = useState<Toast>(null);
  const [replyPolicy, setReplyPolicy] = useState<ReplyPolicy>({
    simulate_human_typing: true,
    low_confidence_handoff: false,
    confidence_threshold: 0.7,
    block_off_platform: true,
    night_auto_reply: true,
  });
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeChatId, setActiveChatId] = useState("");
  const [conversationMessages, setConversationMessages] = useState<ConversationMessage[]>([]);
  const [messagesChatId, setMessagesChatId] = useState("");
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [manualReply, setManualReply] = useState("");
  const [sendingReply, setSendingReply] = useState(false);
  const [agentMode, setAgentMode] = useState<AgentMode>("shadow");
  const [approvalReply, setApprovalReply] = useState("");
  const [graphActionBusy, setGraphActionBusy] = useState(false);
  const [shadowComparisons, setShadowComparisons] = useState<ShadowComparison[]>([]);
  const [faqs, setFaqs] = useState<Faq[]>(demoFaqs);
  const [faqSuggestions, setFaqSuggestions] = useState<FaqSuggestion[]>([]);
  const [activeSuggestionId, setActiveSuggestionId] = useState<number | null>(null);
  const [faqQuery, setFaqQuery] = useState("");
  const [faqSearchResult, setFaqSearchResult] = useState<FaqSearchResult | null>(null);
  const [faqSearching, setFaqSearching] = useState(false);
  const [replyPreview, setReplyPreview] = useState<ReplyPreview | null>(null);
  const [previewingReply, setPreviewingReply] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [savingModel, setSavingModel] = useState(false);
  const [faqEditorOpen, setFaqEditorOpen] = useState(false);
  const [editingFaqId, setEditingFaqId] = useState<number | null>(null);
  const [savingFaq, setSavingFaq] = useState(false);
  const [selectedFaqIds, setSelectedFaqIds] = useState<Set<number>>(() => new Set());
  const [deletingFaqs, setDeletingFaqs] = useState(false);
  const [faqDraft, setFaqDraft] = useState<FaqDraft>({
    scene: "",
    question: "",
    answer: "",
    keywords: "",
    enabled: true,
  });
  const [logLines, setLogLines] = useState<string[]>([]);
  const [metrics, setMetrics] = useState<DashboardMetrics | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 3200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const gatewayBase = useMemo(() => gateway.replace(/\/$/, ""), [gateway]);
  const activeConversation = useMemo(
    () => conversations.find((item) => item.chat_id === activeChatId),
    [activeChatId, conversations],
  );
  const activeConversationMessages = useMemo(
    () => (messagesChatId === activeChatId ? conversationMessages : []),
    [activeChatId, conversationMessages, messagesChatId],
  );
  const hasMetrics = Boolean(metrics);
  const hasLiveMetrics = Boolean(metrics?.connected);
  const faqHitRate = hasMetrics ? metrics?.faq_hit_rate ?? 0 : 0;
  const faqEnabledCount = hasMetrics ? metrics?.faq_enabled_count ?? 0 : 0;
  const faqBars = hasMetrics
    ? [metrics?.faq_vector_hit_rate ?? 0, metrics?.faq_bm25_hit_rate ?? 0, metrics?.faq_miss_rate ?? 0]
    : [0, 0, 0];
  const pendingHandoffs = hasLiveMetrics ? metrics?.pending_handoffs ?? [] : [];
  const pendingHandoffCount = hasLiveMetrics ? metrics?.pending_handoff_count ?? 0 : 0;
  const pendingCountLabel = pendingHandoffCount > 99 ? "99+" : String(pendingHandoffCount);

  async function api(path: string, init?: RequestInit) {
    const response = await fetch(`${gatewayBase}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok)
      throw new Error(
        body.detail || body.error || `请求失败：${response.status}`,
      );
    return body;
  }

  async function testFaqSearch(generateReply = false) {
    if (!faqQuery.trim() || faqSearching || previewingReply) return;
    setSearchError("");
    setReplyPreview(null);
    setFaqSearchResult(null);
    if (generateReply) setPreviewingReply(true);
    else setFaqSearching(true);
    try {
      if (generateReply) {
        const result = await api("/api/pipeline/test", {
          method: "POST",
          body: JSON.stringify({ message: faqQuery.trim(), item_title: "FAQ 检索测试", item_desc: "未选择具体商品，请勿推断商品属性。" }),
        });
        setReplyPreview(result);
      } else {
        setFaqSearchResult(await api("/api/faqs/search", {
          method: "POST", body: JSON.stringify({ query: faqQuery.trim(), limit: 3 }),
        }));
      }
    } catch (error) {
      setSearchError(error instanceof Error ? error.message : "检索失败，请检查 Worker 是否启动");
    } finally {
      setFaqSearching(false);
      setPreviewingReply(false);
    }
  }

  async function saveModelSettings() {
    setSavingModel(true);
    try {
      await api("/api/config", {
        method: "PUT",
        body: JSON.stringify({
          model_name: modelName.trim(), model_base_url: modelBase.trim(),
          api_key: apiKey.trim() || undefined,
        }),
      });
      setApiKey("");
      setToast({ type: "ok", text: "模型配置已保存，可前往知识库测试" });
    } catch (error) {
      setToast({ type: "warn", text: error instanceof Error ? error.message : "保存失败" });
    } finally { setSavingModel(false); }
  }

  async function loadStrategyCenter() {
    try {
      const [policy, modeData, shadowData] = await Promise.all([
        api("/api/reply-policy"),
        api("/api/agent-mode"),
        api("/api/shadow-comparisons?limit=20"),
      ]);
      setReplyPolicy(policy);
      setAgentMode(modeData.mode as AgentMode);
      setShadowComparisons((shadowData.items || []) as ShadowComparison[]);
    } catch {
      /* Worker 未启动时保留表单中的当前值。 */
    }
  }

  async function loadConversations() {
    try {
      const data = await api("/api/conversations");
      const items = (data.items || []) as Conversation[];
      const nextChatId = items.some((item) => item.chat_id === activeChatId)
        ? activeChatId
        : (items[0]?.chat_id ?? "");
      setConversations(items);
      setActiveChatId(nextChatId);
      setApprovalReply(items.find((item) => item.chat_id === nextChatId)?.pending_reply || "");
    } catch {
      setConversations([]);
    }
  }

  async function loadFaqs() {
    try {
      const [faqData, suggestionData] = await Promise.all([
        api("/api/faqs"),
        api("/api/faq-suggestions"),
      ]);
      setFaqs((faqData.items || []) as Faq[]);
      setFaqSuggestions((suggestionData.items || []) as FaqSuggestion[]);
    } catch {
      /* Worker 未启动时保留演示数据。 */
      setFaqSuggestions([]);
    }
  }

  async function loadEvents() {
    try {
      const data = await api("/api/events?limit=100");
      setLogLines(((data.items || []) as RuntimeEvent[]).map(formatRuntimeEvent));
    } catch {
      setLogLines([]);
    }
  }

  function navigate(next: NavKey) {
    setNav(next);
    if (next === "strategy") void loadStrategyCenter();
    if (next === "chat") void loadConversations();
    if (next === "knowledge") {
      setKnowledgeView("design");
      void loadFaqs();
    }
  }

  async function loadConversationMessages(chatId: string) {
    if (!chatId) {
      setConversationMessages([]);
      setMessagesChatId("");
      return;
    }
    setMessagesLoading(true);
    try {
      const data = await api(`/api/conversations/${encodeURIComponent(chatId)}/messages`);
      setConversationMessages((data.items || []) as ConversationMessage[]);
      setMessagesChatId(chatId);
    } catch {
      setConversationMessages([]);
      setMessagesChatId(chatId);
    } finally {
      setMessagesLoading(false);
    }
  }

  function openFaqEditor(faq?: Faq, suggestedQuestion = "", suggestionId: number | null = null) {
    setEditingFaqId(faq?.id ?? null);
    setActiveSuggestionId(suggestionId);
    setFaqDraft(
      faq
        ? {
            scene: faq.scene,
            question: faq.question,
            answer: faq.answer,
            keywords: faq.keywords || "",
            enabled: faq.enabled,
          }
        : {
            scene: suggestionId === null ? "" : "自动识别",
            question: suggestedQuestion,
            answer: "",
            keywords: "",
            enabled: true,
          },
    );
    setFaqEditorOpen(true);
  }

  async function saveFaq() {
    if (!faqDraft.scene.trim() || !faqDraft.question.trim() || !faqDraft.answer.trim()) {
      setToast({ type: "warn", text: "请完整填写场景、用户问法和标准回答" });
      return;
    }
    setSavingFaq(true);
    try {
      const path = editingFaqId === null ? "/api/faqs" : `/api/faqs/${editingFaqId}`;
      const saved = (await api(path, {
        method: editingFaqId === null ? "POST" : "PUT",
        body: JSON.stringify(faqDraft),
      })) as Faq;
      setFaqs((rows) =>
        editingFaqId === null
          ? [saved, ...rows]
          : rows.map((row) => (row.id === saved.id ? saved : row)),
      );
      if (activeSuggestionId !== null) {
        try {
          await api(`/api/faq-suggestions/${activeSuggestionId}/resolve`, { method: "POST" });
          setFaqSuggestions((items) => items.filter((item) => item.id !== activeSuggestionId));
        } catch {
          void loadFaqs();
        }
      }
      setFaqEditorOpen(false);
      setActiveSuggestionId(null);
      setToast({ type: "ok", text: editingFaqId === null ? "问答已新增并启用" : "场景、问法和回答已更新" });
    } catch (error) {
      setToast({ type: "warn", text: error instanceof Error ? error.message : "问答保存失败" });
    } finally {
      setSavingFaq(false);
    }
  }

  async function toggleFaq(faq: Faq) {
    const next = { ...faq, enabled: !faq.enabled };
    setFaqs((rows) => rows.map((row) => (row.id === faq.id ? next : row)));
    try {
      const saved = (await api(`/api/faqs/${faq.id}`, {
        method: "PUT",
        body: JSON.stringify(next),
      })) as Faq;
      setFaqs((rows) => rows.map((row) => (row.id === faq.id ? saved : row)));
    } catch (error) {
      setFaqs((rows) => rows.map((row) => (row.id === faq.id ? faq : row)));
      setToast({ type: "warn", text: error instanceof Error ? error.message : "状态保存失败" });
    }
  }

  function toggleFaqSelection(faqId: number) {
    setSelectedFaqIds((current) => {
      const next = new Set(current);
      if (next.has(faqId)) next.delete(faqId);
      else next.add(faqId);
      return next;
    });
  }

  function toggleAllFaqs() {
    setSelectedFaqIds((current) =>
      current.size === faqs.length ? new Set() : new Set(faqs.map((faq) => faq.id)),
    );
  }

  async function deleteSelectedFaqs() {
    const ids = [...selectedFaqIds];
    if (!ids.length || !window.confirm(`确认删除选中的 ${ids.length} 条问答吗？`)) return;
    setDeletingFaqs(true);
    try {
      await Promise.all(ids.map((id) => api(`/api/faqs/${id}`, { method: "DELETE" })));
      setFaqs((rows) => rows.filter((row) => !selectedFaqIds.has(row.id)));
      setSelectedFaqIds(new Set());
      setToast({ type: "ok", text: `已删除 ${ids.length} 条问答` });
    } catch (error) {
      await loadFaqs();
      setToast({ type: "warn", text: error instanceof Error ? error.message : "问答删除失败" });
    } finally {
      setDeletingFaqs(false);
    }
  }

  async function connectAccount() {
    if (
      !cookie.trim() ||
      !apiKey.trim() ||
      !modelName.trim() ||
      !modelBase.trim()
    ) {
      setToast({ type: "warn", text: "请填写闲鱼 Cookie 与模型 API Key" });
      return;
    }
    setConnecting(true);
    try {
      await api("/api/config", {
        method: "PUT",
        body: JSON.stringify({
          cookie,
          api_key: apiKey,
          model_base_url: modelBase,
          model_name: modelName,
        }),
      });
      await api("/api/connect", { method: "POST", body: "{}" });
      window.localStorage.setItem("xianyu-agent-gateway", gateway);
      setConnected(true);
      setShowConnect(false);
      setCookie("");
      setApiKey("");

      setLogLines((x) => [
        `${new Date().toLocaleTimeString("zh-CN", { hour12: false })}  Connector  闲鱼消息通道已连接`,
        ...x,
      ]);
      setToast({ type: "ok", text: "闲鱼账号连接成功，自动回复已开始值守" });
    } catch (error) {
      setToast({
        type: "warn",
        text:
          error instanceof Error
            ? error.message
            : "连接失败，请确认本地 Worker 已启动",
      });
    } finally {
      setConnecting(false);
    }
  }

  async function disconnectAccount() {
    try {
      await api("/api/disconnect", { method: "POST", body: "{}" });
    } catch {
      /* UI still leaves connected mode */
    }
    setConnected(false);
    setToast({ type: "ok", text: "已停止自动回复" });
  }

  async function updateReplyPolicy(key: ReplyPolicyToggleKey) {
    const previous = replyPolicy;
    const next = { ...replyPolicy, [key]: !replyPolicy[key] };
    setReplyPolicy(next);
    try {
      const saved = await api("/api/reply-policy", {
        method: "PUT",
        body: JSON.stringify(next),
      });
      setReplyPolicy(saved);
      setToast({ type: "ok", text: "回复与接管策略已同步到 Agent" });
    } catch (error) {
      setReplyPolicy(previous);
      setToast({
        type: "warn",
        text: error instanceof Error ? error.message : "回复策略保存失败",
      });
    }
  }

  async function toggleTakeover() {
    if (!activeConversation) return;
    const action = activeConversation.mode === "manual" ? "release" : "takeover";
    try {
      await api(`/api/conversations/${encodeURIComponent(activeConversation.chat_id)}/${action}`, {
        method: "POST",
        body: "{}",
      });
      await loadConversations();
      setToast({
        type: "ok",
        text: action === "takeover" ? "已人工接管，会话自动回复已暂停" : "已交还 Agent 自动回复",
      });
    } catch (error) {
      setToast({ type: "warn", text: error instanceof Error ? error.message : "接管操作失败" });
    }
  }

  async function sendManualReply() {
    if (!activeConversation || !manualReply.trim()) return;
    setSendingReply(true);
    try {
      await api("/api/conversations/reply", {
        method: "POST",
        body: JSON.stringify({
          chat_id: activeConversation.chat_id,
          to_user_id: activeConversation.buyer_user_id,
          item_id: activeConversation.item_id,
          message: manualReply.trim(),
        }),
      });
      setManualReply("");
      await loadConversations();
      setToast({ type: "ok", text: "人工回复已发送" });
    } catch (error) {
      setToast({ type: "warn", text: error instanceof Error ? error.message : "人工回复发送失败" });
    } finally {
      setSendingReply(false);
    }
  }

  async function loadMetrics() {
    try {
      setMetrics((await api("/api/metrics")) as DashboardMetrics);
    } catch {
      setMetrics(null);
    }
  }

  async function ignoreFaqSuggestion(suggestionId: number) {
    try {
      await api(`/api/faq-suggestions/${suggestionId}/ignore`, { method: "POST" });
      setFaqSuggestions((items) => items.filter((item) => item.id !== suggestionId));
      setToast({ type: "ok", text: "已忽略该自动推送问题" });
    } catch (error) {
      setToast({ type: "warn", text: error instanceof Error ? error.message : "忽略失败" });
    }
  }

  async function saveAgentMode(mode: AgentMode) {
    const previous = agentMode;
    setAgentMode(mode);
    try {
      await api("/api/agent-mode", {
        method: "PUT",
        body: JSON.stringify({ agent_mode: mode }),
      });
      setToast({ type: "ok", text: `运行模式已切换为 ${mode}` });
    } catch (error) {
      setAgentMode(previous);
      setToast({ type: "warn", text: error instanceof Error ? error.message : "模式切换失败" });
    }
  }

  useEffect(() => {
    if (nav !== "chat") return;
    const timer = window.setInterval(() => void loadConversations(), 3000);
    return () => window.clearInterval(timer);
  }, [gatewayBase, nav]);

  useEffect(() => {
    if (nav !== "chat") return;
    const initial = window.setTimeout(() => void loadConversationMessages(activeChatId), 0);
    const timer = window.setInterval(() => void loadConversationMessages(activeChatId), 3000);
    return () => { window.clearTimeout(initial); window.clearInterval(timer); };
  }, [activeChatId, gatewayBase, nav]);

  useEffect(() => {
    if (nav !== "logs") return;
    const initial = window.setTimeout(() => void loadEvents(), 0);
    const timer = window.setInterval(() => void loadEvents(), 3000);
    return () => { window.clearTimeout(initial); window.clearInterval(timer); };
  }, [gatewayBase, nav]);

  useEffect(() => {
    if (nav !== "desk") return;
    const initial = window.setTimeout(() => void loadMetrics(), 0);
    const timer = window.setInterval(() => void loadMetrics(), 15_000);
    return () => { window.clearTimeout(initial); window.clearInterval(timer); };
  }, [gatewayBase, nav]);

  useEffect(() => {
    if (nav !== "knowledge") return;
    const timer = window.setInterval(() => void loadFaqs(), 60_000);
    return () => window.clearInterval(timer);
  }, [gatewayBase, nav]);

  async function runGraphAction(action: "pause" | "resume" | "approve" | "modify") {
    if (!activeConversation) return;
    setGraphActionBusy(true);
    try {
      await api(`/api/graph/threads/${encodeURIComponent(activeConversation.chat_id)}/${action}`, {
        method: "POST",
        body: action === "modify" ? JSON.stringify({ reply: approvalReply.trim() }) : "{}",
      });
      await loadConversations();
      setToast({ type: "ok", text: action === "pause" ? "Graph 已暂停" : action === "resume" ? "Graph 已恢复，仍未发送" : "Graph 回复已批准并发送" });
    } catch (error) {
      setToast({ type: "warn", text: error instanceof Error ? error.message : "Graph 操作失败" });
    } finally {
      setGraphActionBusy(false);
    }
  }

  async function uploadFaq(file?: File) {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    try {
      const response = await fetch(`${gatewayBase}/api/faqs/import`, {
        method: "POST",
        body: form,
      });
      if (!response.ok) throw new Error();
      const data = await response.json();
      await loadFaqs();
      setToast({ type: "ok", text: `已导入 ${data.imported ?? 0} 条常见问答` });
    } catch {
      setFaqs((x) => [
        ...x,
        {
          id: Date.now(),
          scene: "批量导入",
          question: file.name,
          answer: "等待本地 Worker 解析入库",
          keywords: "",
          enabled: true,
        },
      ]);
      setToast({
        type: "warn",
        text: "已读取文件；启动本地 Worker 后可正式入库",
      });
    }
  }

  const titleMap: Record<NavKey, [string, string]> = {
    desk: ["智能值守工作台", "实时掌握每一条回复是如何生成的"],
    chat: ["实时会话", "查看 AI 与人工接管中的买家对话"],
    knowledge: knowledgeView === "design"
      ? ["知识库设计", "检索、上传并处理 Agent 自动识别的高频问题"]
      : ["已启用场景", "管理 Agent 当前可以使用的标准问答"],
    strategy: ["策略中心", "配置回复节奏、人工接管与模型运行方式"],
    logs: ["运行日志", "追踪连接、检索、生成与发送状态"],
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">X</span>
          <div>
            <strong>Xianyu Agent</strong>
            <small>智能客服控制台</small>
          </div>
        </div>
        <nav aria-label="主导航">
          {navItems.map((item) => item.key === "knowledge" ? (
            <div className="nav-knowledge-group" key={item.key}>
              <button
                className={nav === item.key ? "active" : ""}
                onClick={() => navigate(item.key)}
              >
                <span>{item.icon}</span>
                {item.label}
              </button>
              {nav === "knowledge" && (
                <div className="knowledge-subnav" aria-label="知识库导航">
                  <button
                    className={knowledgeView === "design" ? "active" : ""}
                    onClick={() => setKnowledgeView("design")}
                  >
                    知识库设计
                  </button>
                  <button
                    className={knowledgeView === "enabled" ? "active" : ""}
                    onClick={() => setKnowledgeView("enabled")}
                  >
                    已启用场景
                  </button>
                </div>
              )}
            </div>
          ) : (
            <button
              key={item.key}
              className={nav === item.key ? "active" : ""}
              onClick={() => navigate(item.key)}
            >
              <span>{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="worker-card">
            <span className={connected ? "pulse online" : "pulse"} />
            <div>
              <strong>本地 Worker</strong>
              <small>{connected ? "消息通道运行中" : "等待账号连接"}</small>
            </div>
          </div>
          <div className="profile">
            <span>店</span>
            <div>
              <strong>我的闲置店铺</strong>
              <small>{connected ? "UID 已安全连接" : "尚未连接"}</small>
            </div>
            <i>⋯</i>
          </div>
        </div>
      </aside>

      <main>
        <header className="topbar">
          <div>
            <h1>{titleMap[nav][0]}</h1>
            <p>{titleMap[nav][1]}</p>
          </div>
          <div className="top-actions">
            <button className="icon-button" aria-label="通知">
              ♢<span />
            </button>
            {connected ? (
              <button className="connected-button" onClick={disconnectAccount}>
                <i />
                闲鱼已连接 <span>停止</span>
              </button>
            ) : (
              <button
                className="primary-button"
                onClick={() => setShowConnect(true)}
              >
                <span>＋</span>连接闲鱼账号
              </button>
            )}
          </div>
        </header>

        <div className="content">
          {nav === "desk" && (
            <>
              <section className="welcome-strip">
                <div>
                  <span className="live-pill">
                    <i />
                    Agent 正常待命
                  </span>
                  <h2>今天的咨询，都在掌控中。</h2>
                  <p>
                    自动回复严格遵循价格边界；遇到异常、敏感或低置信度问题会自动转人工。
                  </p>
                </div>
                <div className="orbit">
                  <span>AI</span>
                  <i className="o1" />
                  <i className="o2" />
                  <i className="o3" />
                </div>
              </section>
              <section className="metrics-grid">
                <Metric
                  icon="↗"
                  label="今日已回复"
                  value={String(metrics?.reply_count ?? 0)}
                  unit="条"
                  trend="当天实际发出"
                />
                <Metric
                  icon="◎"
                  label="意图一致率"
                  value={metrics?.intent_agreement_rate != null ? metrics.intent_agreement_rate.toFixed(1) : "0"}
                  unit="%"
                  trend={metrics?.intent_agreement_sample_count ? `Shadow 样本 ${metrics.intent_agreement_sample_count} 条` : "暂无 Shadow 样本"}
                />
                <Metric
                  icon="ϟ"
                  label="平均响应"
                  value={metrics?.average_response_ms != null ? (metrics.average_response_ms / 1000).toFixed(2) : "0"}
                  unit="秒"
                  trend={metrics?.response_latency_sample_count ? `当天 ${metrics.response_latency_sample_count} 次生成` : "暂无真实生成记录"}
                />
                <Metric
                  icon="◒"
                  label="人工接管率"
                  value={metrics?.takeover_rate != null ? metrics.takeover_rate.toFixed(1) : "0"}
                  unit="%"
                  trend={metrics ? `${metrics.takeover_conversation_count ?? 0}/${metrics.buyer_conversation_count ?? 0} 个买家会话（监测期）` : "0/0 个买家会话（监测期）"}
                />
              </section>
              <section className="bottom-grid">
                <article className="panel compact-panel knowledge-summary">
                  <div className="panel-head">
                    <div>
                      <h3>知识库命中</h3>
                      <p>今日检索表现</p>
                    </div>
                    <button
                      className="text-button"
                      onClick={() => navigate("knowledge")}
                    >
                      管理
                    </button>
                  </div>
                  <div className="knowledge-score">
                    <strong>
                      {faqHitRate.toFixed(1)}<small>%</small>
                    </strong>
                    <div>
                      <b>FAQ 命中率</b>
                      <p>已启用 {faqEnabledCount} 条场景问答</p>
                    </div>
                  </div>
                  <div className="mini-bars">
                    {faqBars.map((value, index) => {
                      const labels = ["向量命中", "BM25 命中", "未命中"];
                      return <span key={labels[index]} title={`${labels[index]} ${value.toFixed(1)}%`}>
                        <i style={{ width: `${value}%` }} />
                      </span>;
                    })}
                  </div>
                </article>
                <article className="panel compact-panel">
                  <div className="panel-head">
                    <div>
                      <h3>待人工处理</h3>
                      <p>低置信度与敏感会话</p>
                    </div>
                    <span className="count-badge">{pendingCountLabel}</span>
                  </div>
                  {pendingHandoffs.map((item) => (
                    <div className="handoff" key={item.chat_id}>
                      <span>{item.message.slice(0, 1) || "客"}</span>
                      <div>
                        <b>{item.message}</b>
                        <small>{item.reason}</small>
                      </div>
                      <button onClick={() => { setNav("chat"); setActiveChatId(item.chat_id); void loadConversations(); }}>查看</button>
                    </div>
                  ))}
                  {!pendingHandoffs.length && <div className="empty-log">暂无待人工处理会话</div>}
                </article>
              </section>
            </>
          )}

          {nav === "chat" && (
            <section className="full-grid">
              <article className="panel session-list">
                <div className="panel-head">
                  <div>
                    <h3>进行中的会话</h3>
                    <p>共 {conversations.length} 条最近会话</p>
                  </div>
                  <button className="text-button" onClick={loadConversations}>刷新</button>
                </div>
                {conversations.map((item) => (
                  <button
                    key={item.chat_id}
                    className={item.chat_id === activeChatId ? "session active" : "session"}
                    onClick={() => { setActiveChatId(item.chat_id); setApprovalReply(item.pending_reply || ""); }}
                  >
                    <span>{item.buyer_user_id?.slice(-1) || "客"}</span>
                    <div>
                      <strong>买家 {item.buyer_user_id?.slice(-6) || "未知"}</strong>
                      <p>{item.item_id} · 已识别 {item.turn_count || 0} 轮{item.last_topic_summary ? ` · ${item.last_topic_summary}` : ""}</p>
                    </div>
                    <div className="session-status">
                      {item.risk_level === "high" && <small className="risk-badge">高风险</small>}
                      <small>{item.mode === "manual" ? "人工" : "AI"}</small>
                    </div>
                  </button>
                ))}
                {!conversations.length && <div className="empty-log">连接 Worker 并收到消息后，会话会显示在这里</div>}
              </article>
              <article className="panel conversation-detail">
                <div className="panel-head">
                  <div>
                    <h3>{activeConversation ? `买家 ${activeConversation.buyer_user_id?.slice(-6)}` : "未选择会话"}</h3>
                    <p>{activeConversation ? `${activeConversation.mode === "manual" ? "人工接管中" : "AI 接管中"} · 商品 ${activeConversation.item_id} · ${activeConversation.risk_level === "high" ? "高风险用户" : `已识别 ${activeConversation.turn_count || 0} 轮`}` : "请从左侧选择真实会话"}</p>
                  </div>
                  <button className="outline-button" onClick={toggleTakeover} disabled={!activeConversation}>
                    {activeConversation?.mode === "manual" ? "交还 AI" : "转人工"}
                  </button>
                </div>
                <div className="large-chat">
                  {!activeConversation && <div className="empty-log">暂无可操作会话</div>}
                  {activeConversation && messagesLoading && !activeConversationMessages.length && <div className="empty-log">正在加载对话记录…</div>}
                  {activeConversation && !messagesLoading && !activeConversationMessages.length && <div className="empty-log">暂无已保存的对话记录</div>}
                  {activeConversationMessages.map((message) => (
                    <div key={message.id} className={message.role === "assistant" ? "message agent" : "message buyer"}>
                      <span>{message.role === "assistant" ? "客" : "用"}</span>
                      <div>
                        <p>{message.content}</p>
                        <small>{message.timestamp.replace("T", " ").slice(0, 16)}</small>
                      </div>
                    </div>
                  ))}
                </div>
                {activeConversation?.graph_status && ["interrupted", "paused", "awaiting_approval"].includes(activeConversation.graph_status) && <div className="graph-status-panel">
                  <>
                    <textarea value={approvalReply} onChange={(event) => setApprovalReply(event.target.value)} maxLength={2000} placeholder="Graph 生成的待批准回复" />
                    <div className="faq-actions">
                      {activeConversation.graph_status !== "paused" && <button className="outline-button" disabled={graphActionBusy} onClick={() => void runGraphAction("pause")}>暂停</button>}
                      <button className="outline-button" disabled={graphActionBusy} onClick={() => void runGraphAction("resume")}>恢复但不发送</button>
                      <button className="primary-small" disabled={graphActionBusy} onClick={() => void runGraphAction("approve")}>批准原回复</button>
                      <button className="primary-small" disabled={graphActionBusy || !approvalReply.trim()} onClick={() => void runGraphAction("modify")}>修改后批准</button>
                    </div>
                  </>
                </div>}
                <div className="composer">
                  <input
                    value={manualReply}
                    onChange={(event) => setManualReply(event.target.value)}
                    onKeyDown={(event) => event.key === "Enter" && void sendManualReply()}
                    placeholder={activeConversation?.mode === "manual" ? "输入人工回复" : "人工接管后可在这里回复"}
                    disabled={activeConversation?.mode !== "manual" || sendingReply}
                  />
                  <button onClick={sendManualReply} disabled={activeConversation?.mode !== "manual" || sendingReply || !manualReply.trim()}>
                    {sendingReply ? "发送中" : "发送"}
                  </button>
                </div>
              </article>
            </section>
          )}

          {nav === "knowledge" && (
            <section className="knowledge-layout">
              <div className="knowledge-view-tabs" role="tablist" aria-label="知识库页面">
                <button className={knowledgeView === "design" ? "active" : ""} onClick={() => setKnowledgeView("design")}>知识库设计</button>
                <button className={knowledgeView === "enabled" ? "active" : ""} onClick={() => setKnowledgeView("enabled")}>已启用场景</button>
              </div>
              {knowledgeView === "design" && <>
              <article className="panel faq-search-panel">
                <div className="panel-head">
                  <div><h3>买家问题检索</h3><p>先查看相关标准答案，也可以测试模型调用知识库后的回复。</p></div>
                </div>
                <form className="faq-search-form" onSubmit={(event) => { event.preventDefault(); void testFaqSearch(); }}>
                  <label htmlFor="faq-query">买家问题</label>
                  <input id="faq-query" value={faqQuery} maxLength={1000} disabled={faqSearching || previewingReply} onChange={(event) => { setFaqQuery(event.target.value); setFaqSearchResult(null); setReplyPreview(null); setSearchError(""); }} placeholder="例如：今天拍下什么时候能寄出？" />
                  <div className="faq-actions">
                    <button className="primary-small" type="submit" disabled={!faqQuery.trim() || faqSearching || previewingReply}>{faqSearching ? "检索中…" : "查找相关答案"}</button>
                    <button className="outline-button" type="button" disabled={!faqQuery.trim() || faqSearching || previewingReply} onClick={() => void testFaqSearch(true)}>{previewingReply ? "模型回复中…" : "测试模型回复"}</button>
                  </div>
                  <small>测试不会向买家发送消息。模型回复仅测试通用 FAQ，不会推断具体商品属性。</small>
                </form>
                <div className="faq-search-results" aria-live="polite" aria-busy={faqSearching || previewingReply}>
                  {searchError && <p role="alert">{searchError}</p>}
                  {faqSearchResult && <>
                    <p><strong>相关知识库答案</strong></p>
                    {faqSearchResult.items.length ? faqSearchResult.items.map((faq) => <article className="faq-search-hit" key={faq.id}>
                      <h4>{faq.question}</h4><p>{faq.answer}</p>
                      <small>{faq.scene}</small>
                    </article>) : <p>没有检索到相关答案，请补充知识库或换一种问法。</p>}
                    <small>{faqSearchResult.notice}</small>
                  </>}
                  {replyPreview && <>
                    <p><strong>回复预览</strong> · {replyPreview.tool_status === "completed" ? "模型工具调用已完成" : replyPreview.tool_status === "fast_mode" ? "快速模式：未调用模型" : replyPreview.tool_status === "not_configured" ? "未配置聊天模型，使用检索降级回复" : replyPreview.handoff_required ? "需要人工处理" : "模型流程未完成，使用降级回复"}</p>
                    <p>{replyPreview.handoff_required ? replyPreview.handoff_reason : replyPreview.reply}</p>
                    {replyPreview.tool_calls?.map((call, index) => <p key={index}>{call.name} · {call.status === "completed" ? "成功" : "失败"} · {call.result.retrieval_mode || "未完成检索"} · {call.result.items?.length ?? 0} 条结果</p>)}
                  </>}
                </div>
              </article>
              <article
                className="upload-card"
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  uploadFaq(e.dataTransfer.files[0]);
                }}
              >
                <input
                  ref={fileRef}
                  type="file"
                  accept=".csv,.json,.xlsx"
                  onChange={(e) => uploadFaq(e.target.files?.[0])}
                  hidden
                />
                <Icon>⇧</Icon>
                <h3>上传常见问答场景</h3>
                <p>拖入 CSV、JSON 或 XLSX 文件，系统会自动校验并建立检索索引</p>
                <button onClick={() => fileRef.current?.click()}>选择文件</button>
                <small>模板字段：scene, question, answer, keywords</small>
              </article>
              <article className="panel suggestion-panel">
                <div className="panel-head">
                  <div>
                    <h3>自动推送问题</h3>
                    <p>同一未命中问题被真实买家提问 3 次后自动出现</p>
                  </div>
                  <span className="suggestion-count">{faqSuggestions.length}</span>
                </div>
                {faqSuggestions.length ? (
                  <div className="suggestion-list">
                    {faqSuggestions.map((suggestion) => (
                      <article className="suggestion-item" key={suggestion.id}>
                        <div>
                          <strong>{suggestion.question}</strong>
                          <p>
                            已提问 {suggestion.occurrence_count} 次 · 最近出现 {new Date(`${suggestion.last_seen_at}Z`).toLocaleString("zh-CN", { hour12: false })}
                          </p>
                        </div>
                        <div className="suggestion-actions">
                          <button className="outline-button" onClick={() => void ignoreFaqSuggestion(suggestion.id)}>忽略</button>
                          <button className="primary-small" onClick={() => openFaqEditor(undefined, suggestion.question, suggestion.id)}>加入知识库</button>
                        </div>
                      </article>
                    ))}
                  </div>
                ) : (
                  <div className="suggestion-empty">暂无自动推送问题。Agent 会持续统计真实买家的未命中问题。</div>
                )}
              </article>
              </>}
              {knowledgeView === "enabled" && (
              <article className="panel faq-table">
                <div className="panel-head">
                  <div>
                    <h3>已启用场景</h3>
                    <p>{faqs.filter((faq) => faq.enabled).length} 条已启用问答 · 可在上方测试实际检索效果</p>
                  </div>
                  <div className="faq-actions">
                    <button
                      className="delete-small"
                      onClick={() => void deleteSelectedFaqs()}
                      disabled={!selectedFaqIds.size || deletingFaqs}
                    >
                      {deletingFaqs ? "删除中…" : `删除所选${selectedFaqIds.size ? `（${selectedFaqIds.size}）` : ""}`}
                    </button>
                    <button
                      className="primary-small"
                      onClick={() => openFaqEditor()}
                    >
                      ＋ 新增问答
                    </button>
                  </div>
                </div>
                <div className="table-head">
                  <input
                    type="checkbox"
                    checked={faqs.length > 0 && selectedFaqIds.size === faqs.length}
                    onChange={toggleAllFaqs}
                    aria-label="选择全部问答"
                  />
                  <span>场景</span>
                  <span>用户问法</span>
                  <span>标准回答</span>
                  <span>状态</span>
                </div>
                {faqs.map((faq) => (
                  <div className="table-row" key={faq.id}>
                    <input
                      type="checkbox"
                      checked={selectedFaqIds.has(faq.id)}
                      onChange={() => toggleFaqSelection(faq.id)}
                      aria-label={`选择${faq.scene}`}
                    />
                    <button className="faq-cell faq-scene" onClick={() => openFaqEditor(faq)}>
                      <b>{faq.scene}</b>
                    </button>
                    <button className="faq-cell" onClick={() => openFaqEditor(faq)}>{faq.question}</button>
                    <button className="faq-cell" onClick={() => openFaqEditor(faq)}>{faq.answer}</button>
                    <span>
                      <button
                        className={`switch ${faq.enabled ? "on" : ""}`}
                        onClick={() => void toggleFaq(faq)}
                        aria-label={`${faq.enabled ? "停用" : "启用"}${faq.scene}`}
                        aria-pressed={faq.enabled}
                      >
                        <i />
                      </button>
                    </span>
                  </div>
                ))}
              </article>
              )}
            </section>
          )}

          {nav === "strategy" && (
            <section className="strategy-grid">
              <article className="panel settings-card">
                <div className="panel-head">
                  <div>
                    <h3>回复与接管</h3>
                    <p>控制 Agent 的表达节奏和风险边界</p>
                  </div>
                </div>
                {([
                  ["simulate_human_typing", "模拟人工输入", replyPolicy.simulate_human_typing ? "已开启：按字数随机延迟 0–10 秒" : "已关闭：跳过模型精排和生成，通常 1 秒内快速回复"],
                  ["low_confidence_handoff", "低置信度转人工", `意图置信度低于 ${Math.round(replyPolicy.confidence_threshold * 100)}% 时暂停回复`],
                  ["block_off_platform", "平台外交易拦截", "拒绝微信、QQ、线下支付等引导"],
                  ["night_auto_reply", "夜间自动值守", "每日 00:00–08:00 保持在线"],
                ] as [ReplyPolicyToggleKey, string, string][]).map(([key, title, detail]) => (
                  <div className="setting-row" key={key}>
                    <div>
                      <strong>{title}</strong>
                      <p>{detail}</p>
                    </div>
                    <button
                      className={`switch ${replyPolicy[key] ? "on" : ""}`}
                      onClick={() => void updateReplyPolicy(key)}
                      aria-pressed={Boolean(replyPolicy[key])}
                    >
                      <i />
                    </button>
                  </div>
                ))}
              </article>
              <article className="panel settings-card model-card">
                <div className="panel-head">
                  <div>
                    <h3>模型路由</h3>
                    <p>兼容 OpenAI 标准接口</p>
                  </div>
                </div>
                <label>
                  Agent 运行模式
                  <select value={agentMode} onChange={(event) => void saveAgentMode(event.target.value as AgentMode)}>
                    <option value="legacy">legacy · 仅旧流水线</option>
                    <option value="shadow">shadow · 旧回复发送，Graph 静默比较</option>
                    <option value="langgraph">langgraph · Graph 回复需人工批准</option>
                  </select>
                </label>
                {shadowComparisons[0] && <div className="model-note">
                  最近 Shadow：意图{shadowComparisons[0].comparison.intent.match ? "一致" : "不一致"} · 召回重合 {Math.round(shadowComparisons[0].comparison.recall.overlap * 100)}% · 回复{shadowComparisons[0].comparison.reply.exact_match ? "一致" : "有差异"} · 延迟差 {shadowComparisons[0].comparison.latency.delta_ms} ms
                </div>}
                <label>
                  模型地址
                  <input
                    value={modelBase}
                    onChange={(e) => setModelBase(e.target.value)}
                  />
                </label>
                <label>
                  模型名称
                  <input
                    value={modelName}
                    onChange={(e) => setModelName(e.target.value)}
                  />
                </label>
                <div className="model-agents">
                  <span>意图专家</span>
                  <span>改写专家</span>
                  <span>精排专家</span>
                  <span>回复专家</span>
                  <span>FAQ 工具调用</span>
                </div>
                <label>聊天模型 API Key<input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="留空保留已保存密钥" /></label>
                <button className="primary-small" disabled={savingModel || !modelName.trim() || !modelBase.trim()} onClick={() => void saveModelSettings()}>{savingModel ? "保存中…" : "保存模型配置"}</button>
                <p className="model-note">
                  API Key 仅保存在本地
                  Worker，不会写入前端代码或上传到托管站点。
                </p>
              </article>
            </section>
          )}

          {nav === "logs" && (
            <section className="panel logs-panel">
              <div className="panel-head">
                <div>
                  <h3>实时运行日志</h3>
                  <p>自动刷新 · 仅输出真实运行结果</p>
                </div>
                <div className="log-actions">
                  <button>全部级别⌄</button>
                  <button onClick={() => setLogLines([])}>清空</button>
                </div>
              </div>
              <div className="log-terminal">
                {logLines.length ? (
                  logLines.map((line, i) => (
                    <div key={`${line}-${i}`}>
                      <span>{line.slice(0, 8)}</span>
                      <b>{line.slice(10, 20)}</b>
                      <p>{line.slice(20)}</p>
                    </div>
                  ))
                ) : (
                  <div className="empty-log">暂无日志</div>
                )}
              </div>
            </section>
          )}
        </div>
      </main>

      {showConnect && (
        <div
          className="modal-backdrop"
        >
          <section
            className="connect-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="connect-title"
          >
            <button
              className="modal-close"
              onClick={() => setShowConnect(false)}
            >
              ×
            </button>
            <span className="modal-mark">X</span>
            <h2 id="connect-title">连接闲鱼账号</h2>
            <p>
              凭证只会发送到你电脑上的本地 Worker。建议使用专门的闲鱼运营账号。
            </p>
            <label>
              本地 Worker 地址
              <input
                value={gateway}
                onChange={(e) => setGateway(e.target.value)}
              />
            </label>
            <label>
              闲鱼网页 Cookie
              <textarea
                value={cookie}
                onChange={(e) => setCookie(e.target.value)}
                placeholder="登录 goofish.com 后，从浏览器开发者工具复制完整 Cookie"
              />
            </label>
            <div className="connect-row">
              <label>
                模型 API Key
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="仅本地保存"
                />
              </label>
              <label>
                模型名称
                <input
                  value={modelName}
                  onChange={(e) => setModelName(e.target.value)}
                />
              </label>
            </div>
            <label>
              模型 URL
              <input
                type="url"
                value={modelBase}
                onChange={(e) => setModelBase(e.target.value)}
              />
            </label>
            <div className="privacy-note">
              <span>✓</span>
              <p>
                <strong>安全提醒</strong>不要把 Cookie 提交到 Git
                或发给他人；账号掉线、滑块或风控需要在闲鱼网页端重新登录处理。
              </p>
            </div>
            <button
              className="primary-button connect-submit"
              onClick={connectAccount}
              disabled={connecting}
            >
              {connecting ? "正在验证并连接…" : "验证账号并开始值守"}
            </button>
            <small className="license-note">
              连接实现基于 XianyuAutoAgent（GPL-3.0），仅用于你有权管理的账号。
            </small>
          </section>
        </div>
      )}
      {faqEditorOpen && (
        <div className="modal-backdrop">
          <section className="connect-modal faq-modal" role="dialog" aria-modal="true" aria-labelledby="faq-editor-title">
            <button className="modal-close" onClick={() => setFaqEditorOpen(false)}>×</button>
            <span className="modal-mark">Q</span>
            <h2 id="faq-editor-title">{editingFaqId === null ? "新增问答" : "编辑问答"}</h2>
            <p>已启用问答的场景用于粗排召回，用户问法和标准回答用于模型精排。</p>
            <label>
              场景
              <input value={faqDraft.scene} onChange={(e) => setFaqDraft((draft) => ({ ...draft, scene: e.target.value }))} placeholder="例如：发货时效" />
            </label>
            <label>
              用户问法
              <textarea value={faqDraft.question} onChange={(e) => setFaqDraft((draft) => ({ ...draft, question: e.target.value }))} placeholder="例如：今天拍什么时候发货？" />
            </label>
            <label>
              标准回答
              <textarea value={faqDraft.answer} onChange={(e) => setFaqDraft((draft) => ({ ...draft, answer: e.target.value }))} placeholder="填写 Agent 可直接参考的回答" />
            </label>
            <label>
              粗排关键词（可选）
              <input value={faqDraft.keywords} onChange={(e) => setFaqDraft((draft) => ({ ...draft, keywords: e.target.value }))} placeholder="多个关键词用空格分隔" />
            </label>
            <div className="faq-enabled-row">
              <div><strong>启用此问答</strong><p>停用后不会进入粗排与精排。</p></div>
              <button className={`switch ${faqDraft.enabled ? "on" : ""}`} onClick={() => setFaqDraft((draft) => ({ ...draft, enabled: !draft.enabled }))} aria-pressed={faqDraft.enabled}><i /></button>
            </div>
            <button className="primary-button connect-submit" onClick={() => void saveFaq()} disabled={savingFaq}>
              {savingFaq ? "正在保存…" : "保存问答"}
            </button>
          </section>
        </div>
      )}
      {toast && (
        <div className={`toast ${toast.type}`}>
          <span>{toast.type === "ok" ? "✓" : "!"}</span>
          {toast.text}
        </div>
      )}
    </div>
  );
}
