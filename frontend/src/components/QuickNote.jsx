import { useEffect, useRef, useState } from 'react';
import axios from 'axios';

/** Dashboard card: one scratch pad that saves itself a moment after you stop typing. */
export default function QuickNote() {
  const [text, setText] = useState(null);
  const [state, setState] = useState('');   // '', 'saving', 'saved', 'error'
  const timer = useRef(null);
  useEffect(() => {
    axios.get('/api/quick-note').then(({ data }) => setText(data.text)).catch(() => setText(''));
    return () => clearTimeout(timer.current);
  }, []);
  const change = (e) => {
    const value = e.target.value;
    setText(value);
    setState('saving');
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      axios.put('/api/quick-note', { text: value }).then(() => setState('saved')).catch(() => setState('error'));
    }, 800);
  };
  if (text === null) return null;
  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-5">
      <div className="flex items-center justify-between gap-2 mb-2">
        <h2 className="font-semibold text-gray-800">Notes</h2>
        <span className="text-xs text-gray-400" aria-live="polite">
          {state === 'saving' ? 'Saving…' : state === 'saved' ? 'Saved' : state === 'error' ? "Couldn't save" : ''}
        </span>
      </div>
      <textarea value={text} onChange={change} rows={6} aria-label="Quick notes"
        placeholder="Anything to remember: a number, an idea, what to buy…"
        className="w-full bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-sworkr-300" />
    </div>
  );
}
