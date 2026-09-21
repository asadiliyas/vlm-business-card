import { useEffect, useState } from "react";

/**
 * Ticks once a second from `since` until `stopped` becomes true, then
 * freezes. Backs the live "Elapsed: 0:47" readout during extraction —
 * without it the user has no signal for how long a multi-minute CPU-bound
 * batch is actually taking versus just being stuck.
 */
export function useElapsedSeconds(since: string | null, stopped: boolean): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!since || stopped) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [since, stopped]);

  if (!since) return 0;
  return Math.max(0, Math.floor((now - new Date(since).getTime()) / 1000));
}

export function formatDuration(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}
