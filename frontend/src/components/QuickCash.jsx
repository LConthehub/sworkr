import { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import Modal, { inputClass, buttonClass } from './Modal';
import { money } from '../colors';

// Entries that couldn't be sent (no signal) wait here, on this device only, until they can.
const QUEUE_KEY = 'sworkr:cash-queue';
const readQueue = () => { try { return JSON.parse(localStorage.getItem(QUEUE_KEY) || '[]'); } catch { return []; } };
const writeQueue = (q) => { try { localStorage.setItem(QUEUE_KEY, JSON.stringify(q)); } catch { /* storage unavailable */ } };
// No signal, sworkr not answering or failing (any 5xx), or logged out (401): keep it for later. Only an entry
// the server rejects as wrong (another 4xx) is dropped, since sending it again would fail the same way.
const unreachable = (err) => !err.response || err.response.status >= 500 || err.response.status === 401;

async function send(entry) {
  if (entry.direction === 'in') {
    await axios.post('/api/income', {
      date: entry.at, gross: entry.amount, fees: 0, kind: 'booking', status: 'received',
      description: entry.note || 'Cash', notes: 'Quick cash log',
    });
  } else {
    await axios.post('/api/expenses', {
      date: entry.at, amount: entry.amount, category: 'other', description: entry.note || 'Cash spent', notes: 'Quick cash log',
    });
  }
  window.dispatchEvent(new Event('sworkr:money-changed'));
}

/**
 * Try to send this person's entries still waiting (another person's, on a shared device, wait for them).
 * Network failures stay queued; anything the server refuses is dropped.
 */
let flushing = null;   // one flush at a time, or two could send the same entry
function flush(userId) {
  if (!flushing) flushing = flushNow(userId).finally(() => { flushing = null; });
  return flushing;
}

async function flushNow(userId) {
  let sent = 0;
  for (const entry of readQueue().filter((e) => e.user === userId)) {
    try {
      await send(entry);
    } catch (err) {
      if (unreachable(err)) continue;    // try again later
    }
    // Sent (or refused for good): take just this one out, keeping anything added meanwhile.
    writeQueue(readQueue().filter((e) => e.id !== entry.id));
    sent += 1;
  }
  return sent;
}

/**
 * A "+ $" button on every page: cash in or out in two taps (amount, save). Cash in is income (a booking paid
 * outside the calendar); cash out is an expense under Other, to sort later. Works with no signal: it's kept on
 * this device and added when sworkr can be reached again.
 */
export default function QuickCash({ userId }) {
  const [open, setOpen] = useState(false);
  const [direction, setDirection] = useState('in');
  const [amount, setAmount] = useState('');
  const [note, setNote] = useState('');
  const [message, setMessage] = useState('');
  const countMine = useCallback(() => readQueue().filter((e) => e.user === userId).length, [userId]);
  const [waiting, setWaiting] = useState(countMine);
  const amountRef = useRef(null);

  const retry = useCallback(async () => {
    const sent = await flush(userId);
    setWaiting(countMine());
    if (sent) setMessage(`Added ${sent} cash entr${sent === 1 ? 'y' : 'ies'} saved while offline.`);
  }, [userId, countMine]);
  useEffect(() => {
    retry();
    window.addEventListener('online', retry);
    return () => window.removeEventListener('online', retry);
  }, [retry]);
  useEffect(() => { if (!message) return undefined; const t = setTimeout(() => setMessage(''), 4000); return () => clearTimeout(t); }, [message]);

  const save = async (e) => {
    e.preventDefault();
    const value = Number(amount);
    if (!(value > 0)) return;
    const entry = { id: `${Date.now()}-${Math.random().toString(36).slice(2)}`, user: userId, direction, amount: Math.round(value * 100) / 100, note: note.trim(), at: new Date().toISOString() };
    setOpen(false);
    setAmount('');
    setNote('');
    try {
      await send(entry);
      setMessage(`${direction === 'in' ? 'Added' : 'Spent'} ${money(entry.amount)}.`);
    } catch (err) {
      if (!unreachable(err)) { setMessage(err.response.data?.detail || "Couldn't save it"); return; }
      writeQueue([...readQueue(), entry]);
      setWaiting(countMine());
      setMessage(`No connection: ${money(entry.amount)} is saved on this device and will be added when you're back online.`);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => { setOpen(true); setTimeout(() => amountRef.current?.focus(), 50); }}
        className="print:hidden fixed z-40 right-4 bottom-20 sm:bottom-6 h-14 px-5 rounded-full bg-sworkr-600 text-white text-lg font-bold shadow-xl hover:bg-sworkr-700"
        aria-label="Log cash quickly"
        title="Log cash in or out"
      >
        + $
        {waiting > 0 && <span className="ml-1 text-xs font-medium bg-white text-sworkr-700 rounded-full px-1.5" title="Waiting to be added">{waiting}</span>}
      </button>
      {message && (
        <p role="status" className="fixed z-40 right-4 bottom-36 sm:bottom-24 max-w-xs rounded-xl bg-gray-900/90 text-white text-sm px-3 py-2 shadow-lg">{message}</p>
      )}
      {open && (
        <Modal title="Quick cash" onClose={() => setOpen(false)}>
          <form onSubmit={save} className="space-y-3">
            <div className="grid grid-cols-2 gap-2" role="group" aria-label="In or out">
              {[['in', 'Money in'], ['out', 'Money out']].map(([v, l]) => (
                <button key={v} type="button" onClick={() => setDirection(v)} aria-pressed={direction === v}
                  className={`py-3 rounded-xl text-sm font-semibold border ${direction === v
                    ? (v === 'in' ? 'bg-emerald-600 text-white border-emerald-600' : 'bg-red-600 text-white border-red-600')
                    : 'bg-white text-gray-700 border-gray-200'}`}>
                  {l}
                </button>
              ))}
            </div>
            <input ref={amountRef} required type="number" min="0.01" step="0.01" inputMode="decimal" value={amount}
              onChange={(e) => setAmount(e.target.value)} placeholder="$0" aria-label="Amount" className={`${inputClass} text-2xl text-center`} />
            <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="What for (optional)" aria-label="What for" className={inputClass} />
            <button type="submit" disabled={!(Number(amount) > 0)} className={`${buttonClass} w-full py-3`}>Save</button>
            <p className="text-xs text-gray-500">
              {direction === 'in' ? 'Added to income as a booking paid outside the calendar.' : 'Added to expenses under Other, to sort later.'} Works offline too.
            </p>
          </form>
        </Modal>
      )}
    </>
  );
}
