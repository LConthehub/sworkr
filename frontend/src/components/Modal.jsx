import { useEffect } from 'react';

export default function Modal({ title, onClose, children, wide = false }) {
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose();
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto px-3 py-6 sm:px-4 sm:py-16">
      <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div role="dialog" aria-modal="true" className={`relative w-full ${wide ? 'max-w-2xl' : 'max-w-lg'} bg-white rounded-2xl shadow-xl`}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <h2 className="font-bold text-night">{title}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700" aria-label="Close">✕</button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

export const inputClass =
  'w-full bg-white border border-gray-200 rounded-lg px-3 py-2 text-sm text-ink focus:outline-none focus:border-sworkr-600 focus:ring-2 focus:ring-sworkr-100';

export function Field({ label, children }) {
  return (
    <label className="block">
      <span className="block text-xs font-medium text-gray-500 mb-1">{label}</span>
      {children}
    </label>
  );
}

export function errorMessage(err, fallback = 'Something went wrong') {
  const detail = err?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join(', ');
  if (detail && typeof detail.message === 'string') return detail.message;
  if (!err?.response) return "Can't reach the server. Check that sworkr is running.";
  return fallback;
}

export const buttonClass =
  'px-5 py-2 rounded-full bg-gradient-to-br from-sworkr-500 to-sworkr-600 text-white text-sm font-semibold hover:brightness-105 hover:shadow-[0_6px_18px_rgba(167,49,120,0.25)] disabled:opacity-50 disabled:shadow-none';
export const quietButtonClass =
  'px-3 py-2 rounded-full text-sm border border-sworkr-600/40 bg-white text-sworkr-600 hover:bg-sworkr-600 hover:text-white disabled:opacity-50';

/** A titled block on a settings or detail page. */
export function Section({ title, hint, children }) {
  return (
    <section className="bg-white rounded-2xl border border-line shadow-sm p-5 sm:p-6">
      <h2 className="font-bold text-night">{title}</h2>
      {hint && <p className="text-sm text-gray-500 mt-1">{hint}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

export function Notice({ message }) {
  if (!message) return null;
  const ok = !!message.ok;
  return (
    <p className={`text-sm rounded-lg px-3 py-2 ${ok ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'}`}>
      {message.ok || message.error}
    </p>
  );
}
