import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import Modal, { Field, inputClass, errorMessage, buttonClass, quietButtonClass } from './Modal';
import { PersonaSelect } from './Personas';
import { dayLabel, fromDateInput, money, toDateInput } from '../colors';

const STATE = {
  expired: { label: 'Expired', badge: 'bg-red-100 text-red-700' },
  soon: { label: 'Expiring soon', badge: 'bg-amber-100 text-amber-800' },
  live: { label: 'Live', badge: 'bg-emerald-100 text-emerald-700' },
  paused: { label: 'Paused', badge: 'bg-gray-100 text-gray-500' },
};
const shortDay = (value) => dayLabel(fromDateInput(value), { weekday: 'short', month: 'short', day: 'numeric' });
const leftText = (l) => (l.days_left == null ? 'No end date' : l.days_left < 0 ? `Expired ${-l.days_left} day${l.days_left === -1 ? '' : 's'} ago`
  : l.days_left === 0 ? 'Expires today' : `${l.days_left} day${l.days_left === 1 ? '' : 's'} left (until ${shortDay(l.end_date)})`);
const adName = (l) => [l.site, l.title || l.city].filter(Boolean).join(' · ');

/** Content → Ads: every listing, the ones that need attention first. */
export default function Listings({ sites }) {
  const [data, setData] = useState(null);
  const [modal, setModal] = useState(null); // { edit } | { renew }
  const [copied, setCopied] = useState(null);
  const load = useCallback(() => axios.get('/api/listings').then(({ data: d }) => setData(d)).catch(() => setData({ listings: [] })), []);
  useEffect(() => { load(); }, [load]);
  const done = () => { setModal(null); load(); };
  const copy = async (l) => {
    try {
      await navigator.clipboard.writeText(l.ad_text || '');
      setCopied(l.id);
      setTimeout(() => setCopied(null), 1500);
    } catch { /* clipboard blocked */ }
  };

  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
        <h2 className="font-semibold text-gray-800">Ads</h2>
        <button onClick={() => setModal({ edit: {} })} className="px-4 py-2 rounded-full text-sm font-medium bg-sworkr-500 text-white hover:bg-sworkr-600">+ New ad</button>
      </div>
      <p className="text-xs text-gray-500 mb-3">
        Your listings on ad sites and directories: when each one runs out and what it costs. Renewing one here moves its date on and
        adds the cost to your expenses. Money → Compare → By how they found you then shows it against what that site's clients paid.
      </p>
      {data?.per_month > 0 && (
        <p className="text-sm text-gray-700 mb-3">
          Your running ads cost about <b>{money(data.per_month)}</b> a month.
          {data.need_attention > 0 && <span className="text-red-600"> {data.need_attention} need{data.need_attention === 1 ? 's' : ''} attention.</span>}
        </p>
      )}
      {!data ? null : data.listings.length === 0 ? (
        <p className="text-sm text-gray-400 py-8 text-center">No ads yet. Add each listing you pay for, and sworkr will tell you before it runs out.</p>
      ) : (
        <ul className="divide-y divide-gray-100">
          {data.listings.map((l) => (
            <li key={l.id} className={`py-3 flex flex-wrap items-start gap-x-3 gap-y-1 ${l.state === 'paused' ? 'opacity-60' : ''}`}>
              <button onClick={() => setModal({ edit: l })} className="flex-1 min-w-48 text-left">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-gray-800">{adName(l)}</span>
                  <span className={`text-[10px] px-2 py-0.5 rounded-full ${STATE[l.state].badge}`}>{STATE[l.state].label}</span>
                  {l.tour_name && <span className="text-xs text-gray-500">Tour: {l.tour_name}</span>}
                </span>
                <span className={`block text-xs ${l.state === 'expired' ? 'text-red-600' : 'text-gray-500'}`}>{leftText(l)}</span>
                <span className="block text-xs text-gray-500">
                  {[l.cost != null && l.renew_days ? `${money(l.cost)} every ${l.renew_days} days` : l.cost != null ? money(l.cost) : null,
                    l.per_month != null && `${money(l.per_month)} a month`, l.payments > 0 && `${money(l.spent)} spent so far`].filter(Boolean).join(' · ')}
                </span>
              </button>
              <span className="flex flex-wrap gap-2 shrink-0">
                {l.ad_text && <button onClick={() => copy(l)} className={quietButtonClass}>{copied === l.id ? 'Copied ✓' : 'Copy ad text'}</button>}
                {l.link && <a href={l.link} target="_blank" rel="noreferrer noopener" className={quietButtonClass}>Open ↗</a>}
                <button onClick={() => setModal({ renew: l })} className="text-xs px-2.5 py-1.5 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700">Renewed</button>
              </span>
            </li>
          ))}
        </ul>
      )}
      {modal?.edit && (
        <Modal title={modal.edit.id ? 'Edit ad' : 'New ad'} onClose={() => setModal(null)} wide>
          <ListingForm listing={modal.edit} sites={sites} onDone={done} />
        </Modal>
      )}
      {modal?.renew && (
        <Modal title={`Renewed: ${adName(modal.renew)}`} onClose={() => setModal(null)}>
          <RenewForm listing={modal.renew} onDone={done} />
        </Modal>
      )}
    </div>
  );
}

