import { formatDuration, useElapsedSeconds } from "../hooks/useElapsedSeconds";
import type { Job } from "../types";

export function ProgressSummary({ job }: { job: Job }) {
  const processed = job.completed_files + job.failed_files;
  const pct = job.total_files > 0 ? Math.round((processed / job.total_files) * 100) : 0;
  const inProgress = job.status === "queued" || job.status === "processing";

  const elapsed = useElapsedSeconds(job.created_at, !inProgress);

  let etaLabel: string;
  if (!inProgress) {
    etaLabel = `Completed in ${formatDuration(elapsed)}`;
  } else if (processed === 0) {
    etaLabel = "Each card can take anywhere from a few seconds to a couple of minutes — hang tight";
  } else {
    const avgPerCard = elapsed / processed;
    const remainingCards = Math.max(0, job.total_files - processed);
    const etaSeconds = Math.round(avgPerCard * remainingCards);
    etaLabel = remainingCards > 0 ? `About ${formatDuration(etaSeconds)} remaining` : "Finishing up…";
  }

  return (
    <div className="rounded-lg border border-ink-200 bg-white p-5 shadow-sm">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div className="flex items-baseline gap-3">
          <span className="text-sm font-semibold text-ink-900">
            {inProgress ? "Extracting leads…" : "Extraction complete"}
          </span>
          <span className="font-mono text-sm text-ink-500" aria-label="Elapsed time">
            {formatDuration(elapsed)}
          </span>
        </div>
        <span className="text-sm text-ink-500">
          {processed} / {job.total_files} cards
          {job.failed_files > 0 && <span className="text-red-600"> · {job.failed_files} failed</span>}
        </span>
      </div>

      <div className="h-2 w-full overflow-hidden rounded-full bg-ink-100">
        <div
          className={`h-full rounded-full bg-brand-600 transition-all duration-500 ease-out ${inProgress ? "progress-stripe" : ""}`}
          style={{ width: `${Math.max(pct, processed > 0 || !inProgress ? pct : 4)}%` }}
        />
      </div>

      <p className="mt-2 text-xs text-ink-500">{etaLabel}</p>
    </div>
  );
}
