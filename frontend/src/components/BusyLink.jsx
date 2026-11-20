import { useEffect, useState } from 'react';
import axios from 'axios';
import { Field, inputClass, errorMessage, buttonClass, quietButtonClass } from './Modal';

/**
 * A private link a home or family calendar can follow to see when you're working, and nothing else:
 * no client, service, place or notes are ever put in it. Off until made.
 */
export default function BusyLink() {
  const [link, setLink] = useState(null);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);
  useEffect(() => { axios.get('/api/busy-link').then(({ data }) => setLink(data)).catch(() => {}); }, []);
  if (!link) return null;
  const ask = async (send) => { setError(''); try { setLink((await send()).data); } catch (err) { setError(errorMessage(err, "Couldn't do that")); } };
  const address = link.path ? window.location.origin + link.path : '';
  const copy = async () => {
    try { await navigator.clipboard.writeText(address); setCopied(true); setTimeout(() => setCopied(false), 2500); } catch { setError('Copying was refused: press and hold the link to copy it instead'); }
  };
  return (
    <div className="space-y-3 text-sm text-gray-700">
      <p>
        Lets a home or family calendar show <b>when</b> you're working, and nothing else. Each booking shows as "Busy" with
        its times, a tour as "Away" and time off as "Off". No client, service, place, note or amount is ever put in it, so
        none of that can leave sworkr through this link.
      </p>
      {!link.on ? (
        <button type="button" onClick={() => ask(() => axios.put('/api/busy-link'))} className={buttonClass}>Make a busy link</button>
      ) : (
        <>
          <Field label="Your busy link">
            <input readOnly value={address} onFocus={(e) => e.target.select()} className={`${inputClass} font-mono text-xs`} />
          </Field>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={copy} className={buttonClass}>{copied ? 'Copied' : 'Copy the link'}</button>
            <button type="button" onClick={() => { if (window.confirm('Make a new link? The old one stops working, and whatever follows it has to be given the new one.')) ask(() => axios.post('/api/busy-link/renew')); }} className={quietButtonClass}>Make a new link</button>
            <button type="button" onClick={() => { if (window.confirm('Turn the busy link off? Whatever follows it stops getting anything.')) ask(() => axios.delete('/api/busy-link')); }} className={quietButtonClass}>Turn it off</button>
          </div>
          <ul className="list-disc space-y-1 pl-5 text-xs text-gray-600">
            <li>Anyone who has this link can see when you're busy, without a password. Give it only to a calendar you trust.</li>
            <li>It reaches from {link.days_back} days back to a year ahead. Cancelled bookings are left out.</li>
            <li>{link.read_at ? `Last read ${new Date(link.read_at).toLocaleString()}.` : 'Nothing has read it yet.'}</li>
          </ul>
        </>
      )}
      {error && <p className="text-red-600">{error}</p>}
    </div>
  );
}
