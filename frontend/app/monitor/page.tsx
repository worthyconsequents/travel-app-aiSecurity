"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import "./monitor.css";

type Audit = { id: string; at: number; correlation_id: string; human: string; agent: string; tool: string; server: string; resource: string; decision: string; reason_code: string; policy_id: string; downstream: boolean; outcome: string; arguments: Record<string, string> };
type Activity = { id: string; at: number; correlation_id: string; stage: string; human: string; agent: string; tool: string; audit_id: string; details: Record<string, string | number> };
type Scenario = { id: number; name: string; decision: string; expected: string; reason_code: string; passed: boolean; status?: string; source?: string; correlation_id: string; audit_id: string; evidence?: Record<string, unknown>; attack?: { tool: string; arguments: object; source_hotel?: string; source_excerpt?: string } };
type Run = { id: string; started: number; finished: number | null; status: string; profile: string; result: { scenarios?: Scenario[]; no_mutations?: boolean; total?: number; note?: string; error?: string } };
type Runner = { enabled: boolean; ready: boolean; message: string; suites: { id: string; name: string }[] };
type Data = { test_runner?: Runner; profile: string; model: string; evidence: string; totals: Record<string, number>; audits: Audit[]; activity: Activity[]; runs: Run[] };
type Flow = { correlation_id: string; events: Activity[]; audits: Audit[]; historical: boolean };
const stages: Record<string, string> = { fixture_catalog_changed: "Synthetic catalog changed", catalog_observed: "Catalog received", fixture_dispatch_started: "Synthetic tool request sent", fixture_receipt_checked: "Backend execution receipt checked", idempotent_replay: "Existing receipt replayed", enforcement_denied: "Additional enforcement denied",  inference_started: "Inference request started", inference_completed: "Inference response received", inference_failed: "Inference request failed",  chat_received: "Chat received", chat_completed: "Assistant replied", chat_failed: "Assistant request failed", test_case_started: "Test case started", test_case_completed: "Test case completed", tool_requested: "Tool request received", policy_decision: "Policy evaluated", dispatch_started: "Downstream dispatch started", dispatch_completed: "Tool response received", tool_failed: "Tool processing failed" };
const clock = (at: number) => new Date(at * 1000).toLocaleTimeString([], { hour12: false });
const date = (at: number) => new Date(at * 1000).toLocaleString();
const badge = (status: string) => `ops-badge ${["ALLOW", "passed", "completed"].includes(status) ? "good" : ["DENY", "failed", "error"].includes(status) ? "bad" : "neutral"}`;

