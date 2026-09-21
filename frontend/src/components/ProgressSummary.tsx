import type { Job } from "../types";

export function ProgressSummary({ job }: { job: Job }) {
  const processed = job.completed_files + job.failed_files;
  const pct = job.total_files > 0 ? Math.round((processed / job.total_files) * 100) : 0;
  const inProgress = job.status === "queued" || job.status === "processing";

  return (
    <div className="rounded-xl border border-ink-200 bg-white p-4 shadow-sm">
      <div className="mb-2 flex items-center justify-between text-sm">
        <span className="font-medium text-ink-800">
          {inProgress ? "Extracting leads…" : "Extraction complete"}
        </span>
        <span className="text-ink-500">
          {processed} / {job.total_files} cards processed
          {job.failed_files > 0 && <span className="text-red-600"> · {job.failed_files} failed</span>}
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-ink-100">
        <div
          className="h-full rounded-full bg-brand-600 transition-all duration-300 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
