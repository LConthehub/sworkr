import { useEffect, useRef, useState } from 'react';
import { Field, inputClass, Notice } from './Modal';

/*
 * Discreet mode, set per device (it's about who might glance at this screen):
 * - the browser tab gets a plain title and icon instead of "Sworkr";
 * - a panic switch hides everything at once, logs out, and shows a plain notes page. It's the Esc key pressed
 *   three times quickly, or the "Hide" button that appears in the top bar.
 * Coming back needs the password, as after any log-out.
 */
const KEY = 'sworkr:discreet';
const DEFAULTS = { enabled: false, title: 'Notes', panicButton: true };

export function readDiscreet() {
  try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || '{}') }; } catch { return DEFAULTS; }
}
function saveDiscreet(value) {
  try { localStorage.setItem(KEY, JSON.stringify(value)); } catch { /* not remembered */ }
  window.dispatchEvent(new Event('sworkr:discreet-changed'));
}

// A plain grey square: looks like any notes or docs tab.
const NEUTRAL_ICON = 'data:image/svg+xml,' + encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><rect x="2" y="1" width="12" height="14" rx="2" fill="#9ca3af"/>'
  + '<rect x="4.5" y="4" width="7" height="1.4" fill="#fff"/><rect x="4.5" y="7" width="7" height="1.4" fill="#fff"/>'
  + '<rect x="4.5" y="10" width="5" height="1.4" fill="#fff"/></svg>');

export function useDiscreet() {
  const [value, setValue] = useState(readDiscreet);
  useEffect(() => {
    const update = () => setValue(readDiscreet());
    window.addEventListener('sworkr:discreet-changed', update);
    window.addEventListener('storage', update);
    return () => { window.removeEventListener('sworkr:discreet-changed', update); window.removeEventListener('storage', update); };
  }, []);
  // The tab title and icon follow the setting (on the login page too).
  useEffect(() => {
    document.title = value.enabled ? (value.title || 'Notes') : 'Sworkr';
    let link = document.querySelector('link[rel="icon"]');
    if (value.enabled) {
      if (!link) { link = document.createElement('link'); link.rel = 'icon'; document.head.appendChild(link); }
      link.href = NEUTRAL_ICON;
    } else if (link) {
      link.remove();
    }
  }, [value]);
  return value;
}

/** Esc three times within 1.5 seconds calls onPanic (when discreet mode is on). */
export function usePanicKey(enabled, onPanic) {
  const presses = useRef([]);
  useEffect(() => {
    if (!enabled) return undefined;
    const onKey = (e) => {
      if (e.key !== 'Escape') return;
      const now = Date.now();
      presses.current = [...presses.current.filter((t) => now - t < 1500), now];
      if (presses.current.length >= 3) { presses.current = []; onPanic(); }
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [enabled, onPanic]);
}

/** What's shown after the panic switch: a dull notes page. Nothing from sworkr is left on screen or in memory. */
export function DecoyScreen({ title }) {
  return (
    <div className="min-h-screen bg-white text-gray-800">
      <div className="max-w-2xl mx-auto px-6 py-10">
        <h1 className="text-2xl font-semibold mb-6">{title || 'Notes'}</h1>
        <div className="space-y-4 text-[15px] leading-relaxed">
          <p className="font-medium">Groceries</p>
          <ul className="list-disc pl-6 text-gray-700">
            <li>Oat milk</li><li>Spinach</li><li>Coffee filters</li><li>Lemons</li><li>Rice</li>
          </ul>
          <p className="font-medium pt-2">This week</p>
          <ul className="list-disc pl-6 text-gray-700">
            <li>Return library books</li><li>Call about the internet bill</li><li>Water the plants</li>
          </ul>
        </div>
      </div>
    </div>
  );
}

/** Settings section (Security & privacy). */
export function DiscreetSettings() {
  const [form, setForm] = useState(readDiscreet);
  const [message, setMessage] = useState(null);
  const save = (changes) => {
    const next = { ...form, ...changes };
    setForm(next);
    saveDiscreet(next);
    setMessage({ ok: 'Saved on this device.' });
  };
  return (
    <div className="space-y-3">
      <label className="flex items-start gap-2 text-sm text-gray-700">
        <input type="checkbox" className="mt-1" checked={form.enabled} onChange={(e) => save({ enabled: e.target.checked })} />
        <span>
          Discreet on this device
          <span className="block text-xs text-gray-500">The browser tab shows a plain title and icon instead of “Sworkr”, and the panic switch is on.</span>
        </span>
      </label>
      {form.enabled && (
        <>
          <Field label="Tab title">
            <input value={form.title} maxLength={40} onChange={(e) => setForm({ ...form, title: e.target.value })}
              onBlur={() => save({ title: form.title.trim() || 'Notes' })} className={`${inputClass} max-w-xs`} />
          </Field>
          <label className="flex items-start gap-2 text-sm text-gray-700">
            <input type="checkbox" className="mt-1" checked={form.panicButton} onChange={(e) => save({ panicButton: e.target.checked })} />
            <span>
              Show a “Hide” button in the top bar
              <span className="block text-xs text-gray-500">For phones. On a computer, pressing Esc three times quickly does the same.</span>
            </span>
          </label>
          <p className="text-sm text-gray-600">
            The panic switch hides sworkr at once, logs you out and shows a plain notes page. Getting back in needs your password.
          </p>
        </>
      )}
      <Notice message={message} />
    </div>
  );
}
