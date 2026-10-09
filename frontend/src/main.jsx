import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const API = import.meta.env.VITE_API_URL || "/api";
const STEPS = ["product_docs", "architecture_docs", "dev_design", "develop", "test", "start_product", "verify_product"];
const STEP_LABELS = { product_docs: "产品需求", architecture_docs: "架构设计", dev_design: "Dev Design", develop: "开发", test: "测试", start_product: "启动", verify_product: "浏览器验证" };
const STATUS_LABELS = { pending: "等待", running: "执行中", waiting_user: "等待用户", waiting_acceptance: "等待验收", succeeded: "成功", failed: "失败", info: "记录" };
const TRACE_LABELS = { model_request: "模型调用信息", model_response: "模型返回数据", model_retry: "模型重试", model_fallback: "模型降级", tool_call: "工具调用", tool_result: "工具返回数据", artifact: "文件", user_event: "用户操作", transition_decision: "流程决策", acceptance_triage: "问题分类", program_validation: "验证结果", state_transition: "状态变化" };
const FIELD_LABELS = { payload: "调用内容", raw_response: "Provider 原始返回", messages: "消息", content: "内容", input: "本次输入", context: "上下文", tools: "可用工具", model: "模型", provider: "服务商", parameters: "参数", result: "返回值", actions: "工具请求", text: "模型回答", request_id: "请求 ID", tool_call_id: "工具调用 ID", path: "工作区路径", name: "文件名", sha256: "内容哈希", status: "状态", summary: "摘要", title: "标题", role: "角色", type: "类型", created_at: "创建时间", started_at: "开始时间", finished_at: "结束时间" };
const mergeUnique = (current, incoming, key) => [...new Map([...current, ...incoming].map((item) => [item[key], item])).values()];
Object.assign(FIELD_LABELS, { prompt_tokens: "输入 Token", completion_tokens: "输出 Token", total_tokens: "总 Token", prompt_cache_hit_tokens: "缓存命中 Token", prompt_cache_miss_tokens: "缓存未命中 Token", prompt_tokens_details: "输入明细", completion_tokens_details: "输出明细", cached_tokens: "缓存 Token", reasoning_tokens: "推理 Token" });

