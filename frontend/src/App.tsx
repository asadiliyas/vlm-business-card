import { useCallback, useEffect, useState } from "react";
import { deleteJob, deleteLead, exportJobUrl, getHealth, updateLead, uploadJob } from "./api";
import { Dropzone } from "./components/Dropzone";
import { LeadsTable } from "./components/LeadsTable";
import { ProgressSummary } from "./components/ProgressSummary";
import { useJobPolling } from "./hooks/useJobPolling";
import type { EditableLeadField, HealthResponse } from "./types";

const MAX_FILES_PER_JOB = 40; // mirrors backend/app/config.py default — server enforces the real limit

export default function App() {
  const [jobId, setJobId] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const { job, error: pollError, setJob } = useJobPolling(jobId);

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  const handleSubmit = useCallback(async (files: File[]) => {
    if (files.length === 0) return;
    setUploadError(null);
    setUploading(true);
    try {
      const summary = await uploadJob(files);
      setJobId(summary.id);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }, []);

  const handleEditField = useCallback(
    async (leadId: string, field: EditableLeadField, value: string) => {
      const updated = await updateLead(leadId, { [field]: value || null });
      setJob((prev) => (prev ? { ...prev, leads: prev.leads.map((l) => (l.id === leadId ? updated : l)) } : prev));
    },
    [setJob],
  );

  const handleDeleteLead = useCallback(
    async (leadId: string) => {
      await deleteLead(leadId);
      setJob((prev) => (prev ? { ...prev, leads: prev.leads.filter((l) => l.id !== leadId) } : prev));
    },
    [setJob],
  );

  const handleClearBatch = useCallback(async () => {
    if (jobId) await deleteJob(jobId);
    setJobId(null);
    setJob(null);
  }, [jobId, setJob]);

  const doneLeadCount = job?.leads.filter((l) => l.status === "done").length ?? 0;

  return (
    <div className="min-h-screen bg-ink-50">
      <header className="border-b border-ink-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div>
            <h1 className="text-lg font-semibold text-ink-900">Business Card Lead Extractor</h1>
            <p className="text-sm text-ink-500">Bulk-upload business cards and export a structured lead list.</p>
          </div>
          {health && (
            <div className="flex items-center gap-2 text-xs text-ink-500">
              <span
                className={`h-2 w-2 rounded-full ${health.active_vlm_backend ? "bg-green-500" : "bg-red-500"}`}
                title={health.active_vlm_backend ?? "no backend reachable"}
              />
              VLM backend:{" "}
              <span className="font-medium text-ink-700">{health.active_vlm_backend ?? "unavailable"}</span>
            </div>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-6xl space-y-6 px-6 py-8">
        <section className="rounded-xl border border-ink-200 bg-white p-6 shadow-sm">
          <Dropzone onSubmit={handleSubmit} maxFiles={MAX_FILES_PER_JOB} disabled={uploading} />
          {uploadError && <p className="mt-3 text-sm text-red-600">{uploadError}</p>}
        </section>

        {pollError && (
          <p className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{pollError}</p>
        )}

        {job && (
          <>
            <ProgressSummary job={job} />

            <section className="space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-ink-800">Extracted Leads</h2>
                <div className="flex gap-3">
                  <button
                    type="button"
                    onClick={handleClearBatch}
                    className="rounded-lg border border-ink-300 px-4 py-2 text-sm font-medium text-ink-600 hover:bg-ink-100"
                  >
                    Clear batch
                  </button>
                  <a
                    href={doneLeadCount > 0 ? exportJobUrl(job.id) : undefined}
                    aria-disabled={doneLeadCount === 0}
                    className={`rounded-lg px-4 py-2 text-sm font-semibold text-white shadow-sm ${
                      doneLeadCount > 0 ? "bg-green-600 hover:bg-green-700" : "cursor-not-allowed bg-ink-300"
                    }`}
                  >
                    Download Excel ({doneLeadCount})
                  </a>
                </div>
              </div>

              <LeadsTable leads={job.leads} onEditField={handleEditField} onDeleteLead={handleDeleteLead} />
            </section>
          </>
        )}
      </main>

      <footer className="mx-auto max-w-6xl px-6 py-8 text-xs text-ink-400">
        Uploaded card images and extracted data are automatically deleted a short time after
        processing. Click any cell in the table to correct it before exporting.
      </footer>
    </div>
  );
}
