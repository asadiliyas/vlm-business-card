import clsx from "clsx";

const WARNING_LABELS: Record<string, string> = {
  no_name_found: "No name",
  no_email_found: "No email",
  no_phone_found: "No phone",
  phone_not_normalized: "Unusual phone format",
  email_failed_validation: "Email looks invalid",
  handwriting: "Handwritten text",
  partially_occluded: "Partially occluded",
  multiple_people_on_card: "Multiple people on card",
  no_email_visible: "No email visible",
};

export function ConfidenceBadge({ confidence }: { confidence: number }) {
  const pct = Math.round(confidence * 100);
  const tone =
    confidence >= 0.8 ? "bg-green-100 text-green-800" : confidence >= 0.5 ? "bg-amber-100 text-amber-800" : "bg-red-100 text-red-800";
  return (
    <span className={clsx("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", tone)}>
      {pct}%
    </span>
  );
}

export function WarningBadges({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {warnings.map((w) => (
        <span
          key={w}
          title={w}
          className="inline-flex items-center rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700 ring-1 ring-inset ring-amber-200"
        >
          {WARNING_LABELS[w] ?? w.replace(/_/g, " ")}
        </span>
      ))}
    </div>
  );
}

export function StatusChip({ status }: { status: string }) {
  const styles: Record<string, string> = {
    queued: "bg-ink-100 text-ink-600",
    processing: "bg-brand-100 text-brand-700 animate-pulse",
    done: "bg-green-100 text-green-800",
    failed: "bg-red-100 text-red-800",
  };
  return (
    <span className={clsx("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium capitalize", styles[status] ?? "bg-ink-100 text-ink-600")}>
      {status}
    </span>
  );
}
