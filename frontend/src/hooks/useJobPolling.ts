import { useEffect, useRef, useState } from "react";
import { getJob } from "../api";
import type { Job } from "../types";

/**
 * Polls GET /api/jobs/:id on an interval until the job reaches a terminal
 * status, streaming each poll's rows into state so the results table fills
 * in live rather than waiting for the whole batch. Stops cleanly on
 * unmount or job switch — a background job continuing server-side after
 * the user navigates away is fine; a leaked client-side timer is not.
 */
export function useJobPolling(jobId: string | null, intervalMs = 1200) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setJob(null);
    setError(null);
    if (!jobId) return;

    let cancelled = false;

    const poll = async () => {
      try {
        const latest = await getJob(jobId);
        if (cancelled) return;
        setJob(latest);
        if (latest.status === "queued" || latest.status === "processing") {
          timerRef.current = setTimeout(poll, intervalMs);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load job status");
        }
      }
    };

    poll();

    return () => {
      cancelled = true;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [jobId, intervalMs]);

  return { job, error, setJob };
}