function App() {
  const [taskId, setTaskId] = useState(() => Number(new URLSearchParams(window.location.search).get("task")) || null);
  const [task, setTask] = useState(null);
  const [messages, setMessages] = useState([]);
  const [traces, setTraces] = useState([]);
  const [liveResponse, setLiveResponse] = useState({});
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [productDocument, setProductDocument] = useState("");
  const [error, setError] = useState("");
  const messageCursor = useRef(0);
  const traceCursor = useRef(0);

  async function request(path, options) {
    const response = await fetch(`${API}${path}`, { headers: { "Content-Type": "application/json" }, ...options });
    if (!response.ok) throw new Error((await response.text()) || `HTTP ${response.status}`);
    return response.json();
  }

  async function createTask(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const created = await request("/tasks", { method: "POST", body: JSON.stringify({ task_name: form.get("task_name"), initial_message: form.get("initial_message") }) });
      window.history.replaceState(null, "", `?task=${created.task_id}`);
      setTaskId(created.task_id); setTask(created); setError("");
    } catch (reason) { setError(reason.message); }
  }

  async function sendEvent(type, data) {
    if (type === "user_message" && task?.repair_decision) {
      data = { ...data, decision_id: task.repair_decision.id };
    }
    if (type === "acceptance_result" && task?.execution_mode === "repair-v1") {
      data = { ...data, submission_id: task.submission_id, expected_task_version: task.task_version };
    }
    try { await request(`/tasks/${taskId}/events`, { method: "POST", body: JSON.stringify({ type, data }) }); setError(""); }
    catch (reason) { setError(reason.message); }
  }

  useEffect(() => {
    if (!taskId) return undefined;
    const poll = async () => {
      try {
        const [nextTask, nextMessages, nextTraces, nextLiveResponse] = await Promise.all([
          request(`/tasks/${taskId}`), request(`/tasks/${taskId}/messages?after_id=${messageCursor.current}`), request(`/tasks/${taskId}/traces?after_sequence=${traceCursor.current}`),
          request(`/tasks/${taskId}/live-response`),
        ]);
        setTask(nextTask);
        setLiveResponse(nextLiveResponse);
        if (nextTask.status === "waiting_user" && nextTask.product_document_available) setProductDocument((await request(`/tasks/${taskId}/documents/product`)).content);
        if (nextMessages.messages.length) { messageCursor.current = nextMessages.latest_message_id; setMessages((current) => mergeUnique(current, nextMessages.messages, "id")); }
        if (nextTraces.traces.length) { traceCursor.current = nextTraces.latest_sequence; setTraces((current) => mergeUnique(current, nextTraces.traces, "sequence")); }
        setError("");
      } catch (reason) { setError(`进度暂时无法获取：${reason.message}`); }
    };
    poll();
    const timer = window.setInterval(poll, 750);
    return () => window.clearInterval(timer);
  }, [taskId]);

  useEffect(() => {
    if (!selected) { setDetail(null); return undefined; }
    let active = true;
    setDetail(null);
    const path = selected.kind === "file" ? `/tasks/${taskId}/files?path=${encodeURIComponent(selected.path)}` : `/tasks/${taskId}/traces/${selected.sequence}`;
    request(path).then((value) => { if (active) setDetail(value); }).catch((reason) => { if (active) setDetail({ unavailable: true, error: reason.message }); });
    return () => { active = false; };
  }, [taskId, selected]);

  const streams = liveResponse.request_id ? { [liveResponse.request_id]: liveResponse.text } : {};
  const completed = useMemo(() => new Set(traces.filter((item) => item.type === "model_response" && item.status === "succeeded").map((item) => item.metadata?.request_id).filter(Boolean)), [traces]);
  const feed = useMemo(() => [
    ...messages.filter((item) => item.content?.trim()).map((item) => ({ ...item, kind: "message", sortAt: item.created_at || "" })),
    ...traces.filter((item) => item.type !== "model_stream_delta").map((item) => ({ ...item, kind: item.type === "artifact" ? "file" : "trace", path: item.metadata?.path, sortAt: item.created_at || "" })),
  ].sort((a, b) => a.sortAt.localeCompare(b.sortAt) || (a.sequence || a.id) - (b.sequence || b.id)), [messages, traces]);

  if (!taskId) return <main className="landing"><h1>开发团队模拟器</h1><p>描述你希望开发的软件。</p><form onSubmit={createTask}><label>任务名称<input name="task_name" defaultValue="网页版计算器" required /></label><label>软件需求<textarea name="initial_message" defaultValue="帮我做一个计算器，支持数字的加减乘除，结果显示为小数点后两位。" required /></label><button>开始开发</button></form>{error && <p className="error">{error}</p>}</main>;

  const currentIndex = STEPS.indexOf(task?.cur_step);
  const latestProductRun = messages.filter((item) => item.content.includes("产品文档 v")).at(-1);
  const version = latestProductRun ? Number(latestProductRun.content.match(/v(\d+)/)?.[1] || 1) : 1;
  return <main className="workspace"><header><div><h1>任务 #{taskId}</h1><p>{STEP_LABELS[task?.cur_step]} · {STATUS_LABELS[task?.status] || task?.status}</p></div>{task?.result_url && <a className="button" href={task.result_url} target="_blank" rel="noreferrer">打开生成的软件</a>}</header>
    <nav className="stage-strip">{STEPS.map((step, index) => <span key={step} className={index < currentIndex ? "done" : index === currentIndex ? "active" : ""}>{STEP_LABELS[step]}</span>)}</nav>
    <section className="split"><div className="feed"><div className="pane-heading"><h2>任务对话</h2><small>消息与执行记录实时更新</small></div>{feed.map((item) => <FeedItem key={`${item.kind}-${item.sequence || item.id}`} item={item} stream={streams[item.metadata?.request_id]} complete={completed.has(item.metadata?.request_id)} selected={selected} onSelect={setSelected} />)}<TaskAction task={task} version={version} document={productDocument} send={sendEvent} />{error && <p className="error">{error}</p>}</div><Inspector selected={selected} detail={detail} /></section>
  </main>;
}

