import clsx from "clsx";

const STEPS = [
  { n: 1, label: "Upload" },
  { n: 2, label: "Extract" },
  { n: 3, label: "Review & export" },
] as const;

interface Props {
  current: 1 | 2 | 3;
}

/**
 * A plain, always-visible "you are here" indicator. The single biggest
 * usability gap in the original layout wasn't any one control being
 * unclear — it was that nothing told the user what the overall process
 * was or where they stood in it. This fixes that in one glance.
 */
export function Stepper({ current }: Props) {
  return (
    <ol className="flex items-center gap-2 sm:gap-3" aria-label="Progress">
      {STEPS.map((step, i) => {
        const state = step.n < current ? "done" : step.n === current ? "active" : "upcoming";
        return (
          <li key={step.n} className="flex items-center gap-2 sm:gap-3">
            <div className="flex items-center gap-2">
              <span
                className={clsx(
                  "flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold transition-colors",
                  state === "done" && "bg-brand-600 text-white",
                  state === "active" && "bg-brand-600 text-white ring-4 ring-brand-100",
                  state === "upcoming" && "bg-ink-200 text-ink-500",
                )}
              >
                {state === "done" ? (
                  <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="none">
                    <path d="M3 8.5L6.5 12L13 4.5" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                ) : (
                  step.n
                )}
              </span>
              <span
                className={clsx(
                  "hidden text-sm font-medium sm:inline",
                  state === "active" ? "text-ink-900" : "text-ink-500",
                )}
              >
                {step.label}
              </span>
            </div>
            {i < STEPS.length - 1 && (
              <span
                className={clsx(
                  "h-px w-4 shrink-0 sm:w-8",
                  step.n < current ? "bg-brand-600" : "bg-ink-200",
                )}
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}
