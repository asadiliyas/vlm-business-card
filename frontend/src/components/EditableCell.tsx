import { useState } from "react";
import clsx from "clsx";

interface Props {
  value: string | null;
  placeholder?: string;
  onCommit: (value: string) => void;
}

/**
 * Click-to-edit table cell. The VLM will not be 100% on every card, so every
 * extracted field must be correctable in place before export — this is that
 * seam. Commits on blur or Enter, discards on Escape.
 */
export function EditableCell({ value, placeholder = "—", onCommit }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value ?? "");

  if (editing) {
    return (
      <input
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          setEditing(false);
          if (draft !== (value ?? "")) onCommit(draft);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
          if (e.key === "Escape") {
            setDraft(value ?? "");
            setEditing(false);
          }
        }}
        className="w-full min-w-[8rem] rounded border border-brand-400 bg-white px-1.5 py-1 text-sm outline-none ring-2 ring-brand-100"
      />
    );
  }

  return (
    <button
      type="button"
      onClick={() => {
        setDraft(value ?? "");
        setEditing(true);
      }}
      className={clsx(
        "w-full rounded px-1.5 py-1 text-left text-sm hover:bg-ink-100",
        !value && "italic text-ink-400",
      )}
      title="Click to edit"
    >
      {value || placeholder}
    </button>
  );
}
