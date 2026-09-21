import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { useMemo } from "react";
import type { EditableLeadField, Lead } from "../types";
import { ConfidenceBadge, StatusChip, WarningBadges } from "./Badges";
import { EditableCell } from "./EditableCell";
import { LeadCard } from "./LeadCard";

interface Props {
  leads: Lead[];
  onEditField: (leadId: string, field: EditableLeadField, value: string) => void;
  onDeleteLead: (leadId: string) => void;
}

const columnHelper = createColumnHelper<Lead>();

export function LeadsTable({ leads, onEditField, onDeleteLead }: Props) {
  const columns = useMemo(
    () => [
      columnHelper.display({
        id: "thumbnail",
        header: "",
        cell: ({ row }) =>
          row.original.thumbnail_url ? (
            <img
              src={row.original.thumbnail_url}
              alt={row.original.source_file}
              className="h-12 w-16 rounded object-cover ring-1 ring-ink-200"
            />
          ) : (
            <div className="flex h-12 w-16 items-center justify-center rounded bg-ink-100 text-[10px] text-ink-400">
              no preview
            </div>
          ),
      }),
      columnHelper.accessor("status", {
        header: "Status",
        cell: (ctx) => (
          <div className="space-y-1">
            <StatusChip status={ctx.getValue()} />
            {ctx.row.original.error && (
              <p className="max-w-[10rem] text-[11px] text-red-600">{ctx.row.original.error}</p>
            )}
          </div>
        ),
      }),
      columnHelper.accessor("first_name", {
        header: "First Name",
        cell: (ctx) => (
          <EditableCell value={ctx.getValue()} onCommit={(v) => onEditField(ctx.row.original.id, "first_name", v)} />
        ),
      }),
      columnHelper.accessor("last_name", {
        header: "Last Name",
        cell: (ctx) => (
          <EditableCell value={ctx.getValue()} onCommit={(v) => onEditField(ctx.row.original.id, "last_name", v)} />
        ),
      }),
      columnHelper.accessor("job_title", {
        header: "Position / Job Title",
        cell: (ctx) => (
          <EditableCell value={ctx.getValue()} onCommit={(v) => onEditField(ctx.row.original.id, "job_title", v)} />
        ),
      }),
      columnHelper.accessor("company", {
        header: "Company",
        cell: (ctx) => (
          <EditableCell value={ctx.getValue()} onCommit={(v) => onEditField(ctx.row.original.id, "company", v)} />
        ),
      }),
      columnHelper.accessor("location", {
        header: "Location",
        cell: (ctx) => (
          <EditableCell value={ctx.getValue()} onCommit={(v) => onEditField(ctx.row.original.id, "location", v)} />
        ),
      }),
      columnHelper.accessor("phone", {
        header: "Phone Number",
        cell: (ctx) => (
          <EditableCell value={ctx.getValue()} onCommit={(v) => onEditField(ctx.row.original.id, "phone", v)} />
        ),
      }),
      columnHelper.accessor("email", {
        header: "Email Address",
        cell: (ctx) => (
          <EditableCell value={ctx.getValue()} onCommit={(v) => onEditField(ctx.row.original.id, "email", v)} />
        ),
      }),
      columnHelper.accessor("confidence", {
        header: "Confidence",
        cell: (ctx) => <ConfidenceBadge confidence={ctx.getValue()} />,
      }),
      columnHelper.accessor("warnings", {
        header: "Warnings",
        cell: (ctx) => <WarningBadges warnings={ctx.getValue()} />,
      }),
      columnHelper.display({
        id: "actions",
        header: "",
        cell: ({ row }) => (
          <button
            type="button"
            onClick={() => onDeleteLead(row.original.id)}
            className="text-xs font-medium text-ink-400 hover:text-red-600"
            title="Remove this lead from the batch"
          >
            Remove
          </button>
        ),
      }),
    ],
    [onEditField, onDeleteLead],
  );

  const table = useReactTable({ data: leads, columns, getCoreRowModel: getCoreRowModel() });

  if (leads.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-ink-300 bg-white py-16 text-center text-sm text-ink-500">
        No leads yet — upload a batch of business cards above to get started.
      </div>
    );
  }

  return (
    <>
      {/* Below md: a stack of cards. An 11-column table has no good answer
          on a phone screen other than "scroll sideways forever", so this
          reshapes the same data instead of just shrinking the table. */}
      <div className="space-y-3 md:hidden">
        {leads.map((lead) => (
          <LeadCard key={lead.id} lead={lead} onEditField={onEditField} onDeleteLead={onDeleteLead} />
        ))}
      </div>

      <div className="thin-scrollbar hidden overflow-x-auto rounded-lg border border-ink-200 bg-white shadow-sm md:block">
        <table className="w-full min-w-[1100px] border-collapse text-sm">
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id} className="border-b border-ink-200 bg-ink-50">
                {hg.headers.map((header) => (
                  <th key={header.id} className="whitespace-nowrap px-3 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-ink-500">
                    {flexRender(header.column.columnDef.header, header.getContext())}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className="border-b border-ink-100 last:border-0 hover:bg-ink-50/60">
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-3 py-2 align-top">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
