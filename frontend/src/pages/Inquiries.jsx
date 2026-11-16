import { useCallback, useEffect, useState } from 'react';
import { Link, NavLink } from 'react-router-dom';
import axios from 'axios';
import Modal, { Field, inputClass, errorMessage, buttonClass, quietButtonClass } from '../components/Modal';
import ClientForm from '../components/ClientForm';
import { useSnippets } from '../components/Promo';
import { dayLabel, fromDateTimeInputs, money, toDateInput, toTimeInput } from '../colors';

const STAGES = [
  { id: 'new', label: 'New', badge: 'bg-amber-100 text-amber-800', next: 'Replied' },
  { id: 'replied', label: 'Replied', badge: 'bg-sky-100 text-sky-700', next: 'Screening' },
  { id: 'screening', label: 'Screening', badge: 'bg-violet-100 text-violet-700', next: 'Deposit' },
  { id: 'deposit', label: 'Deposit', badge: 'bg-sworkr-50 text-sworkr-600', next: 'Booked' },
  { id: 'booked', label: 'Booked', badge: 'bg-emerald-100 text-emerald-700' },
];
const LOST = { id: 'lost', label: 'Lost', badge: 'bg-gray-100 text-gray-500' };
const stageOf = (id) => STAGES.find((s) => s.id === id) || LOST;
const LOST_REASONS = ["Went quiet", "Wouldn't screen", 'Wanted a discount', 'Dates didn\'t work', 'Not a fit', 'Time waster'];
const shortDay = (iso) => dayLabel(new Date(iso), { weekday: 'short', month: 'short', day: 'numeric' });

/** The pills at the top of Contacts, Inquiries and Gone quiet. */
export function PeopleNav({ dark = false }) {
  const base = dark ? 'text-gray-600 hover:bg-gray-100' : 'text-white hover:bg-white/20';
  const active = dark ? 'bg-sworkr-500 text-white' : 'bg-white text-sworkr-600 shadow';
  return (
    <nav className={`flex gap-1 overflow-x-auto rounded-full p-1 ${dark ? 'bg-gray-50' : 'bg-white/20 backdrop-blur-sm'}`} aria-label="People">
      {[['/contacts', 'Everyone'], ['/contacts/inquiries', 'Inquiries'], ['/contacts/quiet', 'Gone quiet']].map(([to, label]) => (
        <NavLink key={to} to={to} end className={({ isActive }) => `whitespace-nowrap px-3 sm:px-4 py-1.5 rounded-full text-sm font-medium ${isActive ? active : base}`}>
          {label}
        </NavLink>
      ))}
    </nav>
  );
}