function FeedItem({ item, stream, complete, selected, onSelect }) {
  if (item.kind === "message") return <article className={`message ${item.role}`}><span>{item.role === "user" ? "你" : "模型"}</span><p>{item.content}</p></article>;
  const active = selected && (selected.sequence === item.sequence);
  const label = TRACE_LABELS[item.type] || item.title;
  return <div className="trace-row"><button className={`trace-card ${active ? "selected" : ""}`} onClick={() => onSelect(item)}><strong>【{label}】</strong><span>{compactSummary(item)}</span></button>{item.type === "model_request" && stream && !complete && <article className="message assistant streaming"><span>模型正在回答</span><p>{stream}<i className="cursor" /></p></article>}</div>;
}

function compactSummary(item) {
  if (item.type === "model_request" || item.type === "model_response") return [item.metadata?.provider, item.metadata?.model, item.summary].filter(Boolean).join(" · ");
  if (item.type === "artifact") return item.metadata?.path || item.metadata?.name || item.summary;
  return item.summary || item.title;
}

function Inspector({ selected, detail }) {
  if (!selected) return <aside className="inspector empty"><div><h2>详细信息</h2><p>点击左侧缩略信息，查看本次模型调用、原始返回、工具执行或文件内容。</p></div></aside>;
  if (!detail) return <aside className="inspector"><p>正在加载……</p></aside>;
  if (detail.unavailable) return <aside className="inspector"><p className="error">详情不可用：{detail.error}</p></aside>;
  if (selected.kind === "file") return <aside className="inspector"><div className="inspector-title"><div><small>文件</small><h2>{detail.name}</h2></div></div><MetaRows value={{ path: detail.path, bytes: detail.bytes, sha256: detail.sha256 }} /><section><h3>文件内容</h3><pre className="file-content">{detail.content}</pre></section></aside>;
  return <aside className="inspector"><div className="inspector-title"><div><small>{TRACE_LABELS[selected.type] || "执行信息"}</small><h2>{selected.title}</h2></div><span className={`badge ${selected.status}`}>{STATUS_LABELS[selected.status] || selected.status}</span></div><MetaRows value={{ provider: selected.metadata?.provider, model: selected.metadata?.model, request_id: selected.metadata?.request_id, created_at: selected.created_at }} />{selected.summary && <section><h3>摘要</h3><p>{selected.summary}</p></section>}<TraceSections type={selected.type} detail={detail} /></aside>;
}

function TraceSections({ type, detail }) {
  const payload = detail.payload ?? detail;
  if (type === "model_request") {
    const call = payload.payload || payload;
    const messages = call.messages || [];
    const system = messages.find((item) => item.role === "system")?.content;
    const userText = messages.find((item) => item.role === "user")?.content;
    let user = userText;
    try { user = JSON.parse(userText); } catch { /* 保留原始文本 */ }
    return <><ReadableSection title="系统指令" value={system} /><ReadableSection title="用户输入与上下文" value={user} /><ReadableSection title="可用工具" value={call.tools} /><ReadableSection title="调用配置" value={{ model: call.model, stream: call.stream, thinking: call.thinking, max_completion_tokens: call.max_completion_tokens }} /></>;
  }
  if (type === "model_response") return <><ReadableSection title="Token 用量" value={payload.raw_response?.usage || "Provider 未返回用量（历史记录可能未保留）"} /><ReadableSection title="模型回答" value={payload.text} /><ReadableSection title="工具请求" value={payload.actions} /><ReadableSection title={payload.raw_response?.stream_events ? "Provider 原始返回（历史记录）" : "Provider 合并响应"} value={payload.raw_response} /></>;
  if (type === "tool_call") return <><ReadableSection title="调用工具" value={payload.tool_name || payload.name} /><ReadableSection title="调用参数" value={payload.parameters || payload} /></>;
  if (type === "tool_result") return <ReadableSection title="工具返回值" value={payload.result || payload} />;
  return <ReadableSection title="完整信息" value={payload} />;
}

