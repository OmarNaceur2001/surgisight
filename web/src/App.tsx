import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent, RefObject } from "react";
import { clampPercent, confidenceState, formatDuration } from "./helpers.mjs";
import "./App.css";

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://127.0.0.1:8000";
const DISCLAIMER = "Research prototype — not for clinical use";

type Role = "admin" | "reviewer" | "researcher" | "viewer";
type User = { id: string; email: string; role: Role };
type VideoItem = {
  id: string;
  global_video_id: string;
  dataset: string;
  duration_s: number;
  fps: number;
  created_at?: string;
  disclaimer?: string;
};
type VideoDetails = VideoItem & {
  crop_offset: number[] | Record<string, number>;
  media_url: string;
  thumbnail_url: string;
  notice: string;
};
type Phase = {
  label: string;
  name: string;
  start: number;
  end: number;
  conf: number;
  uncertain: boolean;
};
type ToolUsage = { tool: string; usage_s: number; pct: number };
type KeyEvent = { type: string; t: number; conf: number; uncertain: boolean; evidence: string[] };
type Triplet = { ivt_id: number; ivt_name: string; t: number; score: number; phase?: string | null };
type Report = {
  video_id: string;
  dataset: string;
  duration_s: number;
  status: "DRAFT_PENDING_REVIEW" | "REVIEWED";
  disclaimer: string;
  phases: Phase[];
  tools: ToolUsage[];
  events: KeyEvent[];
  deviations: Array<{ type: string; phase?: string | null; value_s: number; cohort_p95_s?: number | null; cohort_n: number; wording: string }>;
  triplet_highlights: Triplet[];
  confidence_notes: string[];
  models: Record<string, string>;
  summary?: string | null;
};
type Analysis = {
  id: string;
  video_id: string;
  status: string;
  progress: number;
  stage: string;
  contract_version: string;
  model_versions: Record<string, string>;
  started_at?: string | null;
  finished_at?: string | null;
  report_id?: string | null;
};
type Detection = { t: number; tool: string; score: number; track_id: number; x1: number; y1: number; x2: number; y2: number };

async function api<T>(path: string, token: string | null, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) detail = payload.detail;
    } catch {
      // Keep the HTTP status message when the response is not JSON.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

function DetectionOverlay({ videoRef, detections }: { videoRef: RefObject<HTMLVideoElement | null>; detections: Detection[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;
    let active = true;
    let rafId = 0;
    let videoFrameId: number | undefined;
    const frameVideo = video as HTMLVideoElement & {
      requestVideoFrameCallback?: (callback: (now: number, metadata: { mediaTime: number }) => void) => number;
      cancelVideoFrameCallback?: (id: number) => void;
    };

    const draw = () => {
      if (!active || !video || !canvas) return;
      const width = video.clientWidth;
      const height = video.clientHeight;
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }
      const context = canvas.getContext("2d");
      if (context) {
        context.clearRect(0, 0, width, height);
        if (video.videoWidth > 0 && video.videoHeight > 0) {
          const sx = width / video.videoWidth;
          const sy = height / video.videoHeight;
          const visible = detections.filter((item) => Math.abs(item.t - video.currentTime) <= 0.11);
          for (const item of visible) {
            const x = item.x1 * sx;
            const y = item.y1 * sy;
            const w = Math.max(1, (item.x2 - item.x1) * sx);
            const h = Math.max(1, (item.y2 - item.y1) * sy);
            context.strokeStyle = "#65d8bd";
            context.lineWidth = 2;
            context.strokeRect(x, y, w, h);
            context.font = "12px system-ui";
            const label = item.tool;
            const labelWidth = context.measureText(label).width + 10;
            context.fillStyle = "rgba(9, 24, 33, 0.86)";
            context.fillRect(x, Math.max(0, y - 20), labelWidth, 19);
            context.fillStyle = "#ffffff";
            context.fillText(label, x + 5, Math.max(13, y - 6));
          }
        }
      }
      if (frameVideo.requestVideoFrameCallback) {
        videoFrameId = frameVideo.requestVideoFrameCallback(() => draw());
      } else {
        rafId = window.requestAnimationFrame(draw);
      }
    };

    const begin = () => {
      if (frameVideo.requestVideoFrameCallback) {
        videoFrameId = frameVideo.requestVideoFrameCallback(() => draw());
      } else {
        rafId = window.requestAnimationFrame(draw);
      }
    };
    video.addEventListener("loadedmetadata", begin);
    begin();
    return () => {
      active = false;
      video.removeEventListener("loadedmetadata", begin);
      window.cancelAnimationFrame(rafId);
      if (videoFrameId !== undefined) frameVideo.cancelVideoFrameCallback?.(videoFrameId);
    };
  }, [videoRef, detections]);

  return <canvas className="detection-overlay" ref={canvasRef} aria-hidden="true" />;
}