export default function Monitor() {
  const [authenticated, setAuthenticated] = useState(false);
  const [checking, setChecking] = useState(true);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState(false);
  const [data, setData] = useState<Data | null>(null);
  const [flow, setFlow] = useState<Flow | null>(null);
  const [attack, setAttack] = useState<Scenario | null>(null);
  const [runId, setRunId] = useState("");
  const [suite, setSuite] = useState("all");
  const [filter, setFilter] = useState("");
  const [error, setError] = useState("");
  const [updated, setUpdated] = useState("");

  const flowRequest = useRef<AbortController | null>(null);
  const forget = useCallback(() => { flowRequest.current?.abort(); setAuthenticated(false); setData(null); setFlow(null); setAttack(null); setRunId(""); }, []);
  const load = useCallback(async () => {
    try {
      const response = await fetch("/api/monitor/data", { cache: "no-store" });
      if (response.status === 401) { forget(); return; }
      if (!response.ok) throw new Error();
      const snapshot = await response.json(); setData(snapshot); setRunId(current => current || snapshot.runs[0]?.id || ""); setUpdated(new Date().toLocaleTimeString()); setError("");
    } catch { setError("The activity feed is unavailable. The last successful snapshot is shown."); }
  }, [forget]);

  useEffect(() => { let active = true; void fetch("/api/monitor/session", { cache: "no-store" }).then(r => { if (active) setAuthenticated(r.ok); }).catch(() => {}).finally(() => { if (active) setChecking(false); }); return () => { active = false; }; }, []);
  useEffect(() => {
    if (!authenticated) return;
    void load();
    const timer = setInterval(() => { if (document.visibilityState === "visible") void load(); }, 5000);
    return () => clearInterval(timer);
  }, [authenticated, load]);

  useEffect(() => {
    if (!authenticated || !flow?.correlation_id) return;
    const correlation = flow.correlation_id;
    let active = true;
    const timer = setInterval(() => {
      if (document.visibilityState !== "visible") return;
      void fetch(`/api/monitor/flow/${encodeURIComponent(correlation)}`, { cache: "no-store" })
        .then(async response => {
          if (response.status === 401) { if (active) forget(); return; }
          if (response.ok) { const result = await response.json(); if (active) setFlow(result); }
        }).catch(() => {});
    }, 5000);
    return () => { active = false; clearInterval(timer); };
  }, [authenticated, flow?.correlation_id, forget]);

  async function signIn() {
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/monitor/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password }) });
      if (!response.ok) throw new Error(response.status === 429 ? "Too many attempts. Try again in five minutes." : response.status === 503 ? "Monitoring sign-in is not configured or its secret provider is unavailable." : "That password wasn’t accepted.");
      setAuthenticated(true);
    } catch (e) { setError(e instanceof Error ? e.message : "Sign-in is unavailable."); }
    finally { setPassword(""); setBusy(false); }
  }
  async function signOut() {
    try { await fetch("/api/monitor/logout", { method: "POST" }); } finally { forget(); }
  }
  async function selectFlow(correlation: string, scenario: Scenario | null = null) {
    flowRequest.current?.abort();
    const controller = new AbortController(); flowRequest.current = controller;
    setFlow(null); setAttack(scenario);
    try {
      const response = await fetch(`/api/monitor/flow/${encodeURIComponent(correlation)}`, { cache: "no-store", signal: controller.signal });
      if (response.status === 401) { forget(); return; }
      if (!response.ok) throw new Error();
      const result = await response.json();
      if (!controller.signal.aborted) {
        setFlow(result);
        if (window.matchMedia("(max-width:800px)").matches) document.getElementById("ops-flow")?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    } catch { if (!controller.signal.aborted) setError("The selected trace could not be loaded. Please try again."); }
  }
  async function runTests() {
    setRunning(true); setError("");
    try {
      const response = await fetch("/api/monitor/test-runs", { method: "POST", headers: { "Content-Type": "application/json", "X-Monitor-Action": "run-tests", "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify({ suite }) });
      if (response.status === 401) { forget(); return; }
      if (!response.ok) throw new Error(response.status === 409 ? "A run is already queued or running." : response.status === 503 ? "The test worker is unavailable. No new test run was started." : "Test launch was rejected.");
      const result = await response.json(); setRunId(result.id); await load();
      if (result.scenarios?.[0]) await selectFlow(result.scenarios[0].correlation_id, result.scenarios[0]);
    } catch (e) { await load(); setError(e instanceof Error ? e.message : "Test launch failed. Check saved runs before retrying."); }
    finally { setRunning(false); }
  }

  const activeRun = data?.runs.find(r => r.id === runId) || data?.runs[0];
  const scenarios = activeRun?.result.scenarios || [];
  const activeJob = data?.runs.some(run => ["queued", "running"].includes(run.status));
  const audits = data?.audits.filter(row => `${row.tool} ${row.human} ${row.decision} ${row.reason_code} ${row.correlation_id}`.toLowerCase().includes(filter.toLowerCase())) || [];
  const firstAudit = flow?.audits[0];
  return <main className="ops-page">
    <header className="ops-header"><a href="/" className="ops-wordmark">boring-travel<span>.</span><small>OPERATIONS</small></a><span className="ops-private">Private monitoring</span>{authenticated && <button onClick={() => void signOut()}>Sign out ↗</button>}</header>
    {!authenticated ? <section className="ops-login">
      <div><p className="ops-eyebrow">BEHIND THE JOURNEY</p><h1>Every request.<br />Every decision.</h1><p>A private view of agent activity, policy decisions,<br />and recorded attack-test results.</p><a href="/">← Back to the travel company</a></div>
      <form onSubmit={e => { e.preventDefault(); void signIn(); }}><span className="ops-lock" aria-hidden="true">◇</span><h2>Operator sign-in</h2><p>Use the monitoring password configured for this environment.</p><label htmlFor="ops-password">Monitoring password</label><input id="ops-password" type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} maxLength={256} required disabled={busy || checking} />{error && <p className="ops-error" role="alert">{error}</p>}<button disabled={busy || checking || !password}>{checking ? "Checking session…" : busy ? "Signing in…" : "Open monitoring →"}</button><small>Separate from traveler accounts. Access expires after one hour.</small></form>
    </section> : <div className="ops-content">
      <div className="ops-heading"><div><p className="ops-eyebrow">OBSERVE · VERIFY · UNDERSTAND</p><h1>The control room.</h1><p>Recorded application events and controlled attack tests.</p></div><div className="ops-update"><span className="ops-live" /> Refreshes every 5 seconds<p>{updated ? `Updated ${updated}` : "Loading records…"}</p></div></div>
      {error && <p className="ops-error" role="alert">{error}</p>}
      <div className="ops-evidence"><strong>{data?.profile === "agentcore-offline" ? "AgentCore · offline implementation" : data?.profile === "local" ? "Current · local implementation" : data?.profile || "Loading environment"}</strong><span>{data?.evidence || "Loading evidence scope…"}</span></div>
      <div className="ops-metrics"><div><span>Recorded tool requests · all time</span><strong>{Object.values(data?.totals || {}).reduce((sum, n) => sum + n, 0)}</strong></div><div><span>Allowed</span><strong>{data?.totals.ALLOW || 0}</strong></div><div><span>Denied</span><strong>{data?.totals.DENY || 0}</strong></div><div><span>Human approval required</span><strong>{data?.totals.REQUIRE_APPROVAL || 0}</strong></div></div>
      <div className="ops-columns">
        <section className="ops-box ops-tests"><div className="ops-section-title"><div><p className="ops-eyebrow">CONTROLLED FIXTURES</p><h2>Test runs</h2></div><button disabled={running || activeJob || !data?.test_runner?.ready} onClick={() => void runTests()}>{running ? "Starting…" : activeJob ? "Tests in progress…" : "Run tests ↗"}</button></div>
          <label className="ops-run-picker">Test suite<select aria-label="Test suite" value={suite} onChange={e => setSuite(e.target.value)} disabled={running || activeJob}>{(data?.test_runner?.suites || []).map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
          <p className="ops-caption">{data?.test_runner?.message || "Loading test worker…"} Runs continue after you refresh or close this page. No paid model calls, resets or infrastructure changes.</p>
          {suite === "tool-changes" && <p className="ops-caption">Changes only the isolated synthetic MCP catalog. New tools stay unapproved. Vision One inventory requires separate verification; this suite is excluded from All safe checks.</p>}
          {!!data?.runs.length && <label className="ops-run-picker">Saved run<select value={activeRun?.id || ""} onChange={e => setRunId(e.target.value)}>{data.runs.map(run => <option key={run.id} value={run.id}>{date(run.started)} · {run.status}</option>)}</select></label>}
          {activeRun && <div className="ops-run-summary"><span className={badge(activeRun.status)}>{activeRun.status}</span><span>{scenarios.length}/{activeRun.result.total || scenarios.length} completed · {scenarios.filter(s => s.passed).length} passed</span><span>{activeRun.result.no_mutations === true ? "✓ Bookings unchanged" : "Booking verification pending"}</span></div>}
          {activeRun?.result.error && <p className="ops-error">{activeRun.result.error}</p>}
          {!activeRun && <p className="ops-empty">No saved runs yet. Choose a suite and run checks to record their outcomes.</p>}
          <div className="ops-scenarios">{scenarios.map(scenario => <button className={`ops-scenario ${attack?.correlation_id === scenario.correlation_id ? "selected" : ""}`} key={scenario.id} onClick={() => void selectFlow(scenario.correlation_id, scenario)}><span className="ops-scenario-number">{String(scenario.id).padStart(2, "0")}</span><div><h3>{scenario.name}</h3><p>{scenario.reason_code}</p><small>{scenario.source ? `${scenario.source} · ` : ""}Expected {scenario.expected} · {scenario.status || (scenario.passed ? "Matched" : "Mismatch")}</small></div><span className={badge(scenario.status || scenario.decision)}>{(scenario.status || scenario.decision).replaceAll("_", " ")}</span></button>)}</div>
          <p className="ops-caption">Authorization fixtures force malicious tool calls; they do not demonstrate a real model following an injection. Offline inspection results are simulations. Vendor Events remain a separate evidence source.</p>
        </section>
        <section id="ops-flow" className="ops-box ops-flow"><p className="ops-eyebrow">FOLLOW THE REQUEST</p><h2>Decision flow</h2><p className="ops-caption">Select an attack result or a tool-log row to inspect its recorded path.</p>
          {flow ? <><div className="ops-flow-summary"><span className={badge(firstAudit?.decision || "recorded")}>{firstAudit?.decision || "Recorded"}</span><code>{flow.correlation_id}</code></div>
            {attack?.evidence && <details className="ops-source" open><summary>Recorded tool-change evidence</summary><pre>{JSON.stringify(attack.evidence, null, 2)}</pre></details>}
            {attack?.attack?.source_excerpt && <details className="ops-source" open><summary>Injection source · hotel {attack.attack.source_hotel}</summary><pre>{attack.attack.source_excerpt}</pre><p>Fixture source checked in the database; the malicious call below was submitted by the test runner.</p></details>}
            {attack?.attack && <details className="ops-source"><summary>Submitted attack arguments</summary><pre>{JSON.stringify(attack.attack, null, 2)}</pre></details>}
            {flow.historical ? <div className="ops-historical"><strong>Historical audit</strong><p>Step telemetry was not recorded for this request. The audit confirms {firstAudit?.tool} → {firstAudit?.decision} → {firstAudit?.outcome}. No additional timing or hops are inferred.</p></div> : <ol className="ops-timeline">{flow.events.map(event => <li key={event.id} className={event.details.decision === "DENY" || event.stage.includes("failed") ? "blocked" : ""}><span className="ops-step-dot" /><div><time>{clock(event.at)}</time><h3>{stages[event.stage] || event.stage.replaceAll("_", " ")}</h3><p>{event.tool || `${event.human} · ${event.agent}`}</p>{Object.keys(event.details).length > 0 && <small>{Object.entries(event.details).map(([key, value]) => `${key}: ${value}`).join(" · ")}</small>}</div></li>)}</ol>}
            {firstAudit && <div className="ops-verdict"><h3>{firstAudit.downstream ? firstAudit.outcome === "completed" ? "Downstream completion recorded" : "Dispatch authorized; inspect recorded outcome" : "No downstream dispatch recorded"}</h3><p>{firstAudit.reason_code} · {firstAudit.policy_id}</p><small>Audit {firstAudit.id}</small></div>}
          </> : <div className="ops-flow-placeholder"><span>01 → 02 → 03</span><h3>A trace, backed by records.</h3><p>Request, policy, dispatch, and response events appear here when recorded. Missing steps are never filled in as observed events.</p></div>}
        </section>
      </div>
      <section className="ops-box ops-logs"><div className="ops-section-title"><div><p className="ops-eyebrow">DURABLE AUDIT LOG</p><h2>Tool decisions</h2></div><input aria-label="Filter tool logs" placeholder="Filter tool, traveler, decision, or trace…" value={filter} onChange={e => setFilter(e.target.value)} /></div><p className="ops-caption">Latest {data?.audits.length || 0} records. Each row opens its trace. Passwords, tokens, and raw chat messages are excluded.</p><div className="ops-table-scroll"><table><thead><tr><th>Time</th><th>Traveler / workload</th><th>Tool</th><th>Decision</th><th>Reason / outcome</th><th>Trace</th></tr></thead><tbody>{audits.map(row => <tr key={row.id}><td><time title={date(row.at)}>{clock(row.at)}</time></td><td>{row.human}<small>{row.agent}</small></td><td>{row.tool}<small>{row.server}</small></td><td><span className={badge(row.decision)}>{row.decision.replaceAll("_", " ")}</span></td><td>{row.reason_code}<small>{row.outcome} · {row.downstream ? "dispatch authorized" : "not dispatched"}</small></td><td><button onClick={() => void selectFlow(row.correlation_id)} aria-label={`Open trace ${row.correlation_id}`}>{row.correlation_id.slice(0, 8)} ↗</button><details><summary>JSON</summary><pre>{JSON.stringify(row, null, 2)}</pre></details></td></tr>)}</tbody></table>{!audits.length && <p className="ops-empty">No matching tool records.</p>}</div></section>
      <section className="ops-box ops-activity"><p className="ops-eyebrow">OBSERVED APPLICATION EVENTS</p><h2>Recent activity</h2><div className="ops-activity-list">{data?.activity.slice(0, 20).map(event => <div key={event.id}><time>{clock(event.at)}</time><strong>{stages[event.stage] || event.stage}</strong><span>{event.human} · {event.tool || event.agent}</span><button onClick={() => void selectFlow(event.correlation_id)}>View trace ↗</button></div>)}</div>{!data?.activity.length && <p className="ops-empty">Use the travel assistant or run a test to record activity.</p>}</section>
      <footer className="ops-footer">the boring-travel company · Private operations<span>Configured route: API → reference policy → {data?.profile === "agentcore-offline" ? "AgentCore simulator → " : data?.profile === "trend-gateway" ? "Trend MCP gateway → " : ""}MCP services. Timelines show observed application boundaries.</span></footer>
    </div>}
  </main>;
}
