import clsx from "clsx";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useDropzone } from "react-dropzone";

const SAMPLE_FILES = [
  "card_01_clean.jpg",
  "card_02_clean.jpg",
  "card_03_clean.jpg",
  "card_04_company_only.jpg",
];

interface Props {
  onSubmit: (files: File[]) => void;
  maxFiles: number;
  disabled: boolean;
}

export function Dropzone({ onSubmit, maxFiles, disabled }: Props) {
  const [selected, setSelected] = useState<File[]>([]);
  const [loadingSamples, setLoadingSamples] = useState(false);
  const [limitWarning, setLimitWarning] = useState<string | null>(null);

  // Object URLs must be revoked or they leak for the life of the tab —
  // created once per file list change, not once per render.
  const previewUrls = useMemo(() => selected.map((f) => URL.createObjectURL(f)), [selected]);
  useEffect(() => () => previewUrls.forEach((u) => URL.revokeObjectURL(u)), [previewUrls]);

  const onDrop = useCallback(
    (accepted: File[]) => {
      setSelected((prev) => {
        const merged = [...prev, ...accepted];
        if (merged.length > maxFiles) {
          setLimitWarning(`Only the first ${maxFiles} files were kept (batch limit is ${maxFiles}).`);
          return merged.slice(0, maxFiles);
        }
        setLimitWarning(null);
        return merged;
      });
    },
    [maxFiles],
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "image/jpeg": [], "image/png": [], "image/webp": [] },
    disabled,
  });

  const removeFile = (index: number) => {
    setSelected((prev) => prev.filter((_, i) => i !== index));
  };

  const loadSampleBatch = async () => {
    setLoadingSamples(true);
    try {
      const files = await Promise.all(
        SAMPLE_FILES.map(async (name) => {
          const resp = await fetch(`/samples/${name}`);
          const blob = await resp.blob();
          return new File([blob], name, { type: "image/jpeg" });
        }),
      );
      setSelected(files);
      setLimitWarning(null);
    } finally {
      setLoadingSamples(false);
    }
  };

  return (
    <div className="space-y-4">
      <div
        {...getRootProps()}
        className={clsx(
          "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors sm:py-14",
          isDragActive ? "border-brand-500 bg-brand-50" : "border-ink-300 bg-white hover:border-ink-400",
          disabled && "pointer-events-none opacity-60",
        )}
      >
        <input {...getInputProps()} />
        <svg className="h-9 w-9 text-ink-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
            d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M9 19l3-3m0 0l3 3m-3-3v9" />
        </svg>
        <p className="text-sm font-medium text-ink-900">
          {isDragActive ? "Drop to add these cards" : "Drag business card photos here, or click to choose files"}
        </p>
        <p className="text-xs text-ink-500">
          JPEG, PNG, or WebP · up to {maxFiles} at once
        </p>
      </div>

      {limitWarning && (
        <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700 ring-1 ring-inset ring-amber-200">
          {limitWarning}
        </p>
      )}

      {selected.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-medium text-ink-500">
            {selected.length} card{selected.length === 1 ? "" : "s"} selected
          </p>
          <div className="thin-scrollbar flex gap-3 overflow-x-auto pb-2">
            {selected.map((file, i) => (
              <div key={`${file.name}-${i}`} className="relative shrink-0">
                <img
                  src={previewUrls[i]}
                  alt={file.name}
                  className="h-20 w-28 rounded-md border border-ink-300 object-cover"
                />
                <button
                  type="button"
                  onClick={() => removeFile(i)}
                  className="absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-ink-800 text-xs leading-none text-white shadow hover:bg-ink-900"
                  aria-label={`Remove ${file.name}`}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
        <button
          type="button"
          onClick={() => onSubmit(selected)}
          disabled={disabled || selected.length === 0}
          className="rounded-md bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-brand-700 disabled:cursor-not-allowed disabled:bg-ink-300"
        >
          {selected.length > 0
            ? `Extract ${selected.length} card${selected.length === 1 ? "" : "s"}`
            : "Select cards to begin"}
        </button>

        {selected.length > 0 && (
          <button
            type="button"
            onClick={() => setSelected([])}
            disabled={disabled}
            className="text-sm font-medium text-ink-500 hover:text-ink-800"
          >
            Clear
          </button>
        )}

        <span className="text-sm text-ink-400">or</span>

        <button
          type="button"
          onClick={loadSampleBatch}
          disabled={disabled || loadingSamples}
          className="text-sm font-medium text-brand-700 hover:text-brand-800 disabled:opacity-50"
        >
          {loadingSamples ? "Loading sample cards…" : "try a sample batch →"}
        </button>
      </div>
    </div>
  );
}
