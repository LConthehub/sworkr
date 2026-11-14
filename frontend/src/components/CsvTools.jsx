import { useRef, useState } from 'react';
import axios from 'axios';
import { errorMessage } from './Modal';

const LABELS = { clients: 'clients', expenses: 'expenses' };

/** Export / Import CSV buttons for clients or expenses, with the import result underneath. */
export default function CsvTools({ kind, onImported }) {
  const input = useRef(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  // Dates in the file are in this computer's time zone.
  const tzOffset = new Date().getTimezoneOffset();

  const upload = async (e) => {
    const file = e.target.files[0];
    e.target.value = '';
    if (!file) return;
    setBusy(true);
    setResult(null);
    try {
      const { data } = await axios.post(`/api/csv/${kind}`, file, {
        params: { tz_offset: tzOffset },
        headers: { 'Content-Type': 'text/csv' },
      });
      const parts = [`${data.created} added`, `${data.updated} updated`];
      if (data.skipped) parts.push(`${data.skipped} skipped (already here)`);
      setResult({ ok: `Imported ${file.name}: ${parts.join(', ')}.` });
      onImported?.();
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setResult(detail?.errors
        ? { error: detail.message, errors: detail.errors }
        : { error: errorMessage(err, 'Could not import the file') });
    } finally {
      setBusy(false);
    }
  };

  const button = 'px-3 py-2 rounded-lg text-sm border border-gray-200 bg-white text-gray-600 hover:bg-gray-50';

  return (
    <>
      <a href={`/api/csv/${kind}?tz_offset=${tzOffset}`} download className={button} title={`Download all ${LABELS[kind]} as a CSV file`}>
        Export CSV
      </a>
      <button type="button" disabled={busy} onClick={() => input.current?.click()} className={`${button} disabled:opacity-50`}
        title={`Add or update ${LABELS[kind]} from a CSV file`}>
        {busy ? 'Importing…' : 'Import CSV'}
      </button>
      <input ref={input} type="file" accept=".csv,text/csv" className="hidden" onChange={upload} />
      {result && (
        <div className={`w-full text-sm rounded-lg px-3 py-2 ${result.ok ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'}`}>
          <div className="flex justify-between gap-2">
            <span>{result.ok || result.error}</span>
            <button type="button" onClick={() => setResult(null)} className="opacity-60 hover:opacity-100" aria-label="Dismiss">✕</button>
          </div>
          {result.errors && (
            <ul className="mt-1 list-disc pl-5 text-xs space-y-0.5">
              {result.errors.map((line) => <li key={line}>{line}</li>)}
            </ul>
          )}
        </div>
      )}
    </>
  );
}