function App() {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [videos, setVideos] = useState<VideoItem[]>([]);
  const [selectedVideo, setSelectedVideo] = useState<VideoDetails | null>(null);
  const [selectedRun, setSelectedRun] = useState<Analysis | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [detections, setDetections] = useState<Detection[]>([]);
  const [page, setPage] = useState<"library" | "review">("library");
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [queryPhase, setQueryPhase] = useState("");
  const [queryTool, setQueryTool] = useState("");
  const [queryTriplet, setQueryTriplet] = useState("");
  const [queryEvent, setQueryEvent] = useState("");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [dataset, setDataset] = useState("cholec80");
  const [correctionPhase, setCorrectionPhase] = useState("P2");
  const [correctionEnd, setCorrectionEnd] = useState("");
  const [correctionReason, setCorrectionReason] = useState("");
  const videoRef = useRef<HTMLVideoElement>(null);

  const isReviewer = user?.role === "reviewer" || user?.role === "admin";

  const loadLibrary = useCallback(async (accessToken: string, filters: URLSearchParams = new URLSearchParams()) => {
    const suffix = filters.size ? `?${filters.toString()}` : "";
    const result = await api<{ items: VideoItem[] }>(`/videos${suffix}`, accessToken);
    setVideos(result.items);
  }, []);

  const loadReport = useCallback(async (reportId: string, accessToken: string) => {
    const result = await api<Report>(`/reports/${reportId}`, accessToken);
    setReport(result);
  }, []);

  const restoreSession = useCallback(async () => {
    try {
      const refreshed = await api<{ access_token: string }>("/auth/refresh", null, { method: "POST" });
      setToken(refreshed.access_token);
      const current = await api<User>("/auth/me", refreshed.access_token);
      setUser(current);
      await loadLibrary(refreshed.access_token);
    } catch {
      setToken(null);
      setUser(null);
    }
  }, [loadLibrary]);

  useEffect(() => {
    void restoreSession();
  }, [restoreSession]);

  const submitLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoading(true);
    setNotice("");
    try {
      const session = await api<{ access_token: string }>("/auth/login", null, {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setToken(session.access_token);
      const current = await api<User>("/auth/me", session.access_token);
      setUser(current);
      await loadLibrary(session.access_token);
      setPassword("");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Unable to sign in.");
    } finally {
      setLoading(false);
    }
  };

  const signOut = async () => {
    try {
      await api<{ status: string }>("/auth/logout", token, { method: "POST" });
    } catch {
      // Clear client state even when the API is unavailable.
    }
    setToken(null);
    setUser(null);
    setSelectedVideo(null);
    setSelectedRun(null);
    setReport(null);
    setDetections([]);
  };

  const searchLibrary = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!token) return;
    const params = new URLSearchParams();
    if (queryPhase) params.set("phase", queryPhase);
    if (queryTool) params.set("tool", queryTool);
    if (queryTriplet) params.set("triplet", queryTriplet);
    if (queryEvent) params.set("event", queryEvent);
    setLoading(true);
    try {
      await loadLibrary(token, params);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Library search could not be completed.");
    } finally {
      setLoading(false);
    }
  };

  const openVideo = async (videoId: string) => {
    if (!token) return;
    setLoading(true);
    setNotice("");
    try {
      const details = await api<VideoDetails>(`/videos/${videoId}`, token);
      setSelectedVideo(details);
      setSelectedRun(null);
      setReport(null);
      setDetections([]);
      setPage("review");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Unable to open this video.");
    } finally {
      setLoading(false);
    }
  };

  const uploadVideo = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!token || !uploadFile) return;
    setLoading(true);
    setNotice("");
    try {
      const form = new FormData();
      form.append("file", uploadFile);
      form.append("dataset", dataset);
      const created = await api<VideoDetails>("/videos", token, { method: "POST", body: form });
      setSelectedVideo(created);
      setSelectedRun(null);
      setReport(null);
      setDetections([]);
      setPage("review");
      setNotice("Video uploaded to controlled local storage. Start an analysis when ready.");
      setUploadFile(null);
      await loadLibrary(token);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Upload could not be completed.");
    } finally {
      setLoading(false);
    }
  };

  const startAnalysis = async () => {
    if (!token || !selectedVideo) return;
    setLoading(true);
    setNotice("");
    try {
      const created = await api<Analysis & { created: boolean }>(
        `/videos/${selectedVideo.id}/analyses`,
        token,
        { method: "POST", body: JSON.stringify({ config_hash: "ui_default_v1" }) },
      );
      setSelectedRun(created);
      setReport(null);
      setDetections([]);
      setNotice(created.created ? "Analysis queued for the local worker." : "An existing run was reused.");
      await loadLibrary(token);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Analysis could not be queued.");
    } finally {
      setLoading(false);
    }
  };

  const refreshAnalysis = async () => {
    if (!token || !selectedRun) return;
    setLoading(true);
    setNotice("");
    try {
      const status = await api<Analysis>(`/analyses/${selectedRun.id}`, token);
      setSelectedRun(status);
      if (status.report_id) await loadReport(status.report_id, token);
      if (status.status === "COMPLETED") {
        try {
          const predictionPage = await api<{ rows: Detection[] }>(
            `/analyses/${selectedRun.id}/predictions?stream=5hz&limit=10000`,
            token,
          );
          setDetections(predictionPage.rows);
        } catch {
          setDetections([]);
        }
      }
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Analysis status could not be retrieved.");
    } finally {
      setLoading(false);
    }
  };

  const downloadPdf = async () => {
    if (!token || !selectedRun?.report_id) return;
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE}/reports/${selectedRun.report_id}/pdf`, {
        headers: { Authorization: `Bearer ${token}` },
        credentials: "include",
      });
      if (!response.ok) throw new Error(`PDF export failed (${response.status}).`);
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = `surgisight-report-${selectedRun.report_id}.pdf`;
      anchor.click();
      URL.revokeObjectURL(objectUrl);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "PDF export could not be completed.");
    } finally {
      setLoading(false);
    }
  };

  const submitCorrection = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!token || !selectedRun?.report_id || !report) return;
    const phase = report.phases.find((item) => item.label === correctionPhase);
    const newEnd = Number(correctionEnd);
    if (!phase || !Number.isFinite(newEnd) || newEnd <= phase.start || newEnd >= report.duration_s) {
      setNotice("Enter a boundary inside the selected phase and the video duration.");
      return;
    }
    setLoading(true);
    try {
      await api(`/reports/${selectedRun.report_id}/corrections`, token, {
        method: "POST",
        body: JSON.stringify({
          target_type: "PHASE_BOUNDARY",
          target_ref: `${phase.label}_end`,
          before: { end: phase.end },
          after: { end: newEnd },
          reason: correctionReason,
        }),
      });
      setCorrectionEnd("");
      setCorrectionReason("");
      setNotice("Correction proposal appended to the review history.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Correction could not be submitted.");
    } finally {
      setLoading(false);
    }
  };

  const markReviewed = async () => {
    if (!token || !selectedRun?.report_id) return;
    setLoading(true);
    try {
      await api(`/reports/${selectedRun.report_id}/review`, token, {
        method: "POST",
        body: JSON.stringify({ status: "REVIEWED" }),
      });
      await loadReport(selectedRun.report_id, token);
      setNotice("Report status changed to reviewed.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Review status could not be changed.");
    } finally {
      setLoading(false);
    }
  };

  const seekTo = (seconds: number) => {
    if (videoRef.current) videoRef.current.currentTime = seconds;
  };

  const phaseTimeline = useMemo(() => {
    if (!report?.duration_s) return [];
    return report.phases.map((phase) => ({
      ...phase,
      left: clampPercent((phase.start / report.duration_s) * 100),
      width: clampPercent(((phase.end - phase.start) / report.duration_s) * 100),
      state: phase.uncertain || confidenceState(phase.conf) === "uncertain" ? "uncertain" : "confident",
    }));
  }, [report]);

  if (!user || !token) {
    return (
      <main className="app-shell">
        <div className="research-banner">{DISCLAIMER}</div>
        <section className="login-layout">
          <div className="brand-mark">SS</div>
          <p className="eyebrow">LAPAROSCOPIC CHOLECYSTECTOMY · RESEARCH WORKSPACE</p>
          <h1>SurgiSight</h1>
          <p className="muted">Review synchronized phase timelines, instrument activity and report drafts.</p>
          <form className="panel login-form" onSubmit={submitLogin}>
            <label>Email<input type="email" autoComplete="username" required value={email} onChange={(event) => setEmail(event.target.value)} /></label>
            <label>Password<input type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} /></label>
            <button className="primary-button" disabled={loading}>{loading ? "Signing in…" : "Sign in"}</button>
            {notice && <p className="notice" role="status">{notice}</p>}
          </form>
          <p className="microcopy">Access is restricted to authorized research accounts. Refresh credentials remain in an HttpOnly cookie.</p>
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <div className="research-banner">{DISCLAIMER}</div>
      <header className="topbar">
        <div className="brand-lockup"><span className="brand-mark small">SS</span><div><strong>SurgiSight</strong><small>Research review workspace</small></div></div>
        <nav aria-label="Main navigation">
          <button className={page === "library" ? "nav-active" : ""} onClick={() => setPage("library")}>Library</button>
          <button className={page === "review" ? "nav-active" : ""} disabled={!selectedVideo} onClick={() => setPage("review")}>Video review</button>
        </nav>
        <div className="account-area"><span>{user.email}<small>{user.role}</small></span><button className="quiet-button" onClick={() => void signOut()}>Sign out</button></div>
      </header>

      {notice && <div className="global-notice" role="status">{notice}<button aria-label="Dismiss notice" onClick={() => setNotice("")}>×</button></div>}

      {page === "library" ? (
        <section className="page-content">
          <div className="page-heading"><div><p className="eyebrow">VIDEO LIBRARY</p><h1>Research sessions</h1><p className="muted">Find recorded sessions and start a new analysis.</p></div><div className="count-chip">{videos.length} sessions</div></div>
          <form className="panel filter-panel" onSubmit={searchLibrary}>
            <label>Phase<select value={queryPhase} onChange={(event) => setQueryPhase(event.target.value)}><option value="">Any phase</option>{["P1","P2","P3","P4","P5","P6","P7"].map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
            <label>Instrument<select value={queryTool} onChange={(event) => setQueryTool(event.target.value)}><option value="">Any instrument</option>{["Grasper","Bipolar","Hook","Scissors","Clipper","Irrigator","SpecimenBag"].map((item) => <option key={item}>{item}</option>)}</select></label>
            <label>Triplet ID<input type="number" min="0" placeholder="Any" value={queryTriplet} onChange={(event) => setQueryTriplet(event.target.value)} /></label>
            <label>Event<input placeholder="e.g. first_clip" value={queryEvent} onChange={(event) => setQueryEvent(event.target.value)} /></label>
            <button className="primary-button" disabled={loading}>Search library</button>
            <button className="quiet-button" type="button" onClick={() => { setQueryPhase(""); setQueryTool(""); setQueryTriplet(""); setQueryEvent(""); void loadLibrary(token); }}>Clear</button>
          </form>

          <div className="library-grid">
            <section className="panel upload-panel">
              <p className="eyebrow">ADD A SESSION</p><h2>Upload research video</h2>
              <p className="muted">Only videos you are authorized to use under their research dataset licence may be uploaded. Files are stored in the configured local storage directory.</p>
              <form onSubmit={uploadVideo}>
                <label>Dataset identifier<input value={dataset} onChange={(event) => setDataset(event.target.value)} required maxLength={64} /></label>
                <label className="file-drop">Select video<input type="file" accept=".mp4,.mkv,.avi,.mov,.webm,video/*" onChange={(event) => setUploadFile(event.target.files?.[0] ?? null)} required /></label>
                {uploadFile && <p className="file-name">{uploadFile.name}</p>}
                <button className="primary-button" disabled={loading || !uploadFile}>{loading ? "Working…" : "Upload video"}</button>
              </form>
            </section>
            <section className="session-list">
              {videos.length === 0 ? <div className="empty-state"><div className="empty-icon">◫</div><h2>No indexed sessions yet</h2><p>Upload an authorized research video or clear filters to browse the library.</p></div> : videos.map((video) => (
                <article className="session-card" key={video.id}>
                  <div className="session-icon">▶</div>
                  <div className="session-info"><strong>{video.global_video_id}</strong><span>{video.dataset} · {formatDuration(video.duration_s)} · {video.fps.toFixed(0)} FPS</span><small>{video.created_at ? new Date(video.created_at).toLocaleDateString() : "Indexed session"}</small></div>
                  <button className="quiet-button" onClick={() => void openVideo(video.id)}>Open review →</button>
                </article>
              ))}
            </section>
          </div>
        </section>
      ) : (
        <section className="page-content review-page">
          <div className="page-heading"><div><p className="eyebrow">VIDEO REVIEW</p><h1>{selectedVideo?.global_video_id ?? "Session review"}</h1><p className="muted">{selectedVideo?.dataset} · {selectedVideo ? formatDuration(selectedVideo.duration_s) : ""}</p></div><div className="review-actions"><button className="quiet-button" onClick={() => setPage("library")}>← Library</button><button className="primary-button" onClick={() => void startAnalysis()} disabled={loading || !selectedVideo}>Start analysis</button></div></div>
          <div className="review-grid">
            <section className="panel video-panel">
              <div className="panel-heading"><div><p className="eyebrow">SYNCHRONIZED PLAYER</p><h2>Recorded procedure</h2></div><span className="status-pill">{selectedRun?.status ?? "No analysis"}</span></div>
              {selectedVideo?.media_url ? <div className="video-frame"><video ref={videoRef} controls preload="metadata" src={selectedVideo.media_url.startsWith("http") ? selectedVideo.media_url : `${API_BASE}${selectedVideo.media_url}`} /><DetectionOverlay videoRef={videoRef} detections={detections} /></div> : <div className="empty-video">Select a session to load its video.</div>}
              <div className="player-foot"><span>Time-based navigation uses seconds from video start.</span><button className="quiet-button" onClick={() => void refreshAnalysis()} disabled={!selectedRun || loading}>Refresh analysis status</button></div>
              {selectedRun && <div className="run-progress"><div><span>{selectedRun.stage}</span><strong>{Math.round(selectedRun.progress * 100)}%</strong></div><div className="progress-track"><span style={{ width: `${clampPercent(selectedRun.progress * 100)}%` }} /></div><small>Run {selectedRun.id}</small></div>}
            </section>

            <section className="panel timeline-panel">
              <div className="panel-heading"><div><p className="eyebrow">M2 · 1 HZ</p><h2>Phase timeline</h2></div>{report && <span className={report.status === "REVIEWED" ? "status-pill reviewed" : "status-pill"}>{report.status.replaceAll("_", " ")}</span>}</div>
              {!report ? <div className="empty-state compact"><p>Phase segments will appear when the analysis worker completes a run.</p></div> : <>
                <div className="timeline-ruler"><span>00:00</span><span>{formatDuration(report.duration_s / 2)}</span><span>{formatDuration(report.duration_s)}</span></div>
                <div className="timeline-track" aria-label="Click a phase segment to seek the video">
                  {phaseTimeline.map((phase) => <button key={phase.label} className={`phase-segment ${phase.state}`} style={{ left: `${phase.left}%`, width: `${phase.width}%` }} title={`${phase.label} · ${phase.name} · ${formatDuration(phase.end - phase.start)}`} onClick={() => seekTo(phase.start)}><span>{phase.label}</span></button>)}
                </div>
                <div className="phase-list">{report.phases.map((phase) => <button key={phase.label} className="phase-row" onClick={() => seekTo(phase.start)}><span className="phase-dot" /><span className="phase-name"><strong>{phase.label}</strong>{phase.name}</span><span className="phase-time">{formatDuration(phase.start)}–{formatDuration(phase.end)}</span><span className={`confidence ${confidenceState(phase.conf)}`}>{Math.round(phase.conf * 100)}%</span></button>)}</div>
                <div className="legend"><span><i className="legend-solid" />Observed confidence at or above threshold</span><span><i className="legend-hatched" />Uncertain segment</span></div>
              </>}
            </section>
          </div>

          {report && <div className="detail-grid">
            <section className="panel">
              <div className="panel-heading"><div><p className="eyebrow">INSTRUMENT ACTIVITY</p><h2>Tool presence summary</h2></div><small>Usage may overlap</small></div>
              <div className="tool-list">{report.tools.map((tool) => <div className="tool-row" key={tool.tool}><span>{tool.tool}</span><div className="tool-meter"><i style={{ width: `${clampPercent(tool.pct)}%` }} /></div><strong>{formatDuration(tool.usage_s)}</strong><small>{tool.pct.toFixed(1)}%</small></div>)}</div>
            </section>
            <section className="panel">
              <div className="panel-heading"><div><p className="eyebrow">OBSERVED MILESTONES</p><h2>Key events</h2></div><small>{report.events.length} events</small></div>
              {report.events.length ? <div className="event-list">{report.events.map((item, index) => <button key={`${item.type}-${index}`} className="event-row" onClick={() => seekTo(item.t)}><span className="event-marker">◆</span><span><strong>{item.type.replaceAll("_", " ")}</strong><small>{item.evidence.join(" · ") || "No evidence details recorded"}</small></span><time>{formatDuration(item.t)}</time><span className={`confidence ${confidenceState(item.conf)}`}>{Math.round(item.conf * 100)}%</span></button>)}</div> : <p className="muted">No key events recorded in this report.</p>}
            </section>
          </div>}

          {report && <div className="detail-grid lower-grid">
            <section className="panel">
              <div className="panel-heading"><div><p className="eyebrow">REPORT DRAFT</p><h2>Report preview</h2></div><span className="status-pill">{report.status.replaceAll("_", " ")}</span></div>
              <p className="report-disclaimer">{report.disclaimer}</p>
              <dl className="report-metadata"><div><dt>Dataset</dt><dd>{report.dataset}</dd></div><div><dt>Duration</dt><dd>{formatDuration(report.duration_s)}</dd></div><div><dt>Phase segments</dt><dd>{report.phases.length}</dd></div><div><dt>Model components</dt><dd>{Object.keys(report.models).join(", ") || "Not recorded"}</dd></div></dl>
              {report.confidence_notes.length > 0 && <div className="notes"><strong>Confidence notes</strong>{report.confidence_notes.map((note, index) => <p key={index}>{note}</p>)}</div>}
              {report.deviations.length > 0 && <div className="notes"><strong>Reference cohort observations</strong>{report.deviations.map((item, index) => <p key={index}>{item.wording}</p>)}</div>}
              <button className="primary-button" onClick={() => void downloadPdf()} disabled={loading || !selectedRun?.report_id}>Export PDF</button>
            </section>
            <section className="panel">
              <div className="panel-heading"><div><p className="eyebrow">HUMAN REVIEW</p><h2>Correction proposal</h2></div><span className="append-only-tag">Append-only</span></div>
              <p className="muted">Proposals are recorded with before/after values, author and timestamp. Existing entries cannot be edited or removed.</p>
              <form className="correction-form" onSubmit={submitCorrection}>
                <label>Phase boundary<select value={correctionPhase} onChange={(event) => setCorrectionPhase(event.target.value)}>{report.phases.map((phase) => <option value={phase.label} key={phase.label}>{phase.label} · {phase.name}</option>)}</select></label>
                <label>Proposed end time (seconds)<input type="number" step="0.01" min="0" value={correctionEnd} onChange={(event) => setCorrectionEnd(event.target.value)} required /></label>
                <label>Reason<textarea value={correctionReason} onChange={(event) => setCorrectionReason(event.target.value)} minLength={3} maxLength={4000} required rows={3} /></label>
                <button className="secondary-button" disabled={loading || !selectedRun?.report_id}>Append proposal</button>
              </form>
              {isReviewer && report.status === "DRAFT_PENDING_REVIEW" && <div className="review-approval"><p>Reviewer access is available for this draft.</p><button className="primary-button" onClick={() => void markReviewed()} disabled={loading}>Mark report reviewed</button></div>}
              {isReviewer && report.status === "REVIEWED" && <p className="reviewed-note">This report has been marked reviewed.</p>}
            </section>
          </div>}
        </section>
      )}
      <footer className="app-footer"><span>{DISCLAIMER}</span><span>Data and model artifacts remain in configured local storage.</span></footer>
    </main>
  );
}

export default App;
