import React, { useEffect, useState } from "react";

const API = `${import.meta.env.VITE_API_URL || "/api"}/prompts`;
const LABELS = { passed: "通过", failed: "失败", pending: "待人工判断", not_run: "未执行" };
const LEVELS = { important: "重要", normal: "普通", light: "轻度" };

async function request(path, method = "GET", body) {
  const response = await fetch(`${API}${path}`, { method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail?.code || JSON.stringify(data.detail));
  return data;
}

export default function PromptManager() {
  const [prompts, setPrompts] = useState([]);
  const [filter, setFilter] = useState("");
  const [name, setName] = useState("repair-executor");
  const [detail, setDetail] = useState(null);
  const [version, setVersion] = useState("");
  const [text, setText] = useState("");
  const [cases, setCases] = useState("");
  const [observations, setObservations] = useState("{}");
  const [report, setReport] = useState(null);
  const [history, setHistory] = useState([]);
  const [realRuns, setRealRuns] = useState([]);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    setRealRuns([]);
    request(`/${name}/real-runs`).then(data => { if (active) setRealRuns(data.runs); })
      .catch(reason => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, [name]);

  async function refresh(selectedVersion) {
    const [next, list, previous] = await Promise.all([request(`/${name}`), request(""), request(`/${name}/evaluations`)]);
    setDetail(next); setPrompts(list.prompts); setHistory(previous.reports);
    const chosen = selectedVersion || next.entry.active;
    setVersion(chosen); setText(next.versions.find(item => item.version === chosen).text);
    setCases(JSON.stringify(next.cases, null, 2));
  }

  async function act(action) {
    setBusy(true); setError(""); setNotice("");
    try { await action(); } catch (reason) { setError(reason.message); }
    finally { setBusy(false); }
  }

  useEffect(() => {
    let active = true;
    setDetail(null); setReport(null); setConfirmed(false); setObservations("{}");
    Promise.all([request(`/${name}`), request(""), request(`/${name}/evaluations`)]).then(([next, list, previous]) => {
      if (!active) return;
      setDetail(next); setPrompts(list.prompts); setHistory(previous.reports);
      setVersion(next.entry.active); setText(next.versions.find(item => item.version === next.entry.active).text);
      setCases(JSON.stringify(next.cases, null, 2)); setError("");
    }).catch(reason => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, [name]);

  const activeText = detail?.versions.find(item => item.version === detail.entry.active)?.text || "";
  const originalLines = activeText.split("\n");
  const different = text !== activeText;

  return <main className="prompt-manager">
    <header><div><h1>提示词管理与评测</h1><p>版本、预期、反例与可追溯结果</p></div><a href="/">返回任务</a></header>
    {error && <p role="alert" className="error">{error}</p>}{notice && <p role="status">{notice}</p>}
    <div className="prompt-layout"><aside><label>筛选提示词<input value={filter} onChange={event => setFilter(event.target.value)} /></label>
      <div className="prompt-list">{prompts.filter(item => `${item.name} ${item.purpose}`.includes(filter)).map(item => <button key={item.name} className={item.name === name ? "" : "secondary"} onClick={() => setName(item.name)}><strong>{item.name}</strong><small>{item.active} · {item.purpose || "历史模板"}</small></button>)}</div>
    </aside><div>{!detail ? <p>正在加载……</p> : <>
      <section className="action"><h2>{name}</h2><p>当前启用：{detail.entry.active}。历史版本不可覆盖，创建候选不会自动启用。</p>
        {detail.cases.contract.evaluation_parent && <p>评测消费角色：{detail.cases.contract.evaluation_parent}。与该角色组合发送；声明的工具只观察、不执行。</p>}
        <label>查看版本<select aria-label="查看版本" value={version} onChange={event => { const chosen = event.target.value; setVersion(chosen); setText(detail.versions.find(item => item.version === chosen).text); setConfirmed(false); }}>{detail.versions.map(item => <option key={item.version}>{item.version}</option>)}</select></label>
        <label>候选正文<textarea aria-label="候选正文" className="prompt-code" value={text} onChange={event => setText(event.target.value)} /></label>
        <details><summary>与当前启用版本对比：{different ? "有差异" : "无差异"}</summary><div className="prompt-diff"><pre>{activeText}</pre><pre>{text.split("\n").map((line, index) => <span key={index} className={line !== originalLines[index] ? "changed-line" : ""}>{line}{"\n"}</span>)}</pre></div></details>
        <button disabled={busy || !text.trim()} onClick={() => act(async () => { const created = await request(`/${name}/versions`, "POST", { text, expected_hash: detail.registry_hash }); await refresh(created.version); setReport(null); setNotice(`候选 ${created.version} 已创建，尚未启用。`); })}>创建新版本</button>
      </section>
      <section className="action"><h2>预期与反例</h2><p>按错误后果分级。重要或普通案例失败、未执行、待判断都会阻止启用。</p>
        <table><thead><tr><th>案例</th><th>等级</th><th>预期</th></tr></thead><tbody>{detail.cases.cases.map(item => <tr key={item.id}><td>{item.id}<br />{item.kind}</td><td>{LEVELS[item.level]}</td><td>{item.expected}<br /><small>禁止：{item.forbidden}</small></td></tr>)}</tbody></table>
        <details><summary>编辑契约与案例</summary><label>案例文档<textarea aria-label="案例文档" className="prompt-code" value={cases} onChange={event => setCases(event.target.value)} /></label><button disabled={busy} onClick={() => act(async () => { await request(`/${name}/cases`, "PUT", { document: JSON.parse(cases), expected_hash: detail.case_hash }); await refresh(version); setReport(null); setNotice("案例已保存，旧报告不能用于新案例的启用判断。"); })}>保存案例</button></details>
      </section>
      <section className="action"><h2>真实案例评测</h2><p>仅运行已明确批准的固定输入；未获授权时后端拒绝调用。工具只记录，不执行，不能代替完整软件返修。</p>
        {!realRuns.length && <p>暂无准备好的固定案例。</p>}
        {realRuns.map(item => <div key={item.id}><p>{item.version} · {item.case_id} · {item.status} · HTTP 上限 {item.http_cap} · {item.id.slice(0, 8)}</p>
          <button disabled={busy} onClick={() => act(async () => { const next = await request(`/real-runs/${item.id}/execute`, "POST"); setReport(next); setConfirmed(false); await refresh(version); const list = await request(`/${name}/real-runs`); setRealRuns(list.runs); })}>{item.report_id ? "打开原运行结果" : "运行已批准案例"}</button></div>)}
      </section>
      <section className="action"><h2>离线评测</h2><p>按案例 ID 导入响应与工具轨迹。本操作不调用模型；示例只验证检查器，Token 未知。</p>
        {detail.cases.contract.role === "component" && <p>组件示例仅展示检查器格式，不是完整语义正确响应；需要核对具体校验错误、适用条件和实际结果。</p>}
        <button className="secondary" disabled={busy} onClick={() => setObservations(JSON.stringify(Object.fromEntries(detail.cases.cases.map(item => [item.id, item.reference_observation || { text: "", actions: [] }])), null, 2))}>填入检查器示例</button>
        <label>响应与轨迹<textarea aria-label="响应与轨迹" className="prompt-code" value={observations} onChange={event => setObservations(event.target.value)} /></label>
        <button disabled={busy} onClick={() => act(async () => { const next = await request(`/${name}/evaluations`, "POST", { version, observations: JSON.parse(observations) }); setReport(next); setConfirmed(false); await refresh(version); })}>运行离线评测</button>
        <label>历史结果<select aria-label="历史结果" value={report?.id || ""} onChange={event => { if (event.target.value) act(async () => { setReport(await request(`/evaluations/${event.target.value}`)); setConfirmed(false); }); }}><option value="">选择历史报告</option>{history.map(item => <option key={item.id} value={item.id}>{item.version} · {item.source} · {item.id.slice(0, 8)}</option>)}</select></label>
        {report && <><p>来源：{report.source}；版本：{report.version}；已知 Token：{report.usage?.known_tokens ?? report.usage?.total_tokens ?? "未知"}；HTTP：{report.usage?.http ?? "未知"}／{report.usage?.http_cap ?? "未知"}；用量未知请求：{report.usage?.unknown_usage ?? "未知"}。</p>
          {report.evidence?.limitations?.map((item, index) => <p key={index}>{item}</p>)}
          {report.result.cases.map(item => <Judgment key={`${report.id}-${item.id}`} item={item} busy={busy} onJudge={(passed, reason) => act(async () => setReport(await request(`/evaluations/${report.id}/judgments`, "POST", { case_id: item.id, passed, reason })))} />)}
          <label className="prompt-confirm"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />我已核对证据与限制，确认启用这个版本</label>
          <button disabled={busy || !confirmed || !report.result.activation_ready || report.version !== version} onClick={() => act(async () => { await request(`/${name}/activate`, "POST", { version, report_id: report.id, expected_hash: detail.registry_hash, confirmed }); await refresh(version); setConfirmed(false); setNotice(`已启用 ${version}，已有会话保持原绑定。`); })}>启用评测版本</button>
          <p>离线证据需要逐项人工核对关键案例；结构通过不能代替真实模型与软件验证。</p>
        </>}
      </section>
    </>}</div></div>
  </main>;
}

function Judgment({ item, busy, onJudge }) {
  const [reason, setReason] = useState("");
  return <article className="prompt-result"><strong>{item.id} · {LEVELS[item.level]} · {LABELS[item.status]}</strong><p>{item.expected}</p><ul>{item.checks.map((check, index) => <li key={index}>{LABELS[check.status]}：{check.reason}</li>)}</ul>
    {item.status !== "not_run" && <div><label>人工核对理由<input aria-label={`${item.id} 判断理由`} value={reason} onChange={event => setReason(event.target.value)} /></label><button disabled={busy || !reason.trim()} onClick={() => onJudge(true, reason)}>语义符合</button><button className="secondary" disabled={busy || !reason.trim()} onClick={() => onJudge(false, reason)}>语义不符合</button></div>}
  </article>;
}
