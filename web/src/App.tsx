import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import {
  apiBaseUrl,
  apiRequest,
  getAccessToken,
  restoreSession,
  signIn,
  signOut,
  type Analysis,
  type LibraryVideo,
  type Report,
  type User,
  type VideoDetails,
} from "./api";
import { strings as s } from "./strings";
import { confidenceLabel, formatDuration, phaseWidth } from "./presentation.mjs";
import "./App.css";

type View = "library" | "upload" | "review";
type ReplayRecord = { record: { t: number; phase: { label: string; probs: Record<string, number> }; tools: { probs: Record<string, number> } }; latency_ms: number };
type LibraryResponse = { items: LibraryVideo[]; total: number };
type CohortResponse = { items: { version: string; phase: string | null; statistic: string; value: number; n_videos: number }[] };
type LatencyResponse = { stages: Record<string, { count: number; p50_ms: number; p95_ms: number; max_ms: number }> };
type CorrectionPayload = {
  target_type: string; target_ref: string; before: Record<string, unknown>;
  after: Record<string, unknown>; reason: string;
};

function ResearchBanner() {
  return <div className="research-banner" role="note">{s.notice}</div>;
}

function Login({ onLogin }: { onLogin: (email: string, password: string) => Promise<void> }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await onLogin(email, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : s.error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="login-shell">
      <ResearchBanner />
      <form className="login-card" onSubmit={submit}>
        <div className="eyebrow">SURGICAL VIDEO RESEARCH</div>
        <h1>{s.appName}</h1>
        <p className="muted">Sign in to the controlled research workspace.</p>
        <label>{s.email}<input type="email" autoComplete="username" required value={email} onChange={e => setEmail(e.target.value)} /></label>
        <label>{s.password}<input type="password" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)} /></label>
        {error && <p className="inline-error" role="alert">{error}</p>}
        <button className="primary wide" type="submit" disabled={busy}>{busy ? s.loading : s.signIn}</button>
      </form>
    </main>
  );
}

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [restoring, setRestoring] = useState(true);
  const [view, setView] = useState<View>("library");
  const [videos, setVideos] = useState<LibraryVideo[]>([]);
  const [selected, setSelected] = useState<LibraryVideo | null>(null);
  const [details, setDetails] = useState<VideoDetails | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [phaseFilter, setPhaseFilter] = useState("");
  const [toolFilter, setToolFilter] = useState("");
  const [tripletFilter, setTripletFilter] = useState("");
  const [eventFilter, setEventFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [correctionType, setCorrectionType] = useState("REPORT_NOTE");
  const [correctionRef, setCorrectionRef] = useState("review-note");
  const [correctionBefore, setCorrectionBefore] = useState("");
  const [correctionAfter, setCorrectionAfter] = useState("");
  const [correctionReason, setCorrectionReason] = useState("");
  const [latestRecord, setLatestRecord] = useState<ReplayRecord | null>(null);
  const [cohortStats, setCohortStats] = useState<CohortResponse["items"]>([]);
  const [latencyStages, setLatencyStages] = useState<LatencyResponse["stages"]>({});
  const [replaying, setReplaying] = useState(false);
  const [socketState, setSocketState] = useState("idle");
  const videoRef = useRef<HTMLVideoElement>(null);
  const socketRef = useRef<WebSocket | null>(null);

  const canResearch = user?.role === "admin" || user?.role === "reviewer" || user?.role === "researcher";
  const canReview = user?.role === "admin" || user?.role === "reviewer";

  const loadLibrary = useCallback(async () => {
    const query = new URLSearchParams();
    if (phaseFilter) query.set("phase", phaseFilter);
    if (toolFilter) query.set("tool", toolFilter);
    if (tripletFilter) query.set("triplet", tripletFilter);
    if (eventFilter) query.set("event", eventFilter);
    const result = await apiRequest<LibraryResponse>(`/videos?${query.toString()}`);
    setVideos(result.items);
  }, [phaseFilter, toolFilter, tripletFilter, eventFilter]);

  const selectVideo = useCallback(async (item: LibraryVideo) => {
    setSelected(item);
    setDetails(null);
    setReport(null);
    setAnalysis(null);
    setMessage("");
    setError("");
    try {
      const [video, run] = await Promise.all([
        apiRequest<VideoDetails>(`/videos/${item.id}`),
        item.latest_run_id ? apiRequest<Analysis>(`/analyses/${item.latest_run_id}`) : Promise.resolve(null),
      ]);
      setDetails(video);
      setAnalysis(run);
      const reportId = item.report_id ?? run?.report_id;
      if (reportId) setReport(await apiRequest<Report>(`/reports/${reportId}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : s.error);
    }
  }, []);

  useEffect(() => {
    let active = true;
    restoreSession().then(restored => {
      if (active) setUser(restored);
    }).catch(() => {
      if (active) setUser(null);
    }).finally(() => {
      if (active) setRestoring(false);
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!user) return;
    loadLibrary().catch(err => setError(err instanceof Error ? err.message : s.error));
  }, [user, loadLibrary]);

  useEffect(() => () => {
    socketRef.current?.close();
  }, []);

  async function handleLogin(email: string, password: string) {
    const result = await signIn(email, password);
    setUser(result.user);
    setView("library");
    setMessage("Signed in.");
  }

  async function handleLogout() {
    stopReplay();
    await signOut();
    setUser(null);
    setVideos([]);
    setSelected(null);
    setReport(null);
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!uploadFile) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const form = new FormData();
      form.append("file", uploadFile);
      form.append("dataset", "research_upload");
      const response = await apiRequest<VideoDetails>("/videos", { method: "POST", body: form });
      setMessage(`Added ${response.global_video_id}. ${s.uploadNotice}`);
      setUploadFile(null);
      await loadLibrary();
      setView("library");
    } catch (err) {
      setError(err instanceof Error ? err.message : s.error);
    } finally {
      setBusy(false);
    }
  }

  async function startAnalysis() {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      const created = await apiRequest<Analysis>(`/videos/${selected.id}/analyses`, {
        method: "POST",
        body: JSON.stringify({ model_versions: { M2: "feature-flag-provider", M3: "mock", M4: "mock" }, config_hash: "dashboard-default-v1" }),
      });
      setAnalysis(created);
      setMessage(`Analysis ${created.id} was queued. Refresh the video record for updated progress.`);
      await loadLibrary();
    } catch (err) {
      setError(err instanceof Error ? err.message : s.error);
    } finally {
      setBusy(false);
    }
  }

  async function saveCorrection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || !report) return;
    setBusy(true);
    setError("");
    const payload: CorrectionPayload = {
      target_type: correctionType,
      target_ref: correctionRef,
      before: { value: correctionBefore },
      after: { value: correctionAfter },
      reason: correctionReason,
    };
    try {
      await apiRequest(`/reports/${selected.report_id ?? analysis?.report_id}/corrections`, {
        method: "POST", body: JSON.stringify(payload),
      });
      setMessage("Review proposal saved to the append-only history.");
      setCorrectionBefore("");
      setCorrectionAfter("");
      setCorrectionReason("");
    } catch (err) {
      setError(err instanceof Error ? err.message : s.error);
    } finally {
      setBusy(false);
    }
  }

  async function generateSummary() {
    const reportId = selected?.report_id ?? analysis?.report_id;
    if (!reportId) return;
    setBusy(true);
    try {
      const result = await apiRequest<{ summary: string; valid: boolean }>(
        `/reports/${reportId}/summary`,
        { method: "POST" },
      );
      if (result.valid) {
        setReport(current => current ? { ...current, summary: result.summary } : current);
        setMessage(s.summarySaved);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : s.error);
    } finally {
      setBusy(false);
    }
  }

  async function loadCohort() {
    try {
      const result = await apiRequest<CohortResponse>("/cohort/stats");
      setCohortStats(result.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : s.error);
    }
  }

  async function loadLatency() {
    try {
      const result = await apiRequest<LatencyResponse>("/metrics/latency");
      setLatencyStages(result.stages);
    } catch (err) {
      setError(err instanceof Error ? err.message : s.error);
    }
  }

  async function markReviewed() {
    const reportId = selected?.report_id ?? analysis?.report_id;
    if (!reportId) return;
    setBusy(true);
    try {
      await apiRequest(`/reports/${reportId}/review`, { method: "POST" });
      setReport(await apiRequest<Report>(`/reports/${reportId}`));
      setMessage("Report status updated to REVIEWED.");
    } catch (err) {
      setError(err instanceof Error ? err.message : s.error);
    } finally {
      setBusy(false);
    }
  }

  async function downloadPdf() {
    const reportId = selected?.report_id ?? analysis?.report_id;
    if (!reportId) return;
    try {
      const file = await apiRequest<Blob>(`/reports/${reportId}/pdf`);
      const url = URL.createObjectURL(file);
      const link = document.createElement("a");
      link.href = url;
      link.download = `surgisight-report-${reportId}.pdf`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : s.error);
    }
  }

  function startReplay(mode: "saved" | "live" = "saved") {
    if (!analysis?.id) return;
    const base = new URL(apiBaseUrl());
    base.protocol = base.protocol === "https:" ? "wss:" : "ws:";
    base.pathname = `/ws/replay/${analysis.id}`;
    base.search = "";
    const socket = new WebSocket(base.toString());
    socketRef.current = socket;
    setReplaying(true);
    setSocketState("connecting");
    socket.onopen = () => {
      setSocketState("streaming");
      socket.send(JSON.stringify({ type: "auth", access_token: getAccessToken() ?? "", speed: 4, mode }));
    };
    socket.onmessage = event => {
      try {
        setLatestRecord(JSON.parse(event.data) as ReplayRecord);
      } catch {
        setSocketState("invalid message");
      }
    };
    socket.onerror = () => setSocketState("connection issue");
    socket.onclose = () => {
      setReplaying(false);
      setSocketState("closed");
    };
  }

  function stopReplay() {
    socketRef.current?.close();
    socketRef.current = null;
    setReplaying(false);
    setSocketState("stopped");
  }

  async function applySearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      await loadLibrary();
    } catch (err) {
      setError(err instanceof Error ? err.message : s.error);
    }
  }

  if (restoring) return <main className="login-shell"><ResearchBanner /><div className="loading-card">{s.loading}</div></main>;
  if (!user) return <Login onLogin={handleLogin} />;

  return (
    <div className="app-shell">
      <ResearchBanner />
      <header className="topbar">
        <div className="brand-mark"><span className="brand-icon">S</span><div><strong>{s.appName}</strong><small>OPERATIVE VIDEO REVIEW</small></div></div>
        <div className="topbar-right"><span className="role-chip">{user.role}</span><span className="account-email">{user.email}</span><button className="quiet" onClick={handleLogout}>{s.signOut}</button></div>
      </header>
      <div className="workspace">
        <aside className="sidebar">
          <div className="sidebar-label">{s.dashboard}</div>
          <button className={view === "library" ? "nav-item active" : "nav-item"} onClick={() => setView("library")}>▦ <span>{s.library}</span></button>
          <button className={view === "upload" ? "nav-item active" : "nav-item"} onClick={() => setView("upload")} disabled={!canResearch}>＋ <span>{s.upload}</span></button>
          <button className={view === "review" ? "nav-item active" : "nav-item"} onClick={() => setView("review")} disabled={!selected}>◫ <span>{s.review}</span></button>
          <div className="sidebar-foot"><span className="status-dot" /> API-connected workspace</div>
        </aside>
        <main className="main-content">
          <div className="page-heading">
            <div><div className="eyebrow">SURGISIGHT / {view.toUpperCase()}</div><h1>{view === "library" ? s.library : view === "upload" ? s.upload : s.review}</h1></div>
            <div className="heading-actions"><button className="secondary" onClick={() => loadLibrary().catch(err => setError(String(err)))}>{s.refresh}</button></div>
          </div>
          {message && <div className="notice success" role="status">{message}<button onClick={() => setMessage("")} aria-label="Dismiss">×</button></div>}
          {error && <div className="notice error" role="alert">{error}<button onClick={() => setError("")} aria-label="Dismiss">×</button></div>}

          {view === "library" && (
            <section className="library-layout">
              <div className="library-panel panel">
                <form className="filters" onSubmit={applySearch}>
                  <label>{s.phase}<select value={phaseFilter} onChange={e => setPhaseFilter(e.target.value)}><option value="">{s.all}</option>{["P1","P2","P3","P4","P5","P6","P7"].map(p => <option key={p}>{p}</option>)}</select></label>
                  <label>{s.tool}<input value={toolFilter} onChange={e => setToolFilter(e.target.value)} placeholder="Grasper…" /></label>
                  <label>{s.triplet}<input value={tripletFilter} onChange={e => setTripletFilter(e.target.value)} placeholder="instrument, verb, target" /></label>
                  <label>{s.event}<input value={eventFilter} onChange={e => setEventFilter(e.target.value)} placeholder="first_clip…" /></label>
                  <button className="primary" type="submit">{s.search}</button>
                </form>
                <div className="panel-heading"><strong>{videos.length} videos</strong><span>Research library</span></div>
                {videos.length === 0 ? <div className="empty-state"><div className="empty-icon">▧</div><p>{s.noVideos}</p>{canResearch && <button className="secondary" onClick={() => setView("upload")}>{s.upload}</button>}</div> :
                  <div className="video-list">{videos.map(item => (
                    <button key={item.id} className={selected?.id === item.id ? "video-row chosen" : "video-row"} onClick={() => selectVideo(item)}>
                      <div className="video-thumb"><span>▶</span></div>
                      <div className="video-meta"><strong>{item.global_video_id}</strong><small>{item.dataset} · {formatDuration(item.duration_s)}</small><small>Created {new Date(item.created_at).toLocaleDateString()}</small></div>
                      <span className={item.latest_run_status === "COMPLETED" ? "status-badge done" : "status-badge"}>{item.latest_run_status ?? "unanalysed"}</span>
                    </button>
                  ))}</div>}
              </div>
              <div className="detail-panel">
                {!selected ? <div className="panel empty-state tall"><div className="empty-icon">◫</div><p>{s.selectVideo}</p></div> :
                  <div className="panel selected-summary">
                    <div className="panel-heading"><strong>Selected video</strong><span className="status-badge">{selected.latest_run_status ?? "No analysis"}</span></div>
                    <h2>{selected.global_video_id}</h2>
                    <dl className="facts"><div><dt>{s.duration}</dt><dd>{formatDuration(selected.duration_s)}</dd></div><div><dt>FPS</dt><dd>{selected.fps}</dd></div><div><dt>Dataset</dt><dd>{selected.dataset}</dd></div></dl>
                    {analysis && <div className="analysis-progress"><div><span>{analysis.stage}</span><strong>{Math.round(analysis.progress * 100)}%</strong></div><div className="progress-track"><i style={{ width: `${Math.round(analysis.progress * 100)}%` }} /></div><small>{analysis.status}</small></div>}
                    {canResearch && <button className="primary wide" onClick={startAnalysis} disabled={busy}>{s.startAnalysis}</button>}
                    <button className="secondary wide" onClick={() => setView("review")}>Open review workspace</button>
                  </div>}
              </div>
            </section>
          )}

          {view === "upload" && (
            <section className="panel upload-panel">
              <div className="upload-art">⇧</div><h2>Add a research video</h2><p>{s.uploadNotice}</p>
              <form onSubmit={handleUpload}>
                <label className="file-drop"> <input type="file" accept="video/mp4,video/x-matroska,video/avi,video/quicktime,video/webm" onChange={e => setUploadFile(e.target.files?.[0] ?? null)} />
                  <strong>{uploadFile?.name ?? s.chooseFile}</strong><small>MP4 · MKV · AVI · MOV · WEBM</small>
                </label>
                <button className="primary" type="submit" disabled={!uploadFile || busy}>{busy ? s.loading : s.upload}</button>
              </form>
            </section>
          )}

          {view === "review" && (
            <section className="review-grid">
              {!selected ? <div className="panel empty-state tall">{s.selectVideo}</div> : <>
                <div className="review-main">
                  <section className="panel media-panel">
                    <div className="panel-heading"><div><strong>{selected.global_video_id}</strong><small>{details ? formatDuration(details.duration_s) : s.loading}</small></div><div className="media-actions">{analysis && !replaying && <><button className="secondary" onClick={() => startReplay("saved")}>{s.replay}</button><button className="secondary" onClick={() => startReplay("live")}>{s.liveM2Replay}</button></>}{replaying && <button className="secondary" onClick={stopReplay}>{s.stopReplay}</button>}</div></div>
                    <video ref={videoRef} controls preload="metadata" src={details?.media_url} />
                    {latestRecord && <div className="stream-status"><span className="live-dot" /> Replay {socketState} · {latestRecord.record.phase.label} · t={latestRecord.record.t.toFixed(0)}s · {latestRecord.latency_ms.toFixed(2)} ms record packaging</div>}
                  </section>
                  {report ? <>
                    <section className="panel timeline-panel">
                      <div className="panel-heading"><div><strong>{s.phaseTimeline}</strong><small>Click a segment to seek</small></div><span className="status-badge">{report.status}</span></div>
                      <div className="phase-timeline" aria-label={s.phaseTimeline}>
                        {report.phases.map((phase, index) => <button key={`${phase.label}-${index}`} title={`${phase.name}: ${phase.start}s–${phase.end}s`} className={phase.uncertain ? "phase-block uncertain" : "phase-block"} style={{ width: `${phaseWidth(phase.start, phase.end, report.duration_s)}%` }} onClick={() => { if (videoRef.current) videoRef.current.currentTime = phase.start; }}><span>{phase.label}</span></button>)}
                      </div>
                      <div className="phase-legend">{report.phases.map((p,i) => <span key={`${p.label}-legend-${i}`}><i className={p.uncertain ? "legend-dot uncertain" : "legend-dot"} />{p.label} {p.name}</span>)}</div>
                    </section>
                    <section className="panel">
                      <div className="panel-heading"><strong>{s.toolPresence}</strong><small>Observed presence, overlapping durations</small></div>
                      <div className="tool-list">{report.tools.map(t => <div className="tool-row" key={t.tool}><span>{t.tool}</span><div className="progress-track"><i style={{ width: `${t.pct}%` }} /></div><strong>{t.pct.toFixed(1)}%</strong></div>)}</div>
                    </section>
                    <section className="panel">
                      <div className="panel-heading"><strong>{s.keyEvents}</strong><small>Timeline references</small></div>
                      {report.events.length ? <div className="event-list">{report.events.map((event,i) => <button className="event-row" key={`${event.type}-${i}`} onClick={() => { if (videoRef.current) videoRef.current.currentTime = event.t; }}><span className="event-time">{formatDuration(event.t)}</span><span>{event.type.replaceAll("_"," ")}</span><span className={event.uncertain ? "uncertain-chip" : "confidence-chip"}>{event.uncertain ? s.uncertain : confidenceLabel(event.conf)}</span></button>)}</div> : <p className="muted pad">No events are listed in this report.</p>}
                    </section>
                    <section className="panel">
                      <div className="panel-heading"><strong>{s.summaryTitle}</strong><small>{s.summarySource}</small></div>
                      {report.summary ? <p>{report.summary}</p> : <p className="muted">{s.noSummary}</p>}
                      {report.status !== "REVIEWED" && <button className="secondary" onClick={generateSummary} disabled={busy}>{s.generateSummary}</button>}
                    </section>
                    <section className="panel">
                      <div className="panel-heading"><strong>{s.corrections}</strong><small>Proposals are stored as append-only entries</small></div>
                      {report.status !== "REVIEWED" && canResearch && <form className="correction-form" onSubmit={saveCorrection}>
                        <label>Category<select value={correctionType} onChange={e => setCorrectionType(e.target.value)}><option value="REPORT_NOTE">Report note</option><option value="PHASE_BOUNDARY">Phase boundary</option><option value="PHASE_LABEL">Phase label</option><option value="KEY_EVENT">Key event</option><option value="TOOL_INTERVAL">Tool interval</option></select></label>
                        <label>{s.target}<input required value={correctionRef} onChange={e => setCorrectionRef(e.target.value)} /></label>
                        <div className="form-two"><label>{s.before}<input value={correctionBefore} onChange={e => setCorrectionBefore(e.target.value)} /></label><label>{s.after}<input value={correctionAfter} onChange={e => setCorrectionAfter(e.target.value)} /></label></div>
                        <label>{s.reason}<textarea required minLength={3} value={correctionReason} onChange={e => setCorrectionReason(e.target.value)} /></label>
                        <button className="primary" type="submit" disabled={busy}>{s.submitCorrection}</button>
                      </form>}
                      {report.status === "REVIEWED" && <p className="muted pad">This report is read-only after review.</p>}
                      <div className="review-actions"><button className="secondary" onClick={downloadPdf}>{s.downloadPdf}</button>{canReview && report.status !== "REVIEWED" && <button className="primary" onClick={markReviewed} disabled={busy}>{s.markReviewed}</button>}</div>
                    </section>
                  </> : <div className="panel empty-state"><p>{s.noReport}</p>{analysis && <small>{analysis.status} · {analysis.stage}</small>}</div>}
                </div>
                <aside className="review-side">
                  <div className="panel side-card"><div className="panel-heading"><strong>Video metadata</strong></div><dl className="facts stacked"><div><dt>Duration</dt><dd>{details ? formatDuration(details.duration_s) : "—"}</dd></div><div><dt>Frame rate</dt><dd>{details?.fps ?? "—"}</dd></div><div><dt>Crop offset</dt><dd>{details?.crop_offset.join(", ") ?? "—"}</dd></div><div><dt>Dataset</dt><dd>{details?.dataset ?? selected.dataset}</dd></div></dl></div>
                  <div className="panel side-card"><div className="panel-heading"><strong>{s.model}</strong></div>{report ? Object.entries(report.models).map(([name,version]) => <div className="model-row" key={name}><span>{name}</span><small>{version}</small></div>) : <p className="muted">Model metadata is not available yet.</p>}</div>
                  <div className="panel side-card"><div className="panel-heading"><strong>Confidence notes</strong></div>{report?.confidence_notes.length ? report.confidence_notes.map((note,i) => <p className="note" key={i}>{note}</p>) : <p className="muted">No confidence notes.</p>}</div>
                  <div className="panel side-card"><div className="panel-heading"><strong>Replay monitor</strong><span className="status-badge">{socketState}</span></div><p className="muted">{s.savedReplayDescription}</p>{latestRecord && <><strong>{latestRecord.record.phase.label}</strong><small>Time {latestRecord.record.t.toFixed(1)} s · {latestRecord.latency_ms.toFixed(2)} ms step</small></>}</div>
                  <div className="panel side-card"><div className="panel-heading"><strong>{s.cohort}</strong></div><button className="secondary wide" onClick={loadCohort}>{s.loadCohort}</button>{cohortStats.length ? cohortStats.map((row,i) => <div className="model-row" key={`${row.version}-${row.phase}-${row.statistic}-${i}`}><span>{row.phase ?? "All phases"} · {row.statistic}</span><small>{row.value} · n={row.n_videos}</small></div>) : <p className="muted">{s.noCohort}</p>}</div>
                  <div className="panel side-card"><div className="panel-heading"><strong>{s.latency}</strong></div><button className="secondary wide" onClick={loadLatency}>{s.refreshMetrics}</button>{Object.entries(latencyStages).map(([stage,metric]) => <div className="model-row" key={stage}><span>{stage}</span><small>{metric.p50_ms} / {metric.p95_ms} ms · n={metric.count}</small></div>)}</div>
                </aside>
              </>}
            </section>
          )}
        </main>
      </div>
    </div>
  );
}

export default App;