function RenewForm({ listing, onDone }) {
  const [form, setForm] = useState({ cost: listing.cost ?? '', days: listing.renew_days ?? '', paid_on: toDateInput(new Date()), log_expense: true });
  const [error, setError] = useState('');
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    try {
      await axios.post(`/api/listings/${listing.id}/renew`, {
        cost: form.cost === '' ? null : Number(form.cost), days: form.days === '' ? null : Number(form.days),
        paid_on: form.paid_on || null, log_expense: form.log_expense,
      });
      onDone();
    } catch (err) {
      setError(errorMessage(err, 'Could not save the renewal'));
    }
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      <p className="text-sm text-gray-600">Do this after you've paid on the site. sworkr moves the end date on and logs the cost.</p>
      <div className="grid grid-cols-3 gap-3">
        <Field label="Cost ($)"><input type="number" min="0" step="0.01" inputMode="decimal" value={form.cost} onChange={set('cost')} className={inputClass} /></Field>
        <Field label="For how many days *"><input required type="number" min="1" max="3650" value={form.days} onChange={set('days')} className={inputClass} /></Field>
        <Field label="Paid on"><input type="date" value={form.paid_on} onChange={set('paid_on')} className={inputClass} /></Field>
      </div>
      <label className="flex items-center gap-2 text-sm text-gray-700">
        <input type="checkbox" checked={form.log_expense} onChange={set('log_expense')} /> Add the cost to my expenses (Marketing)
      </label>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex justify-end"><button type="submit" className={buttonClass}>Save renewal</button></div>
    </form>
  );
}