/** Inquiries: everyone who got in touch, and how far each one has got. */
export default function Inquiries() {
  const [show, setShow] = useState('open');
  const [rows, setRows] = useState(null);
  const [summary, setSummary] = useState(null);
  const [modal, setModal] = useState(null); // { inquiry } | { contactFor }
  const [error, setError] = useState('');
  const year = new Date().getFullYear();

  const load = useCallback(() => {
    axios.get('/api/inquiries', { params: { show } }).then(({ data }) => setRows(data)).catch(() => setRows([]));
    axios.get('/api/inquiries/summary', { params: { start: new Date(year, 0, 1).toISOString(), end: new Date(year + 1, 0, 1).toISOString() } })
      .then(({ data }) => setSummary(data)).catch(() => {});
  }, [show, year]);
  useEffect(() => { load(); }, [load]);

  const move = async (e, stage) => {
    let lost_reason = null;
    if (stage === 'lost') {
      lost_reason = window.prompt(`Why was it lost? (${LOST_REASONS.slice(0, 4).join(', ')}…)`, 'Went quiet');
      if (lost_reason === null) return;
    }
    try {
      await axios.post(`/api/inquiries/${e.id}/stage`, { stage, lost_reason });
      setError('');
      load();
    } catch (err) {
      setError(errorMessage(err, 'Could not save'));
    }
  };
  const linkContact = async (e, client) => {
    await axios.put(`/api/inquiries/${e.id}`, { ...e, client_id: client.id }).catch(() => {});
    setModal(null);
    load();
  };

  const groups = show === 'open' ? STAGES.slice(0, 4).map((s) => ({ ...s, items: (rows || []).filter((e) => e.stage === s.id) })).filter((g) => g.items.length)
    : [{ id: show, label: '', items: rows || [] }];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold text-white">Contacts</h1>
        <PeopleNav />
      </div>

      <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
          <div className="inline-flex rounded-lg border border-gray-200 overflow-hidden text-sm" role="group" aria-label="Show">
            {[['open', 'Open'], ['booked', 'Booked'], ['lost', 'Lost'], ['all', 'All']].map(([id, label]) => (
              <button key={id} onClick={() => setShow(id)} aria-pressed={show === id} className={`px-3 py-1.5 ${show === id ? 'bg-sworkr-500 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}>{label}</button>
            ))}
          </div>
          <button onClick={() => setModal({ inquiry: {} })} className="px-4 py-2 rounded-full text-sm font-medium bg-sworkr-500 text-white hover:bg-sworkr-600">+ New inquiry</button>
        </div>
        <p className="text-xs text-gray-500 mb-3">
          Note each person who gets in touch and move them along as you reply, screen and take a deposit. sworkr sends nothing:
          it keeps track, and shows where inquiries drop out and which ads send people who book.
        </p>
        {error && <p className="text-sm text-red-600 mb-2">{error}</p>}
        {!rows ? null : rows.length === 0 ? (
          <p className="text-sm text-gray-400 py-8 text-center">{show === 'open' ? 'No open inquiries. Add one when someone gets in touch.' : 'Nothing here yet.'}</p>
        ) : (
          <div className="space-y-4">
            {groups.map((g) => (
              <section key={g.id}>
                {g.label && <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">{g.label} · {g.items.length}</h3>}
                <ul className="divide-y divide-gray-100">
                  {g.items.map((e) => {
                    const stage = stageOf(e.stage);
                    const nextStage = STAGES[STAGES.findIndex((s) => s.id === e.stage) + 1];
                    return (
                      <li key={e.id} className="py-2.5 flex flex-wrap items-start gap-x-3 gap-y-1">
                        <button onClick={() => setModal({ inquiry: e })} className="flex-1 min-w-48 text-left">
                          <span className="flex flex-wrap items-center gap-2">
                            <span className="font-medium text-gray-800">{e.name}</span>
                            <span className={`text-[10px] px-2 py-0.5 rounded-full ${stage.badge}`}>{stage.label}</span>
                            {e.found_via && <span className="text-xs text-gray-500">via {e.found_via}</span>}
                          </span>
                          <span className="block text-xs text-gray-500">
                            {shortDay(e.received_at)}{e.contact && ` · ${e.contact}`}{e.wanted_date && ` · wants ${shortDay(e.wanted_date)}`}
                          </span>
                          {e.wanted && <span className="block text-sm text-gray-600 line-clamp-2 whitespace-pre-wrap">{e.wanted}</span>}
                          {e.stage === 'lost' && <span className="block text-xs text-gray-400">Lost at {stageOf(e.lost_from).label.toLowerCase()}{e.lost_reason ? `: ${e.lost_reason}` : ''}</span>}
                        </button>
                        <span className="flex flex-wrap gap-2 shrink-0">
                          {e.client_id
                            ? <Link to={`/contacts/${e.client_id}`} className="text-xs px-2.5 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50">{e.client_name} →</Link>
                            : e.stage !== 'lost' && <button onClick={() => setModal({ contactFor: e })} className="text-xs px-2.5 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50">Make a contact</button>}
                          {nextStage && e.stage !== 'lost' && <button onClick={() => move(e, nextStage.id)} className="text-xs px-2.5 py-1.5 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700">{nextStage.label} →</button>}
                          {e.stage !== 'lost' && e.stage !== 'booked' && <button onClick={() => move(e, 'lost')} className="text-xs px-2.5 py-1.5 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50">Lost</button>}
                          {e.stage === 'lost' && <button onClick={() => move(e, e.lost_from || 'new')} className="text-xs px-2.5 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50">Reopen</button>}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </section>
            ))}
          </div>
        )}
      </div>

      {summary?.total > 0 && <Summary data={summary} year={year} />}

      {modal?.inquiry && (
        <Modal title={modal.inquiry.id ? 'Edit inquiry' : 'New inquiry'} onClose={() => setModal(null)}>
          <InquiryForm inquiry={modal.inquiry} onDone={() => { setModal(null); load(); }} />
        </Modal>
      )}
      {modal?.contactFor && (
        <Modal title="Make a contact" onClose={() => setModal(null)}>
          <ClientForm
            initial={{ name: modal.contactFor.name, found_via: modal.contactFor.found_via || '', bio: modal.contactFor.wanted || '',
              email: /^\S+@\S+\.\S+$/.test(modal.contactFor.contact || '') ? modal.contactFor.contact : '' }}
            onSaved={(client) => linkContact(modal.contactFor, client)}
          />
        </Modal>
      )}
    </div>
  );
}

function Summary({ data, year }) {
  const top = data.funnel[0].count || 1;
  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6 space-y-4">
      <div>
        <h2 className="font-semibold text-gray-800">How {year} is going</h2>
        <p className="text-sm text-gray-500">
          {data.total} inquir{data.total === 1 ? 'y' : 'ies'}, {data.booked} booked{data.rate != null && ` (${Math.round(data.rate * 100)}%)`}, {data.lost} lost, {data.open} still open.
        </p>
      </div>
      <ul className="space-y-1.5">
        {data.funnel.map((f) => (
          <li key={f.stage} className="flex items-center gap-3">
            <span className="w-24 shrink-0 text-sm text-gray-700">{stageOf(f.stage).label}</span>
            <span className="relative flex-1 h-5 bg-gray-50 rounded">
              <span className="absolute inset-y-0 left-0 rounded bg-sworkr-400" style={{ width: `${(f.count / top) * 100}%` }} />
            </span>
            <span className="w-10 text-right text-sm font-semibold text-gray-800">{f.count}</span>
          </li>
        ))}
      </ul>
      <p className="text-xs text-gray-400">Each bar is how many got at least that far. A big drop between two bars is where to look.</p>
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">Where they came from</h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500 border-b border-gray-200">
                <th className="py-1 pr-2 font-medium">Found you via</th>
                <th className="py-1 px-1 font-medium text-right">Inquiries</th>
                <th className="py-1 px-1 font-medium text-right">Booked</th>
                <th className="py-1 px-1 font-medium text-right">Rate</th>
              </tr>
            </thead>
            <tbody>
              {data.sources.map((s) => (
                <tr key={s.key} className="border-b border-gray-50">
                  <td className={`py-1 pr-2 ${s.key === 'none' ? 'text-gray-400' : 'text-gray-800'}`}>{s.label}</td>
                  <td className="py-1 px-1 text-right text-gray-600">{s.inquiries}</td>
                  <td className="py-1 px-1 text-right text-gray-600">{s.booked}</td>
                  <td className="py-1 px-1 text-right font-semibold text-gray-800">{Math.round(s.rate * 100)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data.lost_reasons.length > 0 && (
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">Why they were lost</h3>
            <ul className="text-sm divide-y divide-gray-50">
              {data.lost_reasons.map((r) => (
                <li key={r.reason} className="py-1 flex justify-between gap-2"><span className="text-gray-700">{r.reason}</span><span className="text-gray-600">{r.count}</span></li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

function InquiryForm({ inquiry, onDone }) {
  const received = inquiry.received_at ? new Date(inquiry.received_at) : new Date();
  const wanted = inquiry.wanted_date ? new Date(inquiry.wanted_date) : null;
  const [form, setForm] = useState({
    name: inquiry.name || '', contact: inquiry.contact || '', found_via: inquiry.found_via || '',
    received: toDateInput(received), wanted: inquiry.wanted || '',
    wanted_day: wanted ? toDateInput(wanted) : '', wanted_time: wanted ? toTimeInput(wanted) : '19:00',
    stage: inquiry.stage || 'new', lost_reason: inquiry.lost_reason || '', notes: inquiry.notes || '',
  });
  const [used, setUsed] = useState([]);
  const [snippets] = useSnippets();
  const [copied, setCopied] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    axios.get('/api/marketing/found-via/options').then(({ data }) => setUsed(data)).catch(() => {});
  }, []);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const copy = async (s) => {
    try {
      await navigator.clipboard.writeText(s.body);
      setCopied(s.id);
      setTimeout(() => setCopied(null), 1500);
    } catch { /* clipboard blocked */ }
  };
  const submit = async (e) => {
    e.preventDefault();
    const body = {
      name: form.name, contact: form.contact, found_via: form.found_via,
      received_at: form.received === toDateInput(received) ? received.toISOString() : fromDateTimeInputs(form.received, '12:00').toISOString(),
      wanted: form.wanted, wanted_date: form.wanted_day ? fromDateTimeInputs(form.wanted_day, form.wanted_time || '19:00').toISOString() : null,
      stage: form.stage, lost_reason: form.lost_reason, notes: form.notes, client_id: inquiry.client_id || null,
    };
    try {
      if (inquiry.id) await axios.put(`/api/inquiries/${inquiry.id}`, body);
      else await axios.post('/api/inquiries', body);
      onDone();
    } catch (err) {
      setError(errorMessage(err, 'Could not save the inquiry'));
    }
  };
  const remove = async () => {
    if (!window.confirm('Delete this inquiry?')) return;
    await axios.delete(`/api/inquiries/${inquiry.id}`).catch(() => {});
    onDone();
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Field label="Who *"><input required autoFocus value={form.name} onChange={set('name')} placeholder="A name or a handle" className={inputClass} /></Field>
        <Field label="How to reach them"><input value={form.contact} onChange={set('contact')} placeholder="Number, email or @handle" className={inputClass} /></Field>
        <Field label="How they found you">
          <input list="inquiry-found-via" value={form.found_via} onChange={set('found_via')} placeholder="e.g. Tryst, X, a referral" className={inputClass} />
          <datalist id="inquiry-found-via">{used.map((x) => <option key={x} value={x} />)}</datalist>
        </Field>
        <Field label="Got in touch on"><input type="date" value={form.received} onChange={set('received')} className={inputClass} /></Field>
      </div>
      <Field label="What they asked for"><textarea rows={2} value={form.wanted} onChange={set('wanted')} placeholder="e.g. 2 hours, dinner, Friday evening" className={inputClass} /></Field>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <Field label="For which day"><input type="date" value={form.wanted_day} onChange={set('wanted_day')} className={inputClass} /></Field>
        <Field label="Time"><input type="time" value={form.wanted_time} onChange={set('wanted_time')} disabled={!form.wanted_day} className={inputClass} /></Field>
        <Field label="Stage">
          <select value={form.stage} onChange={set('stage')} className={inputClass}>
            {[...STAGES, LOST].map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
        </Field>
      </div>
      {form.stage === 'lost' && (
        <Field label="Why it was lost">
          <input list="lost-reasons" value={form.lost_reason} onChange={set('lost_reason')} className={inputClass} />
          <datalist id="lost-reasons">{LOST_REASONS.map((x) => <option key={x} value={x} />)}</datalist>
        </Field>
      )}
      <Field label="Notes"><textarea rows={2} value={form.notes} onChange={set('notes')} className={inputClass} /></Field>
      {snippets.length > 0 && (
        <p className="flex flex-wrap items-center gap-1">
          <span className="text-xs text-gray-400">Copy a reply:</span>
          {snippets.map((s) => (
            <button key={s.id} type="button" title={s.body} onClick={() => copy(s)} className="text-xs px-2 py-0.5 rounded-full border border-gray-200 text-gray-600 hover:bg-gray-50">
              {copied === s.id ? 'Copied ✓' : s.label}
            </button>
          ))}
        </p>
      )}
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex items-center justify-between">
        {inquiry.id ? <button type="button" onClick={remove} className="text-sm text-red-500 hover:text-red-700">Delete inquiry</button> : <span />}
        <button type="submit" className={buttonClass}>{inquiry.id ? 'Save changes' : 'Save inquiry'}</button>
      </div>
    </form>
  );
}

/** Gone quiet: regulars who haven't booked for a while and have nothing booked ahead. */
export function GoneQuiet() {
  const [days, setDays] = useState(60);
  const [rows, setRows] = useState(null);
  const [snippets] = useSnippets();
  const [copied, setCopied] = useState(null);
  useEffect(() => {
    setRows(null);
    axios.get('/api/marketing/lapsed', { params: { days } }).then(({ data }) => setRows(data)).catch(() => setRows([]));
  }, [days]);
  const copy = async (key, text) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
      setTimeout(() => setCopied(null), 1500);
    } catch { /* clipboard blocked */ }
  };
  const gap = (n) => (n >= 60 ? `about every ${Math.round(n / 30)} months` : n >= 14 ? `about every ${Math.round(n / 7)} weeks` : `about every ${n} day${n === 1 ? '' : 's'}`);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold text-white">Contacts</h1>
        <PeopleNav />
      </div>
      <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
          <p className="text-sm text-gray-600 max-w-xl">
            Clients you've seen at least twice who haven't booked lately and have nothing booked ahead. The ones who've paid you the most come first.
          </p>
          <label className="flex items-center gap-2 text-sm text-gray-600">
            Not seen for
            <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="rounded-lg border border-gray-200 px-2 py-1.5 bg-white">
              {[[30, '30 days'], [60, '60 days'], [90, '90 days'], [180, '6 months'], [365, 'a year']].map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
        </div>
        {snippets.length === 0 && rows?.length > 0 && (
          <p className="text-xs text-gray-400 mb-2">Tip: save a "checking in" message under <Link to="/content/toolkit" className="underline">Content → Promote → Platforms & saved text</Link> and it appears here to copy.</p>
        )}
        {!rows ? null : rows.length === 0 ? (
          <p className="text-sm text-gray-400 py-8 text-center">Nobody has gone quiet. Regulars show up here once they've been away this long.</p>
        ) : (
          <ul className="divide-y divide-gray-100">
            {rows.map((c) => (
              <li key={c.id} className="py-2.5 flex flex-wrap items-start gap-x-3 gap-y-1">
                <Link to={`/contacts/${c.id}`} className="flex-1 min-w-48">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-gray-800">{c.display_name}</span>
                    {c.days_since > c.usual_gap_days * 2 && <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-100 text-amber-800">well overdue</span>}
                    {c.found_via && <span className="text-xs text-gray-500">via {c.found_via}</span>}
                  </span>
                  <span className="block text-xs text-gray-500">
                    Last seen {shortDay(c.last_seen)} ({c.days_since} days ago) · used to book {gap(c.usual_gap_days)}
                  </span>
                  <span className="block text-xs text-gray-500">{c.bookings} bookings · {money(c.total_paid)} in total · {money(c.per_booking)} a time</span>
                </Link>
                <span className="flex flex-wrap gap-2 shrink-0">
                  {(c.contact_phone || c.email) && (
                    <button onClick={() => copy(`c${c.id}`, c.contact_phone || c.email)} className={quietButtonClass}>{copied === `c${c.id}` ? 'Copied ✓' : `Copy ${c.contact_phone ? 'number' : 'email'}`}</button>
                  )}
                  {snippets.slice(0, 3).map((s) => (
                    <button key={s.id} title={s.body} onClick={() => copy(`s${c.id}-${s.id}`, s.body)} className={quietButtonClass}>{copied === `s${c.id}-${s.id}` ? 'Copied ✓' : `Copy "${s.label}"`}</button>
                  ))}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/** On the dashboard: inquiries nobody has answered yet. */
export function InquiriesWaiting() {
  const [rows, setRows] = useState([]);
  useEffect(() => {
    axios.get('/api/inquiries', { params: { show: 'open' } }).then(({ data }) => setRows(data.filter((e) => e.stage === 'new'))).catch(() => {});
  }, []);
  if (rows.length === 0) return null;
  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-5">
      <div className="flex items-center justify-between mb-1">
        <h2 className="font-semibold text-gray-800">Inquiries to answer</h2>
        <Link to="/contacts/inquiries" className="text-sm text-sworkr-600 hover:text-sworkr-800">All inquiries →</Link>
      </div>
      <ul className="divide-y divide-gray-100">
        {rows.slice(0, 5).map((e) => (
          <li key={e.id} className="py-2">
            <Link to="/contacts/inquiries" className="block">
              <span className="font-medium text-gray-800">{e.name}</span>
              <span className="text-xs text-gray-500"> · {shortDay(e.received_at)}{e.found_via ? ` · via ${e.found_via}` : ''}</span>
              {e.wanted && <span className="block text-sm text-gray-600 line-clamp-1">{e.wanted}</span>}
            </Link>
          </li>
        ))}
      </ul>
      {rows.length > 5 && <p className="text-xs text-gray-400 mt-1">and {rows.length - 5} more</p>}
    </div>
  );
}
