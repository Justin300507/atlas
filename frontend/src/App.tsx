import { useEffect, useRef, useState, type FormEvent } from "react";
import { motion, useReducedMotion, type Variants } from "motion/react";
import "./App.css";
import { compareJobs, createJob, getJob, JobNotFoundError, type JobRecord } from "./api";
import { GraphBackground } from "./GraphBackground";
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
  "analyzing_semantics",
  "generating_documentation",
];

const STAGE_LABELS: Record<string, string> = {
  cloning_structure: "Cloning repository",
  parsing: "Parsing source files",
  building_graph: "Building dependency graph",
  analyzing_quality: "Analyzing code quality",
  scanning_security: "Scanning for security issues",
  analyzing_git_history: "Analyzing git history",
  analyzing_semantics: "Analyzing architecture",
  generating_documentation: "Generating documentation",
};

// Hero entrance: the eyebrow/headline/subhead/command-bar stagger in as one
// composed moment on first paint. Collapses to an instant, non-moving state
// under prefers-reduced-motion rather than just a shorter version of the
// same animation.
function heroContainerVariants(reducedMotion: boolean): Variants {
  return {
    hidden: {},
    show: {
      transition: reducedMotion ? { duration: 0 } : { staggerChildren: 0.09, delayChildren: 0.1 },
    },
  };
}

function heroItemVariants(reducedMotion: boolean): Variants {
  return {
    hidden: reducedMotion ? {} : { opacity: 0, y: 16 },
    show: {
      opacity: 1,
      y: 0,
      transition: reducedMotion ? { duration: 0 } : { duration: 0.55, ease: [0.16, 1, 0.3, 1] },
    },
  };
}

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

// A small history of completed jobs per repo URL, so a later run against
// the same repo can offer "Compare with Previous Run" -- backed by the
// existing POST /compare endpoint, which had no frontend surface at all
// before this. Capped so a repo analyzed repeatedly doesn't grow
// localStorage without bound; only the most recent entries matter for
// "compare against the last run."
const JOB_HISTORY_KEY = "atlas.jobHistory";
const MAX_HISTORY_ENTRIES = 50;

interface HistoryEntry {
  jobId: string;
  repoUrl: string;
  completedAt: string;
}

function loadJobHistory(): HistoryEntry[] {
  try {
    const raw = localStorage.getItem(JOB_HISTORY_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (e): e is HistoryEntry =>
        typeof e?.jobId === "string" && typeof e?.repoUrl === "string" && typeof e?.completedAt === "string"
    );
  } catch {
    return [];
  }
}

function recordCompletedJob(jobId: string, repoUrl: string) {
  try {
    const history = loadJobHistory();
    history.push({ jobId, repoUrl, completedAt: new Date().toISOString() });
    localStorage.setItem(JOB_HISTORY_KEY, JSON.stringify(history.slice(-MAX_HISTORY_ENTRIES)));
  } catch {
    // localStorage unavailable (private mode, quota) -- history is best-effort
  }
}

// Most recent *other* completed job for the same repo URL, if any.
function findPreviousJob(repoUrl: string, excludeJobId: string): HistoryEntry | null {
  const matches = loadJobHistory().filter((e) => e.repoUrl === repoUrl && e.jobId !== excludeJobId);
  return matches.length > 0 ? matches[matches.length - 1] : null;
}

