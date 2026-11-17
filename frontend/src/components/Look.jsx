import { useState } from 'react';

const CHOICES = [
  ['light', 'Light', 'The usual pink.'],
  ['dark', 'Dark', 'Easier on the eyes at night.'],
  ['system', 'Follow my device', 'Dark when your phone or computer is in dark mode, like sworkr.com.'],
];

const current = () => {
  try { return localStorage.getItem('sworkr:theme') || 'light'; } catch { return 'light'; }
};

/** Settings > Look: light, dark, or follow the device. Kept on this device only (public/theme.js applies it). */
export default function LookSettings() {
  const [choice, setChoice] = useState(current);
  const pick = (value) => {
    setChoice(value);
    window.sworkrTheme?.(value);
  };
  return (
    <fieldset className="space-y-2">
      <legend className="sr-only">Light or dark</legend>
      {CHOICES.map(([value, label, hint]) => (
        <label key={value} className={`flex items-start gap-3 rounded-xl border px-4 py-3 cursor-pointer ${choice === value ? 'border-sworkr-300 bg-sworkr-50' : 'border-gray-200 hover:bg-gray-50'}`}>
          <input type="radio" name="look" value={value} checked={choice === value} onChange={() => pick(value)} className="mt-1 accent-sworkr-600" />
          <span>
            <span className="block font-medium text-gray-800">{label}</span>
            <span className="block text-xs text-gray-500">{hint}</span>
          </span>
        </label>
      ))}
      <p className="text-xs text-gray-400">Set on each phone or computer separately.</p>
    </fieldset>
  );
}
