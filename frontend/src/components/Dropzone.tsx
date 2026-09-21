import clsx from "clsx";
import { useCallback, useState } from "react";
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
          "flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors",
          isDragActive ? "border-brand-500 bg-brand-50" : "border-ink-300 bg-white",
          disabled && "cursor-not-allowed opacity-60",
        )}
      >
        <input {...getInputProps()} />
        <svg className="h-10 w-10 text-ink-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
            d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M9 19l3-3m0 0l3 3m-3-3v9" />
        </svg>
        <p className="text-sm font-medium text-ink-800">
          {isDragActive ? "Drop the card images here" : "Drag & drop business card images, or click to browse"}
        </p>
        <p className="text-xs text-ink-500">
          JPEG, PNG, or WebP · up to {maxFiles} files per batch
        </p>
      </div>

      {limitWarning && <p className="text-xs text-amber-600">{limitWarning}</p>}

      {selected.length > 0 && (
        <div className="thin-scrollbar flex gap-3 overflow-x-auto pb-2">
          {selected.map((file, i) => (
            <div key={`${file.name}-${i}`} className="relative shrink-0">
              <img
                src={URL.createObjectURL(file)}
                alt={file.name}
                className="h-20 w-28 rounded-lg border border-ink-300 object-cover"
              />
              <button
                type="button"
                onClick={() => removeFile(i)}
                className="absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-ink-800 text-xs text-white shadow hover:bg-ink-900"
                aria-label={`Remove ${file.name}`}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => onSubmit(selected)}
          disabled={disabled || selected.length === 0}
          className="rounded-lg bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Extract {selected.length > 0 ? `${selected.length} card${selected.length === 1 ? "" : "s"}` : "leads"}
        </button>

        {selected.length > 0 && (
          <button
            type="button"
            onClick={() => setSelected([])}
            disabled={disabled}
            className="text-sm font-medium text-ink-500 hover:text-ink-800"
          >
            Clear selection
          </button>
        )}

        <button
          type="button"
          onClick={loadSampleBatch}
          disabled={disabled || loadingSamples}
          className="ml-auto text-sm font-medium text-brand-600 hover:text-brand-700 disabled:opacity-50"
        >
          {loadingSamples ? "Loading sample cards…" : "Try a sample batch →"}
        </button>
      </div>
    </div>
  );
}