function App({ pollIntervalMs = 1000 }: AppProps) {
  const [repoUrl, setRepoUrl] = useState("");
  const [view, setView] = useState<ViewState>("idle");
  const [job, setJob] = useState<JobRecord | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [comparison, setComparison] = useState<string | null>(null);
  const [comparisonError, setComparisonError] = useState<string | null>(null);
  const [comparing, setComparing] = useState(false);
  const pollRef = useRef<number | null>(null);
  const timerRef = useRef<number | null>(null);
  const hasCheckedRecovery = useRef(false);
  const reducedMotion = useReducedMotion();

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

  function startTracking(jobId: string, initialElapsedSeconds: number, repoUrlForHistory: string) {
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
          if (record.status === "done") recordCompletedJob(jobId, repoUrlForHistory);
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
          if (record.status === "done") recordCompletedJob(saved.jobId, saved.repoUrl);
          setView(record.status);
          return;
        }
        const createdAtMs = Date.parse(record.created_at);
        const elapsed = Number.isNaN(createdAtMs)
          ? 0
          : Math.max(0, Math.floor((Date.now() - createdAtMs) / 1000));
        startTracking(saved.jobId, elapsed, saved.repoUrl);
      } catch (err) {
        if (err instanceof JobNotFoundError) {
          // The job is genuinely gone (expired, DB reset, etc.) -- give up gracefully.
          clearActiveJob();
          setView("idle");
        } else {
          // A transient failure (network blip, backend still booting) isn't proof the
          // job is gone -- keep the saved job and let the normal poll loop's own
          // dropped-request tolerance retry on the next tick.
          startTracking(saved.jobId, 0, saved.repoUrl);
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
      setComparison(null);
      setComparisonError(null);
      setView("running");
      startTracking(job_id, 0, repoUrl);
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
    setComparison(null);
    setComparisonError(null);
  }

  async function handleCompare(previousJobId: string, currentJobId: string) {
    setComparing(true);
    setComparisonError(null);
    try {
      const result = await compareJobs(previousJobId, currentJobId);
      setComparison(result.markdown);
    } catch (err) {
      setComparisonError(err instanceof Error ? err.message : "Failed to compare runs");
    } finally {
      setComparing(false);
    }
  }

  const currentStageIndex = job?.stage ? STAGES.indexOf(job.stage) : -1;
  const previousJob = view === "done" && job ? findPreviousJob(repoUrl, job.id) : null;

  return (
    <div className="app">
      <header className="topbar">
        <button
          type="button"
          className="brand-mark"
          onClick={reset}
          aria-label="Atlas — start a new analysis"
        >
          Atlas
        </button>
      </header>

      {view === "idle" && (
        <section className="hero">
          <GraphBackground />
          <motion.div
            className="hero-content"
            initial="hidden"
            animate="show"
            variants={heroContainerVariants(!!reducedMotion)}
          >
            <motion.p className="eyebrow" variants={heroItemVariants(!!reducedMotion)}>
              Deterministic static analysis
            </motion.p>
            <motion.h1 variants={heroItemVariants(!!reducedMotion)}>
              Every codebase has a shape you can't see.
            </motion.h1>
            <motion.p className="subhead" variants={heroItemVariants(!!reducedMotion)}>
              Paste a public GitHub repo and get a full engineering review — stack, architecture,
              code quality, security, and git history — in one report.
            </motion.p>
            <motion.form
              className="command-bar"
              variants={heroItemVariants(!!reducedMotion)}
              onSubmit={handleSubmit}
            >
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
            </motion.form>
            {submitError && (
              <motion.p className="error" role="alert" variants={heroItemVariants(!!reducedMotion)}>
                {submitError}
              </motion.p>
            )}
          </motion.div>
        </section>
      )}

      {view === "running" && (
        <div className="panel progress" aria-busy="true">
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
        <div className="panel report">
          <button onClick={reset}>New Analysis</button>
          {previousJob && (
            <button
              onClick={() => handleCompare(previousJob.jobId, job.id)}
              disabled={comparing}
              className="compare-button"
            >
              {comparing ? "Comparing…" : "Compare with Previous Run"}
            </button>
          )}
          {comparisonError && (
            <p className="error" role="alert">
              {comparisonError}
            </p>
          )}
          {comparison && (
            <div className="comparison">
              <div className="comparison-header">
                <h2>Comparison with Previous Run</h2>
                <button onClick={() => setComparison(null)}>Hide Comparison</button>
              </div>
              <MarkdownReport markdown={comparison} />
            </div>
          )}
          <MarkdownReport markdown={job.markdown} />
        </div>
      )}

      {view === "error" && (
        <div className="panel report">
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
