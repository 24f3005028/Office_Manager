"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api/client";
import { DOCUMENT_CATEGORIES, type DocumentCategory, type WorkspaceSettings } from "@/lib/api/types";

type DocumentRoots = Record<DocumentCategory, string[]>;

const emptyRoots: DocumentRoots = {
  bills: [],
  credit_notes: [],
  debit_notes: [],
};

function messageFor(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

interface FolderSettingsFormProps {
  settings: WorkspaceSettings | null;
  onSaved: (settings: WorkspaceSettings) => void;
  compact?: boolean;
}

export function FolderSettingsForm({ settings, onSaved, compact = false }: FolderSettingsFormProps) {
  const [roots, setRoots] = useState<DocumentRoots>(emptyRoots);
  const [manualPath, setManualPath] = useState<Record<DocumentCategory, string>>( {
    bills: "",
    credit_notes: "",
    debit_notes: "",
  });
  const [busyCategory, setBusyCategory] = useState<DocumentCategory | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!settings) return;
    setRoots({
      bills: [...settings.document_roots.bills],
      credit_notes: [...settings.document_roots.credit_notes],
      debit_notes: [...settings.document_roots.debit_notes],
    });
  }, [settings]);

  function addPath(category: DocumentCategory, path: string) {
    const trimmed = path.trim();
    if (!trimmed) return;
    setRoots((current) => ({
      ...current,
      [category]: current[category].includes(trimmed) ? current[category] : [...current[category], trimmed],
    }));
    setManualPath((current) => ({ ...current, [category]: "" }));
    setSaved(false);
  }

  function removePath(category: DocumentCategory, path: string) {
    setRoots((current) => ({
      ...current,
      [category]: current[category].filter((value) => value !== path),
    }));
    setSaved(false);
  }

  async function browse(category: DocumentCategory) {
    setBusyCategory(category);
    setError(null);
    try {
      addPath(category, await api.pickFolder());
    } catch (reason) {
      setError(messageFor(reason, "The native folder picker could not be opened. You can enter a path manually."));
    } finally {
      setBusyCategory(null);
    }
  }

  async function save() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const next = await api.updateDocumentRoots(roots);
      onSaved(next);
      setSaved(true);
    } catch (reason) {
      setError(messageFor(reason, "Folders could not be saved. Check that every path is an existing folder."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={compact ? "folder-settings compact" : "folder-settings"}>
      <div className="folder-settings-intro">
        <div>
          <p className="eyebrow">Document sources</p>
          <h2>{compact ? "Document folders" : "Choose your document folders"}</h2>
        </div>
        <span className="folder-count">{Object.values(roots).flat().length} folders</span>
      </div>
      {!compact && <p className="muted-text">Add one or more local folders for each document type. Subfolders are scanned automatically.</p>}

      <div className="folder-category-grid">
        {DOCUMENT_CATEGORIES.map((category) => (
          <section className="folder-category" key={category.value}>
            <div className="folder-category-heading">
              <div>
                <h3>{category.label}</h3>
                <p>{roots[category.value].length ? `${roots[category.value].length} folder${roots[category.value].length === 1 ? "" : "s"} selected` : "No folders selected"}</p>
              </div>
              <span className={roots[category.value].length ? "category-check complete" : "category-check"}>
                {roots[category.value].length ? "✓" : "–"}
              </span>
            </div>
            <ul className="folder-list">
              {roots[category.value].map((path) => (
                <li key={path}>
                  <span title={path}>{path}</span>
                  <button className="remove-folder" type="button" onClick={() => removePath(category.value, path)} aria-label={`Remove ${path}`}>
                    ×
                  </button>
                </li>
              ))}
              {!roots[category.value].length && <li className="folder-empty">Add the first folder for this type.</li>}
            </ul>
            <div className="folder-add-row">
              <input
                aria-label={`${category.label} folder path`}
                value={manualPath[category.value]}
                placeholder="Paste a folder path"
                onChange={(event) => setManualPath((current) => ({ ...current, [category.value]: event.target.value }))}
                onKeyDown={(event) => {
                  if (event.key === "Enter") addPath(category.value, manualPath[category.value]);
                }}
              />
              <button className="button button-secondary folder-add-button" type="button" onClick={() => addPath(category.value, manualPath[category.value])}>
                Add
              </button>
            </div>
            <button className="button button-quiet folder-browse-button" type="button" onClick={() => void browse(category.value)} disabled={busyCategory !== null}>
              {busyCategory === category.value ? <><span className="spinner dark" /> Opening…</> : <>Browse local folders <span aria-hidden="true">↗</span></>}
            </button>
          </section>
        ))}
      </div>

      {error && <p className="inline-error">{error}</p>}
      <div className="folder-settings-footer">
        <p className="muted-text">{saved ? "Folder settings saved. New previews use them immediately." : "Paths are validated before they are saved."}</p>
        <button className="button button-primary" type="button" onClick={() => void save()} disabled={saving}>
          {saving ? <><span className="spinner" /> Saving…</> : <>Save folders <span aria-hidden="true">↗</span></>}
        </button>
      </div>
    </div>
  );
}
