import { useCallback, useEffect, useState } from "react";
import { deleteJob, deleteLead, exportJobUrl, getHealth, updateLead, uploadJob } from "./api";
import { Dropzone } from "./components/Dropzone";
import { LeadsTable } from "./components/LeadsTable";
import { ProgressSummary } from "./components/ProgressSummary";
import { Stepper } from "./components/Stepper";
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
  const jobInProgress = job?.status === "queued" || job?.status === "processing";
  const currentStep: 1 | 2 | 3 = !job ? 1 : jobInProgress ? 2 : 3;

  return (
    <div className="min-h-screen bg-ink-50">
      <header className="border-b border-ink-200 bg-white">
        <div className="mx-auto flex max-w-5xl flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-ink-900">
              <svg className="h-5 w-5 text-white" viewBox="0 0 24 24" fill="none">
                <rect x="2.5" y="5" width="19" height="14" rx="2" stroke="currentColor" strokeWidth="1.6" />
                <circle cx="8.5" cy="12" r="2.2" stroke="currentColor" strokeWidth="1.6" />
                <path d="M13.5 10h5M13.5 14h3.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              </svg>
            </div>
            <div>
              <h1 className="text-base font-semibold leading-tight text-ink-900">Business Card Lead Extractor</h1>
              <p className="text-xs text-ink-500">Bulk-upload business cards, export a structured lead list.</p>
            </div>
          </div>
          {health && (
            <div className="inline-flex w-fit items-center gap-1.5 rounded-full bg-ink-100 px-2.5 py-1 text-xs text-ink-600">
              <span
                className={`h-1.5 w-1.5 rounded-full ${health.active_vlm_backend ? "bg-green-500" : "bg-red-500"}`}
              />
              <span>Extraction engine:</span>
              <span className="font-medium text-ink-800">{health.active_vlm_backend ?? "unavailable"}</span>
            </div>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-6 px-4 py-6 sm:px-6 sm:py-8">
        <Stepper current={currentStep} />

        <section className="rounded-lg border border-ink-200 bg-white p-4 shadow-sm sm:p-6">
          <h2 className="mb-4 text-sm font-semibold text-ink-900">
            <span className="mr-1.5 text-ink-400">1.</span>Upload business cards
          </h2>
          <Dropzone onSubmit={handleSubmit} maxFiles={MAX_FILES_PER_JOB} disabled={uploading} />
          {uploadError && (
            <p className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 ring-1 ring-inset ring-red-200">
              {uploadError}
            </p>
          )}
        </section>

        {pollError && (
          <p className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-inset ring-red-200">
            {pollError}
          </p>
        )}

        {job && (
          <>
            <section aria-label="Extraction progress">
              <h2 className="mb-2 text-sm font-semibold text-ink-900">
                <span className="mr-1.5 text-ink-400">2.</span>Extracting
              </h2>
              <ProgressSummary job={job} />
            </section>

            <section className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-sm font-semibold text-ink-900">
                  <span className="mr-1.5 text-ink-400">3.</span>Review &amp; export
                </h2>
                <div className="flex flex-wrap gap-2 sm:gap-3">
                  <button
                    type="button"
                    onClick={handleClearBatch}
                    className="rounded-md border border-ink-300 bg-white px-3.5 py-2 text-sm font-medium text-ink-600 hover:bg-ink-100 sm:px-4"
                  >
                    Clear batch
                  </button>
                  <a
                    href={doneLeadCount > 0 ? exportJobUrl(job.id) : undefined}
                    aria-disabled={doneLeadCount === 0}
                    className={`inline-flex items-center gap-1.5 rounded-md px-3.5 py-2 text-sm font-semibold text-white shadow-sm sm:px-4 ${
                      doneLeadCount > 0 ? "bg-brand-600 hover:bg-brand-700" : "pointer-events-none bg-ink-300"
                    }`}
                  >
                    <svg className="h-4 w-4" viewBox="0 0 20 20" fill="none">
                      <path d="M10 3v10m0 0l-3.5-3.5M10 13l3.5-3.5M4 16.5h12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    Download Excel ({doneLeadCount})
                  </a>
                </div>
              </div>

              <LeadsTable leads={job.leads} onEditField={handleEditField} onDeleteLead={handleDeleteLead} />
            </section>
          </>
        )}
      </main>

      <footer className="mx-auto max-w-5xl px-4 py-8 text-xs text-ink-400 sm:px-6">
        Uploaded card images and extracted data are automatically deleted a short time after
        processing. Click any field to correct it before exporting.
      </footer>
    </div>
  );
}
