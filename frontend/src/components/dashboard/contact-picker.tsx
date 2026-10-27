import { useMemo, useState } from "react";
import type { Contact } from "@/lib/api/types";
import { formatPhoneNumber, searchablePhone } from "@/lib/phone";

interface ContactPickerProps {
  contacts: Contact[];
  selected: Contact | null;
  loading: boolean;
  error: string | null;
  disabled?: boolean;
  onSelect: (contact: Contact | null) => void;
  onRetry: () => void;
}

/** Rendering thousands of list rows is what made the page choke; cap the DOM and keep typing. */
const MATCH_RENDER_LIMIT = 200;

export function ContactPicker({
  contacts,
  selected,
  loading,
  error,
  disabled,
  onSelect,
  onRetry,
}: ContactPickerProps) {
  const [query, setQuery] = useState("");
  const filteredContacts = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) return contacts;
    const digitNeedle = searchablePhone(needle);
    return contacts.filter((contact) => {
      if (contact.name.toLocaleLowerCase().includes(needle)) return true;
       if ((contact.phone_display ?? contact.number ?? "").toLocaleLowerCase().includes(needle)) return true;
      // Typing digits should find contacts whose stored number has country codes or
      // formatting characters around them, e.g. "98765" matches "91 98765 43210".
      const numberDigits = searchablePhone(contact.phone_display ?? contact.number);
      return digitNeedle.length >= 3 && numberDigits.includes(digitNeedle);
    });
  }, [contacts, query]);

  return (
    <div className="contact-picker">
      <div className="contact-picker-heading">
        <div>
          <label className="field-label" htmlFor="contact-search">Send to</label>
          <p className="muted-text">Choose a WhatsApp contact. Groups are not shown.</p>
        </div>
        {selected && (
          <button className="text-button" type="button" onClick={() => onSelect(null)}>
            Clear
          </button>
        )}
      </div>
      <div className="search-input-wrap">
        <span aria-hidden="true" className="search-icon">⌕</span>
        <input
          id="contact-search"
          type="search"
          placeholder="Search by name or number"
          value={query}
          disabled={disabled || loading}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      {selected && (
        <div className="selected-contact">
          <span className="avatar">{selected.name.charAt(0).toUpperCase()}</span>
          <span>
            <strong>{selected.name}</strong>
           <small>{formatPhoneNumber(selected.phone_display ?? selected.number) ?? "Phone number unavailable"}</small>
          </span>
          <span className="selected-check" aria-label="Selected">✓</span>
        </div>
      )}
      <div className="contact-results" aria-live="polite">
        {loading && <div className="empty-mini"><span className="spinner dark" /> Loading contacts…</div>}
        {!loading && error && (
          <div className="empty-mini error-mini">
            <span>{error}</span>
            <button className="text-button" type="button" onClick={onRetry}>Retry</button>
          </div>
        )}
        {!loading && !error && !contacts.length && (
          <div className="empty-mini">No contacts are available while WhatsApp is disconnected.</div>
        )}
        {!loading && !error && contacts.length > 0 && !filteredContacts.length && (
          <div className="empty-mini">No contacts match “{query}”.</div>
        )}
        {!loading && !error && filteredContacts.length > 0 && (
          <>
            <ul className="contact-list">
              {filteredContacts.slice(0, MATCH_RENDER_LIMIT).map((contact) => (
                <li key={contact.id}>
                  <button
                    className={selected?.id === contact.id ? "contact-option selected" : "contact-option"}
                    type="button"
                    disabled={disabled}
                    onClick={() => onSelect(contact)}
                  >
                    <span className="avatar">{contact.name.charAt(0).toUpperCase()}</span>
                    <span className="contact-option-copy">
                      <strong>{contact.name}</strong>
                       <small>{formatPhoneNumber(contact.phone_display ?? contact.number) ?? "Phone number unavailable"}</small>
                    </span>
                    {selected?.id === contact.id && <span className="selected-check">✓</span>}
                  </button>
                </li>
              ))}
            </ul>
            {filteredContacts.length > MATCH_RENDER_LIMIT && (
              <div className="empty-mini">
                Showing the first {MATCH_RENDER_LIMIT} of {filteredContacts.length} results. Keep typing to narrow the list.
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
