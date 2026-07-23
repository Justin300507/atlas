import { useEffect, useRef, useState, type FormEvent } from "react";
import "./App.css";
import { createJob, getJob, type JobRecord } from "./api";
import { MarkdownReport } from "./MarkdownReport";

const STAGES = [
  "cloning_structure",
  "parsing",
  "building_graph",
  "analyzing_quality",
  "cloning_history",
  "analyzing_git_history",
  "generating_documentation",
];

const STAGE_LABELS: Record<string, string> = {
  cloning_structure: "Cloning repository",
  parsing: "Parsing source files",
  building_graph: "Building dependency graph",
  analyzing_quality: "Analyzing code quality",
  cloning_history: "Cloning commit history",
  analyzing_git_history: "Analyzing git history",
  generating_documentation: "Generating documentation",
};

type ViewState = "idle" | "running" | "done" | "error";

interface AppProps {
  pollIntervalMs?: number;
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

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (submitting) return; // guards against a double-click firing two jobs
    setSubmitError(null);
    setSubmitting(true);
    try {
      const { job_id } = await createJob(repoUrl);
      setJob(null);
      setElapsedSeconds(0);
      setView("running");

      timerRef.current = window.setInterval(() => {
        setElapsedSeconds((s) => s + 1);
      }, pollIntervalMs);

      pollRef.current = window.setInterval(async () => {
        try {
          const record = await getJob(job_id);
          setJob(record);
          if (record.status === "done" || record.status === "error") {
            stopTimers();
            setView(record.status);
          }
        } catch {
          // A single dropped poll isn't a job failure — retry on the next tick.
        }
      }, pollIntervalMs);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to start analysis");
    } finally {
      setSubmitting(false);
    }
  }

  function reset() {
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
        <form onSubmit={handleSubmit}>
          <input
            type="text"
            placeholder="https://github.com/owner/repo"
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
            required
          />
          <button type="submit" disabled={submitting}>
            {submitting ? "Starting…" : "Analyze"}
          </button>
          {submitError && <p className="error">{submitError}</p>}
        </form>
      )}

      {view === "running" && (
        <div className="progress">
          <p>{elapsedSeconds}s elapsed</p>
          <ul>
            {STAGES.map((stage, i) => (
              <li key={stage} className={i <= currentStageIndex ? "done" : ""}>
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
          <p className="error">{job?.error ?? "Analysis failed"}</p>
          <button onClick={reset}>Try Again</button>
        </div>
      )}
    </div>
  );
}

export default App;
