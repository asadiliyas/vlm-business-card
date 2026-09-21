// Thin fetch wrapper over the backend API. Every call uses a relative path
// ('/api/...') so this works unmodified in local dev (via the Vite proxy in
// vite.config.ts) and in production (same-origin — the backend serves this
// built frontend directly).
import type { HealthResponse, Job, JobSummary, Lead, LeadUpdate } from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function handle<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = body.detail ?? detail;
    } catch {
      // response body wasn't JSON — fall back to statusText
    }
    throw new ApiError(resp.status, detail);
  }
  return resp.json() as Promise<T>;
}

export async function uploadJob(files: File[]): Promise<JobSummary> {
  const form = new FormData();
  for (const f of files) form.append("files", f, f.name);
  const resp = await fetch("/api/jobs", { method: "POST", body: form });
  return handle<JobSummary>(resp);
}

export async function getJob(jobId: string): Promise<Job> {
  const resp = await fetch(`/api/jobs/${jobId}`);
  return handle<Job>(resp);
}

export async function deleteJob(jobId: string): Promise<void> {
  const resp = await fetch(`/api/jobs/${jobId}`, { method: "DELETE" });
  if (!resp.ok && resp.status !== 204) await handle(resp);
}

export async function updateLead(leadId: string, update: LeadUpdate): Promise<Lead> {
  const resp = await fetch(`/api/leads/${leadId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update),
  });
  return handle<Lead>(resp);
}

export async function deleteLead(leadId: string): Promise<void> {
  const resp = await fetch(`/api/leads/${leadId}`, { method: "DELETE" });
  if (!resp.ok && resp.status !== 204) await handle(resp);
}

export function exportJobUrl(jobId: string): string {
  return `/api/jobs/${jobId}/export.xlsx`;
}

export async function getHealth(): Promise<HealthResponse> {
  const resp = await fetch("/api/health");
  return handle<HealthResponse>(resp);
}
