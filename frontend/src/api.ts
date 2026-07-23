const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

export type JobStatus = "queued" | "running" | "done" | "error";

export interface JobRecord {
  id: string;
  status: JobStatus;
  stage: string | null;
  markdown: string | null;
  error: string | null;
  created_at: string;
}

export async function createJob(repoUrl: string): Promise<{ job_id: string }> {
  const resp = await fetch(`${API_BASE}/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo_url: repoUrl }),
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({ detail: null }));
    throw new Error(body.detail || `Request failed with status ${resp.status}`);
  }
  return resp.json();
}

export class JobNotFoundError extends Error {}

export async function getJob(jobId: string): Promise<JobRecord> {
  const resp = await fetch(`${API_BASE}/jobs/${jobId}`);
  if (resp.status === 404) {
    throw new JobNotFoundError(`No job found with id ${jobId}`);
  }
  if (!resp.ok) {
    throw new Error(`Request failed with status ${resp.status}`);
  }
  return resp.json();
}
