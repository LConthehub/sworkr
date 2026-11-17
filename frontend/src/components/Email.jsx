import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import axios from 'axios';
import Modal, { errorMessage, inputClass, buttonClass, quietButtonClass } from './Modal';
import ClientForm from './ClientForm';
import { dayLabel, formatTime, sameDay } from '../colors';

const whenLabel = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  return sameDay(d, new Date()) ? formatTime(d) : dayLabel(d, { month: 'short', day: 'numeric' });
};
const senderLabel = (m) => m.contact?.display_name || m.from.name || m.from.email || 'Unknown sender';

/** Unread and important emails, with a reader, replies and "add as contact". */
export function EmailPanel() {
  const [which, setWhich] = useState('unread');
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [notSetUp, setNotSetUp] = useState(false);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(null); // a uid
  // With more than one email account, a switch between them. Each is its own inbox.
  const [accounts, setAccounts] = useState([]);
  const [account, setAccount] = useState(1);
  useEffect(() => {
    axios.get('/api/mail/accounts').then(({ data: d }) => {
      const on = d.accounts.filter((a) => a.enabled);
      setAccounts(on);
      if (on.length && !on.some((a) => a.account === 1)) setAccount(on[0].account);
    }).catch(() => {});
  }, []);

  const load = useCallback(async (fresh = false) => {
    setLoading(true);
    try {
      const { data: result } = await axios.get('/api/mail/messages', { params: { which, fresh, account } });
      setData(result);
      setError('');
      setNotSetUp(false);
    } catch (err) {
      if (err?.response?.status === 409) setNotSetUp(true);
      else if (err?.response?.status !== 401) setError(errorMessage(err, "Couldn't load your email."));
    } finally {
      setLoading(false);
    }
  }, [which, account]);
  useEffect(() => { load(); }, [load]);

  if (notSetUp) {
    return (
      <div className="bg-white rounded-2xl border border-line shadow-sm p-4 sm:p-5">
        <h2 className="font-semibold text-gray-800">Email</h2>
        <p className="text-sm text-gray-500 mt-1">
          See your unread and important emails here, reply to them, and add senders as contacts.
        </p>
        <Link to="/account/connections#email" className={`${buttonClass} inline-block mt-3`}>Connect your email</Link>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-2xl border border-line shadow-sm p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <h2 className="font-semibold text-gray-800">Email</h2>
        <div className="flex flex-wrap items-center gap-2">
          {accounts.length > 1 && (
            <select value={account} onChange={(e) => { setData(null); setAccount(Number(e.target.value)); }} aria-label="Email account"
              className="rounded-lg border border-gray-200 px-2 py-1 text-sm text-gray-700 bg-white max-w-[10rem]">
              {accounts.map((a) => <option key={a.account} value={a.account}>{a.label}</option>)}
            </select>
          )}
          <div className="inline-flex rounded-lg border border-gray-200 overflow-hidden text-sm" role="group" aria-label="Which emails">
            {[['unread', 'Unread'], ['important', 'Important']].map(([id, label]) => (
              <button key={id} onClick={() => setWhich(id)} aria-pressed={which === id}
                className={`px-3 py-1 ${which === id ? 'bg-sworkr-500 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}>
                {label}{which === id && data ? ` (${data.total})` : ''}
              </button>
            ))}
          </div>
          <button onClick={() => load(true)} disabled={loading} className="w-8 h-8 rounded-full hover:bg-gray-100 text-gray-500 disabled:opacity-40" aria-label="Check for new email" title="Check for new email">
            ↻
          </button>
        </div>
      </div>
      {data?.demo && <p className="text-xs text-gray-400 mb-2">Demo: a made-up inbox. Nothing is sent anywhere.</p>}
      {error && <p className="text-sm rounded-lg px-3 py-2 bg-red-50 text-red-700 mb-2">{error}</p>}
      {!data ? (
        <p className="text-sm text-gray-400 py-4">{loading ? 'Checking your email…' : ''}</p>
      ) : data.messages.length === 0 ? (
        <p className="text-sm text-gray-400 py-4">{which === 'unread' ? 'No unread email. 🎉' : 'Nothing flagged as important.'}</p>
      ) : (
        <ul className="divide-y divide-gray-100">
          {data.messages.map((m) => (
            <li key={m.uid}>
              <button onClick={() => setOpen(m.uid)} className="w-full text-left py-2 flex items-start gap-2 hover:bg-gray-50 rounded-lg px-1">
                <span className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ${m.unread ? 'bg-sworkr-500' : 'bg-transparent'}`} aria-label={m.unread ? 'Unread' : undefined} />
                <span className="flex-1 min-w-0">
                  <span className="flex items-baseline gap-2">
                    <span className={`truncate text-sm ${m.unread ? 'font-semibold text-gray-900' : 'text-gray-700'}`}>{senderLabel(m)}</span>
                    {m.contact && <span className="shrink-0 text-[10px] px-1.5 rounded-full bg-sworkr-50 text-sworkr-600">contact</span>}
                    {m.flagged && <span className="shrink-0 text-amber-500 text-xs" aria-label="Important">★</span>}
                    <span className="ml-auto shrink-0 text-xs text-gray-400">{whenLabel(m.date)}</span>
                  </span>
                  <span className="block truncate text-sm text-gray-600">{m.subject || '(no subject)'}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {data && data.total > data.messages.length && (
        <p className="text-xs text-gray-400 mt-2">Showing the newest {data.messages.length} of {data.total}.</p>
      )}
      {open && <MessageModal uid={open} account={account} onClose={() => setOpen(null)} onChanged={() => load(true)} />}
    </div>
  );
}

function MessageModal({ uid, account = 1, onClose, onChanged }) {
  const navigate = useNavigate();
  const [m, setM] = useState(null);
  const [error, setError] = useState('');
  const [replying, setReplying] = useState(false);
  const [reply, setReply] = useState('');
  const [replyAll, setReplyAll] = useState(false);
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState('');
  const [addingContact, setAddingContact] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await axios.get(`/api/mail/messages/${uid}`, { params: { account } });
      setM(data);
    } catch (err) {
      setError(errorMessage(err, "Couldn't open that email."));
    }
  }, [uid]);
  useEffect(() => { load(); }, [load]);

  const setFlags = async (changes) => {
    try {
      await axios.post(`/api/mail/messages/${uid}/flags`, changes, { params: { account } });
      setM((x) => ({ ...x, ...changes }));
      onChanged();
    } catch (err) {
      setError(errorMessage(err, 'Could not change that'));
    }
  };
  const send = async () => {
    setSending(true);
    setError('');
    try {
      const { data } = await axios.post(`/api/mail/messages/${uid}/reply`, { body: reply, reply_all: replyAll }, { params: { account } });
      setReplying(false);
      setReply('');
      setNotice(data.demo ? 'Demo: the reply was not actually sent.' : `Sent to ${data.sent_to}.`);
      setM((x) => ({ ...x, unread: false, answered: true }));
      onChanged();
    } catch (err) {
      setError(errorMessage(err, 'The reply could not be sent'));
    } finally {
      setSending(false);
    }
  };

  const others = m ? [...m.to, ...m.cc].length > 1 : false;

  return (
    <Modal title={m ? m.subject || '(no subject)' : 'Email'} onClose={onClose} wide>
      {!m ? (
        <p className="text-sm text-gray-500">{error || 'Opening…'}</p>
      ) : addingContact ? (
        <>
          <p className="text-sm text-gray-500 mb-3">Add {m.from.name || m.from.email} as a contact. Check the details, then save.</p>
          <ClientForm
            initial={{ name: m.from.name || '', email: m.from.email || '', bio: `First emailed: "${m.subject || 'no subject'}"` }}
            onSaved={(c) => { setAddingContact(false); setM((x) => ({ ...x, contact: { id: c.id, display_name: c.display_name } })); onChanged(); }}
          />
          <button onClick={() => setAddingContact(false)} className={`${quietButtonClass} mt-3`}>Back to the email</button>
        </>
      ) : (
        <div className="space-y-3">
          <div className="text-sm text-gray-600 space-y-0.5">
            <p>
              <span className="text-gray-400">From </span>
              <span className="font-medium text-gray-800">{m.from.name || m.from.email}</span>
              {m.from.name && <span className="text-gray-500"> &lt;{m.from.email}&gt;</span>}
            </p>
            {m.to.length > 0 && <p className="truncate"><span className="text-gray-400">To </span>{m.to.map((a) => a.email).join(', ')}</p>}
            {m.cc.length > 0 && <p className="truncate"><span className="text-gray-400">Cc </span>{m.cc.map((a) => a.email).join(', ')}</p>}
            <p className="text-xs text-gray-400">{m.date && new Date(m.date).toLocaleString()}</p>
          </div>

          <div className="flex flex-wrap gap-2">
            {m.contact ? (
              <button onClick={() => { onClose(); navigate(`/contacts/${m.contact.id}`); }} className={quietButtonClass}>Open {m.contact.display_name}</button>
            ) : m.from.email && (
              <button onClick={() => setAddingContact(true)} className={quietButtonClass}>+ Add as contact</button>
            )}
            <button onClick={() => setFlags({ unread: !m.unread })} className={quietButtonClass}>{m.unread ? 'Mark read' : 'Mark unread'}</button>
            <button onClick={() => setFlags({ flagged: !m.flagged })} className={quietButtonClass}>{m.flagged ? '★ Unflag' : '☆ Flag as important'}</button>
            {!replying && <button onClick={() => setReplying(true)} className={buttonClass}>Reply</button>}
          </div>

          {notice && <p className="text-sm text-emerald-700">{notice}</p>}
          {error && <p className="text-sm text-red-600">{error}</p>}

          {replying && (
            <div className="rounded-xl border border-gray-200 p-3 space-y-2">
              <textarea autoFocus rows={6} value={reply} onChange={(e) => setReply(e.target.value)} placeholder="Write your reply…" className={inputClass} aria-label="Your reply" />
              <div className="flex flex-wrap items-center gap-3">
                {others && (
                  <label className="flex items-center gap-2 text-sm text-gray-600">
                    <input type="checkbox" checked={replyAll} onChange={(e) => setReplyAll(e.target.checked)} /> Reply to everyone
                  </label>
                )}
                <span className="text-xs text-gray-400">Sent from your own email account, with the original quoted below.</span>
                <span className="ml-auto flex gap-2">
                  <button onClick={() => setReplying(false)} className={quietButtonClass}>Cancel</button>
                  <button onClick={send} disabled={sending || !reply.trim()} className={buttonClass}>{sending ? 'Sending…' : 'Send'}</button>
                </span>
              </div>
            </div>
          )}

          <div className="rounded-xl bg-gray-50 px-4 py-3 text-sm text-gray-800 whitespace-pre-wrap break-words max-h-[50vh] overflow-y-auto">
            {m.text || '(This email has no text.)'}
          </div>
          {m.attachments.length > 0 && (
            <p className="text-xs text-gray-500">Attachments (open them in your email app): {m.attachments.join(', ')}</p>
          )}
        </div>
      )}
    </Modal>
  );
}