function ReadableSection({ title, value }) { if (value === undefined || value === null) return null; return <section><h3>{title}</h3><HumanValue value={value} /></section>; }
function HumanValue({ value }) {
  if (value === null || value === undefined) return <span className="muted">无</span>;
  if (typeof value === "string") return <pre className="text-value">{value}</pre>;
  if (typeof value !== "object") return <span>{String(value)}</span>;
  if (Array.isArray(value)) return value.length ? <ol className="value-list">{value.map((item, index) => <li key={index}><HumanValue value={item} /></li>)}</ol> : <span className="muted">无</span>;
  const entries = Object.entries(value).filter(([, item]) => item !== undefined && item !== null);
  return entries.length ? <dl className="value-grid">{entries.map(([key, item]) => <div key={key}><dt>{FIELD_LABELS[key] || key.replaceAll("_", " ")}</dt><dd><HumanValue value={item} /></dd></div>)}</dl> : <span className="muted">无</span>;
}
function MetaRows({ value }) { return <div className="meta-row">{Object.entries(value).filter(([, item]) => item !== undefined && item !== null).map(([key, item]) => <span key={key}><b>{FIELD_LABELS[key] || key}</b>{key.endsWith("_at") ? new Date(item).toLocaleString() : String(item)}</span>)}</div>; }

function TaskAction({ task, version, document, send }) {
  if (task?.repair_state === "waiting_decision") return <section><p>{task.repair_decision?.question}</p><p>{task.repair_decision?.impact}</p><p>{task.repair_decision?.proposal}</p><Clarification send={send} /></section>;
  if (task?.status === "waiting_user" && !task.product_document_available) return <Clarification send={send} />;
  if (task?.status === "waiting_user" && task.product_document_available) return <Approval version={version} document={document} send={send} />;
  if (task?.status === "waiting_acceptance") return <Acceptance send={send} />;
  if (task?.status === "succeeded") return <ChangeRequest send={send} />;
  return task?.failure_reason ? <p className="error">{task.failure_reason}</p> : null;
}
function Clarification({ send }) { const [answer, setAnswer] = useState(""); return <section className="action"><h2>回答产品问题</h2><textarea value={answer} onChange={(event) => setAnswer(event.target.value)} /><button disabled={!answer.trim()} onClick={() => { send("user_message", { content: answer.trim() }); setAnswer(""); }}>提交回答</button></section>; }
function Approval({ version, document, send }) { const [feedback, setFeedback] = useState(""); return <section className="action"><h2>确认产品文档</h2><pre className="document">{document}</pre><textarea value={feedback} onChange={(event) => setFeedback(event.target.value)} placeholder="退回时填写修改意见" /><div><button onClick={() => send("document_approval", { document_type: "product", document_version: version, approved: true, feedback: "" })}>批准</button><button className="secondary" onClick={() => send("document_approval", { document_type: "product", document_version: version, approved: false, feedback })}>退回修改</button></div></section>; }
function Acceptance({ send }) { const [feedback, setFeedback] = useState(""); return <section className="action"><h2>人工验收</h2><textarea value={feedback} onChange={(event) => setFeedback(event.target.value)} placeholder="描述期望行为、实际行为和复现步骤" /><div><button onClick={() => send("acceptance_result", { approved: true, feedback: "" })}>验收通过</button><button className="secondary" disabled={!feedback.trim()} onClick={() => { send("acceptance_result", { approved: false, feedback: feedback.trim() }); setFeedback(""); }}>报告问题</button></div></section>; }
function ChangeRequest({ send }) { const [feedback, setFeedback] = useState(""); return <section className="action"><h2>给现有产品增加功能</h2><textarea value={feedback} onChange={(event) => setFeedback(event.target.value)} placeholder="说明新增什么、为什么需要、怎么算成功" /><button disabled={!feedback.trim()} onClick={() => { send("change_request", { feedback: feedback.trim() }); setFeedback(""); }}>提交功能需求</button></section>; }

createRoot(document.getElementById("root")).render(<React.StrictMode><App /></React.StrictMode>);