function ListingForm({ listing, sites, onDone }) {
  const [form, setForm] = useState({
    site: listing.site || '', title: listing.title || '', city: listing.city || '', start_date: listing.start_date || '',
    end_date: listing.end_date || '', cost: listing.cost ?? '', renew_days: listing.renew_days ?? '', ad_text: listing.ad_text || '',
    link: listing.link || '', paused: !!listing.paused, notes: listing.notes || '',
    tour_id: listing.tour_id ? String(listing.tour_id) : '', persona_id: listing.persona_id ? String(listing.persona_id) : '',
  });
  const [tours, setTours] = useState([]);
  const [error, setError] = useState('');
  useEffect(() => {
    axios.get('/api/tours').then(({ data }) => setTours(data.filter((t) => t.kind === 'tour'))).catch(() => {});
  }, []);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    const body = {
      ...form, start_date: form.start_date || null, end_date: form.end_date || null,
      cost: form.cost === '' ? null : Number(form.cost), renew_days: form.renew_days === '' ? null : Number(form.renew_days),
      link: form.link.trim() || null, tour_id: form.tour_id ? Number(form.tour_id) : null,
      persona_id: form.persona_id ? Number(form.persona_id) : null,
    };
    try {
      if (listing.id) await axios.put(`/api/listings/${listing.id}`, body);
      else await axios.post('/api/listings', body);
      onDone();
    } catch (err) {
      setError(errorMessage(err, 'Could not save the ad'));
    }
  };
  const remove = async () => {
    if (!window.confirm('Delete this ad? What you spent on it stays in your expenses.')) return;
    await axios.delete(`/api/listings/${listing.id}`).catch(() => {});
    onDone();
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <Field label="Site *">
          <input required autoFocus list="listing-sites" value={form.site} onChange={set('site')} placeholder="e.g. Tryst" className={inputClass} />
          <datalist id="listing-sites">{sites.map((s) => <option key={s} value={s} />)}</datalist>
        </Field>
        <Field label="Which ad (optional)"><input value={form.title} onChange={set('title')} placeholder="If you have several" className={inputClass} /></Field>
        <Field label="City"><input value={form.city} onChange={set('city')} className={inputClass} /></Field>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Field label="Started"><input type="date" value={form.start_date} onChange={set('start_date')} className={inputClass} /></Field>
        <Field label="Runs out on"><input type="date" value={form.end_date} onChange={set('end_date')} className={inputClass} /></Field>
        <Field label="Cost per renewal ($)"><input type="number" min="0" step="0.01" inputMode="decimal" value={form.cost} onChange={set('cost')} className={inputClass} /></Field>
        <Field label="A renewal lasts (days)"><input type="number" min="1" max="3650" value={form.renew_days} onChange={set('renew_days')} placeholder="e.g. 30" className={inputClass} /></Field>
      </div>
      <Field label={`Ad text (${form.ad_text.length} characters)`}>
        <textarea rows={5} value={form.ad_text} onChange={set('ad_text')} placeholder="Keep the current wording here, ready to copy when you renew or repost" className={inputClass} />
      </Field>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <Field label="Link to the ad"><input value={form.link} onChange={set('link')} placeholder="https://…" className={inputClass} /></Field>
        {tours.length > 0 && (
          <Field label="For a tour">
            <select value={form.tour_id} onChange={set('tour_id')} className={inputClass}>
              <option value="">Not for a tour</option>
              {tours.map((t) => <option key={t.id} value={t.id}>{t.name || t.location || 'Tour'}</option>)}
            </select>
          </Field>
        )}
        <PersonaSelect value={form.persona_id} onChange={set('persona_id')} label="Persona" />
      </div>
      <Field label="Notes"><textarea rows={2} value={form.notes} onChange={set('notes')} placeholder="Login reminder (not the password), photo rules, what worked" className={inputClass} /></Field>
      <label className="flex items-center gap-2 text-sm text-gray-700">
        <input type="checkbox" checked={form.paused} onChange={set('paused')} /> Paused (not running, don't remind me)
      </label>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex items-center justify-between">
        {listing.id ? <button type="button" onClick={remove} className="text-sm text-red-500 hover:text-red-700">Delete ad</button> : <span />}
        <button type="submit" className={buttonClass}>{listing.id ? 'Save changes' : 'Save ad'}</button>
      </div>
    </form>
  );
}

/** On the dashboard: ads that have run out or are about to. */
export function AdsExpiring() {
  const [rows, setRows] = useState([]);
  useEffect(() => {
    axios.get('/api/listings').then(({ data }) => setRows(data.listings.filter((l) => l.state === 'expired' || l.state === 'soon'))).catch(() => {});
  }, []);
  if (rows.length === 0) return null;
  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-5">
      <div className="flex items-center justify-between mb-1">
        <h2 className="font-semibold text-gray-800">Ads running out</h2>
        <Link to="/content/ads" className="text-sm text-sworkr-600 hover:text-sworkr-800">Ads →</Link>
      </div>
      <ul className="divide-y divide-gray-100">
        {rows.map((l) => (
          <li key={l.id} className="py-2">
            <Link to="/content/ads" className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium text-gray-800">{adName(l)}</span>
              <span className={`text-xs ${l.state === 'expired' ? 'text-red-600' : 'text-amber-700'}`}>{leftText(l)}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
