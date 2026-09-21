import type { EditableLeadField, Lead } from "../types";
import { ConfidenceBadge, StatusChip, WarningBadges } from "./Badges";
import { EditableCell } from "./EditableCell";

interface Props {
  lead: Lead;
  onEditField: (leadId: string, field: EditableLeadField, value: string) => void;
  onDeleteLead: (leadId: string) => void;
}

const FIELD_ROWS: { field: EditableLeadField; label: string }[] = [
  { field: "first_name", label: "First name" },
  { field: "last_name", label: "Last name" },
  { field: "job_title", label: "Position" },
  { field: "company", label: "Company" },
  { field: "location", label: "Location" },
  { field: "phone", label: "Phone" },
  { field: "email", label: "Email" },
];

/**
 * The table view works well once there's screen width to spare, but a
 * horizontally-scrolling 11-column table on a phone is a genuinely bad
 * experience — this is the same data as a stack of labeled rows instead,
 * shown only below the md breakpoint (see LeadsTable's responsive split).
 */
export function LeadCard({ lead, onEditField, onDeleteLead }: Props) {
  return (
    <div className="rounded-lg border border-ink-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center gap-3">
        {lead.thumbnail_url ? (
          <img
            src={lead.thumbnail_url}
            alt={lead.source_file}
            className="h-12 w-16 shrink-0 rounded object-cover ring-1 ring-ink-200"
          />
        ) : (
          <div className="flex h-12 w-16 shrink-0 items-center justify-center rounded bg-ink-100 text-[10px] text-ink-400">
            no preview
          </div>
        )}
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs text-ink-500">{lead.source_file}</p>
          <div className="mt-1 flex items-center gap-2">
            <StatusChip status={lead.status} />
            <ConfidenceBadge confidence={lead.confidence} />
          </div>
        </div>
        <button
          type="button"
          onClick={() => onDeleteLead(lead.id)}
          className="shrink-0 rounded p-1.5 text-ink-400 hover:bg-ink-100 hover:text-red-600"
          aria-label={`Remove ${lead.source_file}`}
        >
          <svg className="h-4 w-4" viewBox="0 0 20 20" fill="none">
            <path d="M6 6l8 8M14 6l-8 8" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" />
          </svg>
        </button>
      </div>

      {lead.error && <p className="mb-2 text-xs text-red-600">{lead.error}</p>}

      <dl className="grid grid-cols-[5.5rem_1fr] gap-y-1.5 text-sm">
        {FIELD_ROWS.map(({ field, label }) => (
          <div key={field} className="contents">
            <dt className="self-center py-1 text-xs font-medium text-ink-500">{label}</dt>
            <dd>
              <EditableCell value={lead[field]} onCommit={(v) => onEditField(lead.id, field, v)} />
            </dd>
          </div>
        ))}
      </dl>

      {lead.warnings.length > 0 && (
        <div className="mt-2 border-t border-ink-100 pt-2">
          <WarningBadges warnings={lead.warnings} />
        </div>
      )}
    </div>
  );
}
