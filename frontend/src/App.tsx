import { useEffect, useRef, useState, type FormEvent } from "react";
import "./App.css";
import { createJob, getJob, JobNotFoundError, type JobRecord } from "./api";
import { MarkdownReport } from "./MarkdownReport";

// The backend clones the repo once (deep enough to cover both structure and
// git history) and reports that single clone under "cloning_structure" --
// there's no separate clone-history step to show progress for.
const STAGES = [
  "cloning_structure",
  "parsing",
  "building_graph",
  "analyzing_quality",
  "scanning_security",
  "analyzing_git_history",
  "generating_documentation",
];

const STAGE_LABELS: Record<string, string> = {
  cloning_structure: "Cloning repository",
  parsing: "Parsing source files",
  building_graph: "Building dependency graph",
  analyzing_quality: "Analyzing code quality",
  scanning_security: "Scanning for security issues",
  analyzing_git_history: "Analyzing git history",
  generating_documentation: "Generating documentation",
};

type ViewState = "idle" | "running" | "done" | "error";

interface AppProps {
  pollIntervalMs?: number;
}

const ACTIVE_JOB_KEY = "atlas.activeJob";

interface SavedJob {
  jobId: string;
  repoUrl: string;
}

function saveActiveJob(jobId: string, repoUrl: string) {
  try {
    localStorage.setItem(ACTIVE_JOB_KEY, JSON.stringify({ jobId, repoUrl }));
  } catch {
    // localStorage unavailable (private mode, quota) -- recovery is best-effort
  }
}

function loadActiveJob(): SavedJob | null {
  try {
    const raw = localStorage.getItem(ACTIVE_JOB_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (typeof parsed?.jobId === "string" && typeof parsed?.repoUrl === "string") {
      return parsed;
    }
    return null;
  } catch {
    return null;
  }
}

function clearActiveJob() {
  try {
    localStorage.removeItem(ACTIVE_JOB_KEY);
  } catch {
    // ignore
  }
}

function App({ pollIntervalMs = 1000 }: AppProps) {
  const [repoUrl, setRepoUrl] = useState("");
  const [view, setView] = useState<ViewState>("idle");
  const [job, setJob] = useState<JobRecord | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const pollRef = useRef<number | null>(null);
  const timerRef = useRef<number | null>(null);
  const hasCheckedRecovery = useRef(false);

  useEffect(() => {
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
      if (timerRef.current) window.clearInterval(timerRef.current);
    };
  }, []);

  function stopTimers() {
    if (pollRef.current) window.clearInterval(pollRef.current);
    if (timerRef.current) window.clearInterval(timerRef.current);
  }

  function startTracking(jobId: string, initialElapsedSeconds: number) {
    stopTimers(); // never let a stale poll/timer pair from a prior job outlive this one
    setElapsedSeconds(initialElapsedSeconds);

    timerRef.current = window.setInterval(() => {
      setElapsedSeconds((s) => s + 1);
    }, pollIntervalMs);

    pollRef.current = window.setInterval(async () => {
      try {
        const record = await getJob(jobId);
        setJob(record);
        if (record.status === "done" || record.status === "error") {
          stopTimers();
          clearActiveJob();
          setView(record.status);
        }
      } catch {
        // A single dropped poll isn't a job failure — retry on the next tick.
      }
    }, pollIntervalMs);
  }

  // Recover a job that was still active before a refresh/reconnect. Runs once
  // on mount; guarded against StrictMode's dev-mode double-invoke.
  useEffect(() => {
    if (hasCheckedRecovery.current) return;
    hasCheckedRecovery.current = true;

    const saved = loadActiveJob();
    if (!saved) return;

    setRepoUrl(saved.repoUrl);
    setView("running");

    (async () => {
      try {
        const record = await getJob(saved.jobId);
        setJob(record);
        if (record.status === "done" || record.status === "error") {
          clearActiveJob();
          setView(record.status);
          return;
        }
        const createdAtMs = Date.parse(record.created_at);
        const elapsed = Number.isNaN(createdAtMs)
          ? 0
          : Math.max(0, Math.floor((Date.now() - createdAtMs) / 1000));
        startTracking(saved.jobId, elapsed);
      } catch (err) {
        if (err instanceof JobNotFoundError) {
          // The job is genuinely gone (expired, DB reset, etc.) -- give up gracefully.
          clearActiveJob();
          setView("idle");
        } else {
          // A transient failure (network blip, backend still booting) isn't proof the
          // job is gone -- keep the saved job and let the normal poll loop's own
          // dropped-request tolerance retry on the next tick.
          startTracking(saved.jobId, 0);
        }
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (submitting) return; // guards against a double-click firing two jobs
    setSubmitError(null);
    setSubmitting(true);
    try {
      const { job_id } = await createJob(repoUrl);
      saveActiveJob(job_id, repoUrl);
      setJob(null);
      setView("running");
      startTracking(job_id, 0);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to start analysis");
    } finally {
      setSubmitting(false);
    }
  }

  function reset() {
    stopTimers();
    clearActiveJob();
    setView("idle");
    setJob(null);
    setSubmitError(null);
    setRepoUrl("");
  }

  const currentStageIndex = job?.stage ? STAGES.indexOf(job.stage) : -1;

  return (
    <div className="app">
      <h1>Atlas</h1>

      {view === "idle" && (
        <>
          <p className="tagline">
            Paste a public GitHub repo and get a full engineering review — stack, architecture,
            code quality, security, and git history — in one report.
          </p>
          <form onSubmit={handleSubmit}>
            <label htmlFor="repo-url" className="sr-only">
              GitHub repository URL
            </label>
            <input
              id="repo-url"
              type="text"
              placeholder="https://github.com/owner/repo"
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              required
            />
            <button type="submit" disabled={submitting}>
              {submitting ? "Starting…" : "Analyze"}
            </button>
            {submitError && (
              <p className="error" role="alert">
                {submitError}
              </p>
            )}
          </form>
        </>
      )}

      {view === "running" && (
        <div className="progress" aria-busy="true">
          <p>{elapsedSeconds}s elapsed</p>
          {/* Visually hidden but real text content, so a stage change is an
              actual DOM mutation an aria-live region will announce -- toggling
              a sibling <li>'s className alone wouldn't trigger anything. */}
          <p className="sr-only" aria-live="polite">
            {job?.stage
              ? `${STAGE_LABELS[job.stage]} (step ${currentStageIndex + 1} of ${STAGES.length})`
              : "Starting analysis…"}
          </p>
          <ul>
            {STAGES.map((stage, i) => (
              <li
                key={stage}
                className={i < currentStageIndex ? "done" : i === currentStageIndex ? "current" : ""}
              >
                {STAGE_LABELS[stage]}
              </li>
            ))}
          </ul>
        </div>
      )}

      {view === "done" && job?.markdown && (
        <div className="report">
          <button onClick={reset}>New Analysis</button>
          <MarkdownReport markdown={job.markdown} />
        </div>
      )}

      {view === "error" && (
        <div className="report">
          <p className="error" role="alert">
            {job?.error ?? "Analysis failed"}
          </p>
          <button onClick={reset}>Try Again</button>
        </div>
      )}
    </div>
  );
}

export default App;
