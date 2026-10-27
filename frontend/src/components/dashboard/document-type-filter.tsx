import { DOCUMENT_TYPES, type DocumentType } from "@/lib/api/types";

interface DocumentTypeFilterProps {
  value: DocumentType[];
  onChange: (value: DocumentType[]) => void;
}

export function DocumentTypeFilter({ value, onChange }: DocumentTypeFilterProps) {
  function toggle(type: DocumentType) {
    onChange(value.includes(type) ? value.filter((current) => current !== type) : [...value, type]);
  }

  return (
    <fieldset className="filter-group">
      <legend>Document types</legend>
      <div className="checkbox-list">
        {DOCUMENT_TYPES.map((type) => (
          <label className="checkbox-card" key={type.value}>
            <input
              type="checkbox"
              checked={value.includes(type.value)}
              onChange={() => toggle(type.value)}
            />
            <span className="custom-checkbox" aria-hidden="true">✓</span>
            <span>{type.label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
