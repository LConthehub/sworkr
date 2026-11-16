import { useCallback, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import axios from 'axios';
import Modal, { Field, inputClass, errorMessage, buttonClass, quietButtonClass } from './Modal';
import { PersonaSelect } from './Personas';
import { useCampaigns } from './Promo';
import { fetchAll } from '../api';
import { dayLabel, fromDateInput, money } from '../colors';

const STATUS = {
  idea: { label: 'Idea', badge: 'bg-gray-100 text-gray-600' },
  planning: { label: 'Planning', badge: 'bg-amber-100 text-amber-800' },
  booked: { label: 'Booked', badge: 'bg-sky-100 text-sky-700' },
  shot: { label: 'Shot', badge: 'bg-violet-100 text-violet-700' },
  editing: { label: 'Editing', badge: 'bg-sworkr-50 text-sworkr-600' },
  released: { label: 'Released', badge: 'bg-emerald-100 text-emerald-700' },
  cancelled: { label: 'Cancelled', badge: 'bg-gray-100 text-gray-400 line-through' },
};
const ROLES = { photographer: 'Photographer', videographer: 'Videographer', 'co-star': 'Co-star', makeup: 'Hair & makeup', assistant: 'Assistant', other: 'Other' };
// Each list on a shoot: its heading, what to type, and what ticking it means.
const LISTS = [
  { kind: 'goal', title: 'Goals', hint: 'What this shoot has to produce.', placeholder: 'e.g. 3 pay-per-view sets, 10 teasers, a trailer', tick: 'Got it' },
  { kind: 'shot', title: 'Shot list', hint: 'The looks, poses and scenes to get.', placeholder: 'e.g. On the bed, red lace, 20 photos', tick: 'Shot' },
  { kind: 'wardrobe', title: 'Wardrobe & props', hint: 'Tick each one as you pack it.', placeholder: 'e.g. Red lace set, heels, ring light', tick: 'Packed' },
  { kind: 'prep', title: 'To prepare', hint: 'Everything to sort out before the day.', placeholder: 'e.g. Book the studio, send the release', tick: 'Done', dated: true },
  { kind: 'marketing', title: 'Marketing plan', hint: 'How and when it goes out.', placeholder: 'e.g. Teaser on X the day before', tick: 'Done', dated: true },
];
const shortDay = (value) => dayLabel(fromDateInput(value), { weekday: 'short', month: 'short', day: 'numeric' });
const whenText = (s) => (!s.shoot_date ? 'No date yet' : `${shortDay(s.shoot_date)}${s.start_time ? `, ${s.start_time}` : ''}${s.hours ? ` · ${s.hours} h` : ''}`);
const countdown = (n) => (n == null ? '' : n < 0 ? `${-n} day${n === -1 ? '' : 's'} ago` : n === 0 ? 'today' : n === 1 ? 'tomorrow' : `in ${n} days`);

/** Content → Shoots: every shoot, or one shoot's whole plan. */
export default function Shoots() {
  const [search, setSearch] = useSearchParams();
  const openId = search.get('shoot');
  return openId ? <ShootPlan id={openId} onBack={() => setSearch({})} onOpen={(id) => setSearch({ shoot: id })} />
    : <ShootList onOpen={(id) => setSearch({ shoot: id })} />;
}

function ShootList({ onOpen }) {
  const [show, setShow] = useState('ahead');
  const [shoots, setShoots] = useState(null);
  const [adding, setAdding] = useState(false);
  const load = useCallback(() => axios.get('/api/shoots', { params: { show } }).then(({ data }) => setShoots(data)).catch(() => setShoots([])), [show]);
  useEffect(() => { load(); }, [load]);
  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <div className="inline-flex rounded-lg border border-gray-200 overflow-hidden text-sm" role="group" aria-label="Show">
          {[['ahead', 'Coming up'], ['done', 'Shot'], ['all', 'All']].map(([id, label]) => (
            <button key={id} onClick={() => setShow(id)} aria-pressed={show === id} className={`px-3 py-1.5 ${show === id ? 'bg-sworkr-500 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}>{label}</button>
          ))}
        </div>
        <button onClick={() => setAdding(true)} className="px-4 py-2 rounded-full text-sm font-medium bg-sworkr-500 text-white hover:bg-sworkr-600">+ Plan a shoot</button>
      </div>
      <p className="text-xs text-gray-500 mb-3">
        Plan a shoot in one place: where, who with, what it has to produce, what to wear and bring, what it costs, and how it goes out afterwards.
      </p>
      {!shoots ? null : shoots.length === 0 ? (
        <p className="text-sm text-gray-400 py-8 text-center">{show === 'ahead' ? 'No shoots planned. Start with an idea and fill it in as it firms up.' : 'Nothing here yet.'}</p>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {shoots.map((s) => {
            const c = s.summary.counts;
            return (
              <li key={s.id}>
                <button onClick={() => onOpen(s.id)} className="w-full text-left rounded-xl border border-gray-100 p-4 hover:shadow-sm hover:border-sworkr-200">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-gray-800">{s.title}</span>
                    <span className={`text-[10px] px-2 py-0.5 rounded-full ${STATUS[s.status].badge}`}>{STATUS[s.status].label}</span>
                  </span>
                  <span className="block text-xs text-gray-500">
                    {whenText(s)}{s.summary.days_left != null && ['idea', 'planning', 'booked'].includes(s.status) && ` (${countdown(s.summary.days_left)})`}
                    {s.location_name && ` · ${s.location_name}`}
                  </span>
                  <span className="block text-xs text-gray-500 mt-1">
                    {[s.summary.people > 0 && `${s.summary.people} ${s.summary.people === 1 ? 'person' : 'people'}`,
                      c.goal.total > 0 && `${c.goal.total} goal${c.goal.total === 1 ? '' : 's'}`,
                      c.prep.total > 0 && `prep ${c.prep.done}/${c.prep.total}`,
                      c.wardrobe.total > 0 && `packed ${c.wardrobe.done}/${c.wardrobe.total}`,
                      s.summary.planned > 0 && `budget ${money(s.summary.planned)}`, s.summary.spent > 0 && `spent ${money(s.summary.spent)}`].filter(Boolean).join(' · ') || 'Nothing planned yet'}
                  </span>
                  {s.summary.warnings.length > 0 && <span className="block text-xs text-amber-700 mt-1">{s.summary.warnings.join(' · ')}</span>}
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {adding && (
        <Modal title="Plan a shoot" onClose={() => setAdding(false)} wide>
          <ShootForm shoot={{}} onDone={(saved) => { setAdding(false); if (saved) onOpen(saved.id); }} />
        </Modal>
      )}
    </div>
  );
}

function ShootPlan({ id, onBack, onOpen }) {
  const [shoot, setShoot] = useState(null);
  const [error, setError] = useState('');
  const [modal, setModal] = useState(null); // 'edit' | { person } | { pay }
  const load = useCallback(() => axios.get(`/api/shoots/${id}`).then(({ data }) => setShoot(data)).catch((err) => setError(errorMessage(err, "Couldn't open this shoot."))), [id]);
  useEffect(() => { setShoot(null); load(); }, [load]);
  // Every change answers with the whole shoot, so the page is always what's saved.
  const run = async (request) => {
    try {
      const { data } = await request;
      if (data?.id) setShoot(data);
      setError('');
      return data;
    } catch (err) {
      setError(errorMessage(err, 'Could not save'));
      return null;
    }
  };

  if (!shoot) {
    return (
      <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
        <button onClick={onBack} className="text-sm text-sworkr-600 hover:text-sworkr-800">← All shoots</button>
        {error && <p className="text-sm text-red-600 mt-2">{error}</p>}
      </div>
    );
  }
  const s = shoot.summary;
  const budget = shoot.items.filter((i) => i.kind === 'budget');
  const copy = async () => { const made = await run(axios.post(`/api/shoots/${shoot.id}/copy`)); if (made) onOpen(made.id); };

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
        <button onClick={onBack} className="text-sm text-sworkr-600 hover:text-sworkr-800">← All shoots</button>
        <div className="flex flex-wrap items-start justify-between gap-3 mt-2">
          <div className="min-w-0">
            <h2 className="text-xl font-bold text-gray-800 break-words">{shoot.title}</h2>
            <p className="text-sm text-gray-600">
              {whenText(shoot)}{s.days_left != null && ['idea', 'planning', 'booked'].includes(shoot.status) && ` (${countdown(s.days_left)})`}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select value={shoot.status} aria-label="Status" onChange={(e) => run(axios.put(`/api/shoots/${shoot.id}`, { ...shoot, status: e.target.value }))}
              className="rounded-lg border border-gray-200 px-2 py-1.5 text-sm bg-white">
              {Object.entries(STATUS).map(([v, x]) => <option key={v} value={v}>{x.label}</option>)}
            </select>
            <button onClick={() => setModal('edit')} className={buttonClass}>Edit</button>
            <button onClick={copy} className={quietButtonClass} title="A new shoot with the same place, people and lists">Copy</button>
          </div>
        </div>
        {s.warnings.length > 0 && (
          <ul className="mt-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 list-disc pl-7">
            {s.warnings.map((w) => <li key={w}>{w}</li>)}
          </ul>
        )}
        {error && <p className="text-sm text-red-600 mt-2">{error}</p>}
        <div className="grid gap-4 sm:grid-cols-2 mt-4 text-sm">
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">Where</h3>
            {shoot.location_name || shoot.location_address ? (
              <>
                <p className="text-gray-800">{shoot.location_name}</p>
                {shoot.location_address && <p className="text-gray-600">{shoot.location_address}</p>}
                {shoot.location_notes && <p className="text-gray-600 whitespace-pre-wrap mt-1">{shoot.location_notes}</p>}
              </>
            ) : <p className="text-gray-400">Not decided yet.</p>}
          </div>
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">The idea</h3>
            {shoot.concept ? <p className="text-gray-700 whitespace-pre-wrap">{shoot.concept}</p> : <p className="text-gray-400">No concept written yet.</p>}
            <p className="text-xs text-gray-500 mt-1">
              {[shoot.tour_name && `Tour: ${shoot.tour_name}`, shoot.set_path && `Library folder: ${shoot.set_path}`].filter(Boolean).join(' · ')}
            </p>
          </div>
        </div>
        {shoot.notes && <p className="text-sm text-gray-600 whitespace-pre-wrap mt-3">{shoot.notes}</p>}
      </div>

      <div className="grid gap-4 lg:grid-cols-2 items-start">
        <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
          <div className="flex items-center justify-between gap-3 mb-1">
            <h3 className="font-semibold text-gray-800">People</h3>
            <button onClick={() => setModal({ person: {} })} className={quietButtonClass}>+ Add someone</button>
          </div>
          <p className="text-xs text-gray-500 mb-2">Photographer, co-stars, makeup, a driver. Keep what you agreed about the content with each of them.</p>
          {shoot.people.length === 0 ? <p className="text-sm text-gray-400 py-2">Just you so far.</p> : (
            <ul className="divide-y divide-gray-100">
              {shoot.people.map((p) => (
                <li key={p.id} className="py-2 flex flex-wrap items-start gap-x-3 gap-y-1">
                  <button onClick={() => setModal({ person: p })} className="flex-1 min-w-40 text-left">
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-gray-800">{p.display_name}</span>
                      <span className="text-xs text-gray-500">{ROLES[p.role] || p.role}</span>
                      <span className={`text-[10px] px-2 py-0.5 rounded-full ${p.confirmed ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-800'}`}>{p.confirmed ? 'Confirmed' : 'Not confirmed'}</span>
                      {p.role === 'co-star' && <span className={`text-[10px] px-2 py-0.5 rounded-full ${p.id_checked && p.release_signed ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'}`}>{p.id_checked && p.release_signed ? 'Paperwork done' : 'Paperwork needed'}</span>}
                    </span>
                    {p.agreement && <span className="block text-sm text-gray-600 whitespace-pre-wrap">{p.agreement}</span>}
                    {p.fee != null && <span className="block text-xs text-gray-500">Fee {money(p.fee)}{p.expense_id ? ' · paid' : ''}</span>}
                  </button>
                  <span className="flex gap-2 shrink-0">
                    {p.contact_id && <Link to={`/contacts/${p.contact_id}`} className={quietButtonClass}>Contact →</Link>}
                    {p.fee > 0 && !p.expense_id && <button onClick={() => setModal({ pay: { person: p } })} className="text-xs px-2.5 py-1.5 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700">Paid</button>}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
          <h3 className="font-semibold text-gray-800 mb-1">Budget</h3>
          <p className="text-xs text-gray-500 mb-2">
            Planned <b>{money(s.planned)}</b> (with people's fees) · spent <b>{money(s.spent)}</b> ·{' '}
            <span className={s.left_to_spend < 0 ? 'text-red-600' : ''}>{s.left_to_spend < 0 ? `${money(-s.left_to_spend)} over` : `${money(s.left_to_spend)} left`}</span>
          </p>
          <ul className="divide-y divide-gray-100">
            {budget.map((i) => (
              <li key={i.id} className="py-2 flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="flex-1 min-w-32 text-sm text-gray-800">{i.label}</span>
                <span className="text-sm text-gray-600">{i.amount != null ? money(i.amount) : '—'}{i.actual != null && i.actual !== i.amount ? ` → ${money(i.actual)}` : ''}</span>
                {i.expense_id ? <span className="text-xs text-emerald-700">Paid</span>
                  : <button onClick={() => setModal({ pay: { item: i } })} className="text-xs px-2.5 py-1.5 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700">Paid</button>}
                <button onClick={() => run(axios.delete(`/api/shoots/items/${i.id}`))} className="text-gray-300 hover:text-red-500 text-sm" aria-label={`Remove ${i.label}`}>✕</button>
              </li>
            ))}
          </ul>
          <AddLine placeholder="e.g. Studio hire, lingerie, travel" withAmount onAdd={(label, amount) => run(axios.post(`/api/shoots/${shoot.id}/items`, { kind: 'budget', label, amount }))} />
          <p className="text-xs text-gray-400 mt-1">"Paid" adds it to your expenses, so the shoot knows what it really cost.</p>
        </div>

        {LISTS.map((list) => (
          <div key={list.kind} className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
            <div className="flex items-center justify-between gap-3 mb-1">
              <h3 className="font-semibold text-gray-800">{list.title}</h3>
              {list.kind === 'marketing' && (shoot.campaign_id
                ? <Link to={`/content/planner?campaign=${shoot.campaign_id}`} className={quietButtonClass}>Its posts →</Link>
                : <button onClick={() => run(axios.post(`/api/shoots/${shoot.id}/campaign`))} className={quietButtonClass}>Start a campaign for it</button>)}
            </div>
            <p className="text-xs text-gray-500 mb-2">{list.hint}</p>
            <ul className="space-y-1">
              {shoot.items.filter((i) => i.kind === list.kind).map((i) => (
                <li key={i.id} className="flex items-start gap-2">
                  <input type="checkbox" checked={i.done} aria-label={`${list.tick}: ${i.label}`} className="mt-1"
                    onChange={(e) => run(axios.put(`/api/shoots/items/${i.id}`, { ...i, done: e.target.checked }))} />
                  <span className={`flex-1 text-sm ${i.done ? 'text-gray-400 line-through' : 'text-gray-800'}`}>
                    {i.label}{i.due_date && <span className="text-xs text-gray-500 no-underline"> · by {shortDay(i.due_date)}</span>}
                  </span>
                  <button onClick={() => run(axios.delete(`/api/shoots/items/${i.id}`))} className="text-gray-300 hover:text-red-500 text-sm" aria-label={`Remove ${i.label}`}>✕</button>
                </li>
              ))}
            </ul>
            <AddLine placeholder={list.placeholder} withDate={list.dated} onAdd={(label, _amount, due_date) => run(axios.post(`/api/shoots/${shoot.id}/items`, { kind: list.kind, label, due_date }))} />
          </div>
        ))}
      </div>

      <div className="text-right">
        <button onClick={async () => { if (window.confirm('Delete this shoot and its lists? What you spent stays in your expenses.')) { await axios.delete(`/api/shoots/${shoot.id}`).catch(() => {}); onBack(); } }}
          className="text-sm text-white/90 hover:text-white underline">Delete this shoot</button>
      </div>

      {modal === 'edit' && (
        <Modal title="Edit shoot" onClose={() => setModal(null)} wide>
          <ShootForm shoot={shoot} onDone={(saved) => { setModal(null); if (saved) setShoot(saved); }} />
        </Modal>
      )}
      {modal?.person && (
        <Modal title={modal.person.id ? 'Edit person' : 'Add someone'} onClose={() => setModal(null)}>
          <PersonForm shootId={shoot.id} person={modal.person} onDone={(saved) => { setModal(null); if (saved) setShoot(saved); }} />
        </Modal>
      )}
      {modal?.pay && (
        <Modal title={`Paid: ${modal.pay.item ? modal.pay.item.label : modal.pay.person.display_name}`} onClose={() => setModal(null)}>
          <PayForm pay={modal.pay} onDone={(saved) => { setModal(null); if (saved) setShoot(saved); }} />
        </Modal>
      )}
    </div>
  );
}

/** One line to type into, with Add. */
function AddLine({ placeholder, withAmount, withDate, onAdd }) {
  const [label, setLabel] = useState('');
  const [amount, setAmount] = useState('');
  const [due, setDue] = useState('');
  const submit = (e) => {
    e.preventDefault();
    if (!label.trim()) return;
    onAdd(label.trim(), amount === '' ? null : Number(amount), due || null);
    setLabel(''); setAmount(''); setDue('');
  };
  return (
    <form onSubmit={submit} className="flex flex-wrap gap-2 mt-2">
      <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder={placeholder} aria-label="Add" className={`${inputClass} flex-1 min-w-40`} />
      {withAmount && <input type="number" min="0" step="0.01" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="$" aria-label="Planned cost" className={`${inputClass} !w-24`} />}
      {withDate && <input type="date" value={due} onChange={(e) => setDue(e.target.value)} aria-label="By when" className={`${inputClass} !w-40`} />}
      <button type="submit" className={quietButtonClass}>Add</button>
    </form>
  );
}

function PayForm({ pay, onDone }) {
  const planned = pay.item ? pay.item.amount : pay.person.fee;
  const [amount, setAmount] = useState(planned ?? '');
  const [paidOn, setPaidOn] = useState(new Date().toISOString().slice(0, 10));
  const [error, setError] = useState('');
  const submit = async (e) => {
    e.preventDefault();
    try {
      const url = pay.item ? `/api/shoots/items/${pay.item.id}/pay` : `/api/shoots/people/${pay.person.id}/pay`;
      const { data } = await axios.post(url, { amount: amount === '' ? null : Number(amount), paid_on: paidOn || null });
      onDone(data);
    } catch (err) {
      setError(errorMessage(err, 'Could not save'));
    }
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <Field label="What it cost ($) *"><input required autoFocus type="number" min="0.01" step="0.01" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} className={inputClass} /></Field>
        <Field label="Paid on"><input type="date" value={paidOn} onChange={(e) => setPaidOn(e.target.value)} className={inputClass} /></Field>
      </div>
      <p className="text-xs text-gray-500">This is added to your expenses.</p>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex justify-end"><button type="submit" className={buttonClass}>Save</button></div>
    </form>
  );
}

function PersonForm({ shootId, person, onDone }) {
  const [form, setForm] = useState({
    name: person.name || '', contact_id: person.contact_id ? String(person.contact_id) : '', role: person.role || 'photographer',
    fee: person.fee ?? '', agreement: person.agreement || '', id_checked: !!person.id_checked, release_signed: !!person.release_signed,
    confirmed: !!person.confirmed, notes: person.notes || '',
  });
  const [contacts, setContacts] = useState([]);
  const [error, setError] = useState('');
  useEffect(() => { fetchAll('/api/clients', { sort: 'name' }, 200).then((all) => setContacts(all.filter((c) => c.role !== 'client'))).catch(() => {}); }, []);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    const body = { ...form, contact_id: form.contact_id ? Number(form.contact_id) : null, fee: form.fee === '' ? null : Number(form.fee) };
    try {
      const { data } = person.id ? await axios.put(`/api/shoots/people/${person.id}`, body) : await axios.post(`/api/shoots/${shootId}/people`, body);
      onDone(data);
    } catch (err) {
      setError(errorMessage(err, 'Could not save'));
    }
  };
  const remove = async () => {
    const { data } = await axios.delete(`/api/shoots/people/${person.id}`).catch(() => ({}));
    onDone(data);
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {contacts.length > 0 && (
          <Field label="One of your co-workers or crew">
            <select value={form.contact_id} onChange={set('contact_id')} className={inputClass}>
              <option value="">Someone else</option>
              {contacts.map((c) => <option key={c.id} value={c.id}>{c.display_name}</option>)}
            </select>
          </Field>
        )}
        {!form.contact_id && <Field label="Name *"><input required autoFocus value={form.name} onChange={set('name')} className={inputClass} /></Field>}
        <Field label="Role">
          <select value={form.role} onChange={set('role')} className={inputClass}>
            {Object.entries(ROLES).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </Field>
        <Field label="Fee ($)"><input type="number" min="0" step="0.01" inputMode="decimal" value={form.fee} onChange={set('fee')} placeholder="If you're paying them" className={inputClass} /></Field>
      </div>
      <Field label="What you've agreed about the content">
        <textarea rows={3} value={form.agreement} onChange={set('agreement')} placeholder="Who can post it and where, how sales are split, what's off limits, when it can go out" className={inputClass} />
      </Field>
      <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm text-gray-700">
        <label className="flex items-center gap-2"><input type="checkbox" checked={form.confirmed} onChange={set('confirmed')} /> Confirmed for the day</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={form.id_checked} onChange={set('id_checked')} /> ID checked</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={form.release_signed} onChange={set('release_signed')} /> Release signed</label>
      </div>
      {form.role === 'co-star' && <p className="text-xs text-gray-500">Platforms ask for ID and a signed release for everyone who appears. sworkr reminds you until both are ticked.</p>}
      <Field label="Notes"><textarea rows={2} value={form.notes} onChange={set('notes')} className={inputClass} /></Field>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex items-center justify-between">
        {person.id ? <button type="button" onClick={remove} className="text-sm text-red-500 hover:text-red-700">Remove from shoot</button> : <span />}
        <button type="submit" className={buttonClass}>Save</button>
      </div>
    </form>
  );
}

function ShootForm({ shoot, onDone }) {
  const [form, setForm] = useState({
    title: shoot.title || '', status: shoot.status || 'planning', shoot_date: shoot.shoot_date || '', start_time: shoot.start_time || '',
    hours: shoot.hours ?? '', concept: shoot.concept || '', location_name: shoot.location_name || '', location_address: shoot.location_address || '',
    location_notes: shoot.location_notes || '', set_path: shoot.set_path || '', campaign_id: shoot.campaign_id ? String(shoot.campaign_id) : '',
    tour_id: shoot.tour_id ? String(shoot.tour_id) : '', persona_id: shoot.persona_id ? String(shoot.persona_id) : '', notes: shoot.notes || '',
  });
  const [tours, setTours] = useState([]);
  const [campaigns] = useCampaigns();
  const [error, setError] = useState('');
  useEffect(() => { axios.get('/api/tours').then(({ data }) => setTours(data.filter((t) => t.kind === 'tour'))).catch(() => {}); }, []);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    const body = {
      ...form, shoot_date: form.shoot_date || null, start_time: form.start_time || null, hours: form.hours === '' ? null : Number(form.hours),
      set_path: form.set_path.trim() || null, campaign_id: form.campaign_id ? Number(form.campaign_id) : null,
      tour_id: form.tour_id ? Number(form.tour_id) : null, persona_id: form.persona_id ? Number(form.persona_id) : null,
    };
    try {
      const { data } = shoot.id ? await axios.put(`/api/shoots/${shoot.id}`, body) : await axios.post('/api/shoots', body);
      onDone(data);
    } catch (err) {
      setError(errorMessage(err, 'Could not save the shoot'));
    }
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <span className="sm:col-span-2"><Field label="Name *"><input required autoFocus value={form.title} onChange={set('title')} placeholder="e.g. Red lace boudoir, Beach day with Jade" className={inputClass} /></Field></span>
        <Field label="Status">
          <select value={form.status} onChange={set('status')} className={inputClass}>
            {Object.entries(STATUS).map(([v, x]) => <option key={v} value={v}>{x.label}</option>)}
          </select>
        </Field>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <Field label="Day"><input type="date" value={form.shoot_date} onChange={set('shoot_date')} className={inputClass} /></Field>
        <Field label="Start"><input type="time" value={form.start_time} onChange={set('start_time')} className={inputClass} /></Field>
        <Field label="Hours"><input type="number" min="0.5" max="72" step="0.5" value={form.hours} onChange={set('hours')} className={inputClass} /></Field>
      </div>
      <Field label="The idea"><textarea rows={3} value={form.concept} onChange={set('concept')} placeholder="The look, the mood, the story. Links to reference pictures." className={inputClass} /></Field>
      <fieldset className="rounded-lg border border-gray-200 px-3 pt-2 pb-3 space-y-3">
        <legend className="px-1 text-xs font-medium text-gray-500">Where</legend>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field label="Place"><input value={form.location_name} onChange={set('location_name')} placeholder="e.g. Studio 5, my place, North beach" className={inputClass} /></Field>
          <Field label="Address"><input value={form.location_address} onChange={set('location_address')} className={inputClass} /></Field>
        </div>
        <Field label="Good to know"><textarea rows={2} value={form.location_notes} onChange={set('location_notes')} placeholder="How to get in, parking, the light, what's allowed, who else is around" className={inputClass} /></Field>
      </fieldset>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Field label="Folder in your library"><input value={form.set_path} onChange={set('set_path')} placeholder="Where the pictures will go" className={inputClass} /></Field>
        {campaigns.length > 0 && (
          <Field label="Campaign">
            <select value={form.campaign_id} onChange={set('campaign_id')} className={inputClass}>
              <option value="">None yet</option>
              {campaigns.filter((c) => !c.archived || String(c.id) === form.campaign_id).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
        )}
        {tours.length > 0 && (
          <Field label="During a tour">
            <select value={form.tour_id} onChange={set('tour_id')} className={inputClass}>
              <option value="">Not on a tour</option>
              {tours.map((t) => <option key={t.id} value={t.id}>{t.name || t.location || 'Tour'}</option>)}
            </select>
          </Field>
        )}
        <PersonaSelect value={form.persona_id} onChange={set('persona_id')} label="Persona" />
      </div>
      <Field label="Notes"><textarea rows={2} value={form.notes} onChange={set('notes')} className={inputClass} /></Field>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex justify-end"><button type="submit" className={buttonClass}>{shoot.id ? 'Save changes' : 'Save and plan it'}</button></div>
    </form>
  );
}

/** On the dashboard: shoots in the next week, with what's still to sort out. */
export function ShootsSoon() {
  const [shoots, setShoots] = useState([]);
  useEffect(() => {
    axios.get('/api/shoots').then(({ data }) => setShoots(data.filter((s) => s.summary.days_left != null && s.summary.days_left <= 7))).catch(() => {});
  }, []);
  if (shoots.length === 0) return null;
  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-5">
      <div className="flex items-center justify-between mb-1">
        <h2 className="font-semibold text-gray-800">Shoots coming up</h2>
        <Link to="/content/shoots" className="text-sm text-sworkr-600 hover:text-sworkr-800">Shoots →</Link>
      </div>
      <ul className="divide-y divide-gray-100">
        {shoots.map((s) => (
          <li key={s.id} className="py-2">
            <Link to={`/content/shoots?shoot=${s.id}`} className="block">
              <span className="font-medium text-gray-800">{s.title}</span>
              <span className="text-xs text-gray-500"> · {whenText(s)} ({countdown(s.summary.days_left)})</span>
              {s.summary.warnings.length > 0 && <span className="block text-xs text-amber-700">{s.summary.warnings.join(' · ')}</span>}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
