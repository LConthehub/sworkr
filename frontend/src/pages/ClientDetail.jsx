import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import axios from 'axios';
import Modal, { errorMessage, inputClass, buttonClass, quietButtonClass } from '../components/Modal';
import ClientForm from '../components/ClientForm';
import AppointmentForm from '../components/AppointmentForm';
import { ScreeningBadge } from '../components/ClientCard';
import { AppointmentItem } from './AppointmentCalendar';
import { BadDateWarning } from '../components/Blocklist';
import { colorFor, dayLabel, money, nextBirthday } from '../colors';

const shortDate = (iso) => (iso ? dayLabel(new Date(iso), { month: 'short', day: 'numeric', year: 'numeric' }) : '—');

/** One client: who they are, screening, money, every appointment and dated notes. */
export default function ClientDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [modal, setModal] = useState(null); // 'edit' | { appointment } | { booking: true }
  const [note, setNote] = useState('');
  const [noteError, setNoteError] = useState('');

  const load = useCallback(async () => {
    try {
      const { data: summary } = await axios.get(`/api/clients/${id}/summary`);
      setData(summary);
      setError('');
    } catch (err) {
      if (err?.response?.status === 404) setError('This client no longer exists.');
      else if (err?.response?.status !== 401) setError(errorMessage(err, "Couldn't load this client."));
    }
  }, [id]);

  useEffect(() => { setData(null); load(); }, [load]);

  const act = async (request) => {
    try { await request(); } catch (err) { console.error(err); }
    load();
    window.dispatchEvent(new Event('sworkr:appointments-changed'));
  };
  const actions = {
    open: (a) => setModal({ appointment: a }),
    status: (a, status, extra = {}) => act(() => axios.put(`/api/appointments/${a.id}/status`, null, { params: { status, ...extra } })),
    paid: (a) => act(() => axios.post(`/api/appointments/${a.id}/mark-paid`)),
    checkIn: (a) => act(() => axios.post(`/api/appointments/${a.id}/check-in`)),
  };

  const addNote = async (e) => {
    e.preventDefault();
    if (!note.trim()) return;
    setNoteError('');
    try {
      await axios.post(`/api/clients/${id}/notes`, { body: note.trim() });
      setNote('');
      load();
    } catch (err) {
      setNoteError(errorMessage(err, 'Could not save the note'));
    }
  };
  const deleteNote = async (n) => {
    if (!window.confirm('Delete this note?')) return;
    await axios.delete(`/api/clients/${id}/notes/${n.id}`).catch(() => {});
    load();
  };

  if (error) {
    return (
      <div className="bg-white rounded-2xl shadow-lg p-6">
        <p className="text-gray-700">{error}</p>
        <Link to="/contacts" className="inline-block mt-3 text-sm text-sworkr-600 hover:text-sworkr-800">← All contacts</Link>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="flex justify-center py-16">
        <div className="animate-spin border-4 rounded-full border-white/30 border-t-white w-12 h-12" role="status" aria-label="Loading" />
      </div>
    );
  }

  const { client, stats, appointments, notes } = data;
  const now = new Date();
  const upcoming = appointments.filter((a) => a.status === 'scheduled' && new Date(a.scheduled_date) >= now).reverse();
  const past = appointments.filter((a) => !upcoming.includes(a));

  return (
    <div className="space-y-4">
      <Link to="/contacts" className="inline-block text-sm text-white/90 hover:text-white">← All contacts</Link>
      <BadDateWarning key={client.updated_at} clientId={client.id} />

      {client.do_not_see && (
        <div className="rounded-2xl bg-red-600 text-white px-5 py-4 shadow-lg" role="alert">
          <p className="font-bold">Do not see</p>
          <p className="text-sm text-white/90">{client.do_not_see_reason || 'This client is flagged. No reason was recorded.'}</p>
        </div>
      )}

      <div className="bg-white rounded-2xl shadow-lg p-5 sm:p-6">
        <div className="flex flex-wrap items-start gap-4">
          <div className="w-14 h-14 shrink-0 rounded-xl flex items-center justify-center font-bold text-white text-2xl" style={{ background: colorFor(client.display_name) }}>
            {client.display_name.replace(/^@/, '').charAt(0).toUpperCase()}
          </div>
          <div className="flex-1 min-w-0">
            <h1 className="text-xl font-bold text-gray-800 break-words">{client.display_name}</h1>
            {client.couple_with && (
              <p className="text-sm text-sworkr-600">
                💞 Couple with <Link to={`/contacts/${client.couple_with}`} className="underline">{client.couple_name}</Link>
              </p>
            )}
            {(client.name && client.name !== client.display_name) || client.industry ? (
              <p className="text-sm text-gray-500">
                {[client.name && client.name !== client.display_name && client.name, client.industry].filter(Boolean).join(' · ')}
              </p>
            ) : null}
            <div className="flex flex-wrap gap-2 mt-1">
              <ScreeningBadge client={client} />
              {!client.is_active && <span className="px-2 py-0.5 bg-gray-100 text-gray-500 rounded-full text-xs font-medium">Inactive</span>}
              {client.tags.map((tag) => (
                <span key={tag} className="px-2 py-0.5 rounded-full text-xs font-medium text-white" style={{ background: colorFor(tag) }}>#{tag}</span>
              ))}
            </div>
            <div className="mt-2 text-sm text-gray-600 space-y-0.5">
              {client.contact_phone && <p><a href={`tel:${client.contact_phone}`} className="hover:text-sworkr-600">{client.contact_phone}</a></p>}
              {client.email && <p><a href={`mailto:${client.email}`} className="hover:text-sworkr-600 break-all">{client.email}</a></p>}
              {client.handles.length > 0 && (
                <ul className="flex flex-wrap gap-x-3 gap-y-0.5">
                  {client.handles.map((h, i) => (
                    <li key={i} className="select-all break-all">
                      {h.platform && <span className="text-gray-400">{h.platform}: </span>}{h.handle}
                    </li>
                  ))}
                </ul>
              )}
              {client.bio && <p className="text-gray-500 whitespace-pre-wrap">{client.bio}</p>}
            </div>
          </div>
          <div className="flex gap-2">
            <button onClick={() => setModal({ booking: true })} className={buttonClass}>+ Book</button>
            <button onClick={() => setModal('edit')} className={quietButtonClass}>Edit</button>
          </div>
        </div>

        <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-5">
          <Stat label="Visits" value={stats.completed}
            sub={[stats.cancelled && `${stats.cancelled} cancelled`, stats.no_shows && `${stats.no_shows} no-show${stats.no_shows === 1 ? '' : 's'}`,
              stats.late_cancellations && `${stats.late_cancellations} late`].filter(Boolean).join(' · ') || null}
            warn={stats.no_shows > 0} />
          <Stat label="Total paid" value={money(stats.total_paid)} />
          <Stat label="Still owed" value={money(stats.outstanding)} warn={stats.outstanding > 0} />
          <Stat label="Last seen" value={shortDate(stats.last_seen)} sub={stats.next_appointment ? `Next: ${shortDate(stats.next_appointment)}` : 'Nothing booked'} />
        </dl>

        {(client.birthday || client.drink_preferences || client.food_preferences) && (
          <div className="grid sm:grid-cols-3 gap-3 mt-4">
            {client.birthday && <BirthdayBlock birthday={client.birthday} />}
            {client.drink_preferences && <TextBlock label="Drinks" text={client.drink_preferences} />}
            {client.food_preferences && <TextBlock label="Food" text={client.food_preferences} />}
          </div>
        )}

        {(client.references || client.screening_notes) && (
          <div className="grid sm:grid-cols-2 gap-3 mt-4">
            {client.references && <TextBlock label="References" text={client.references} />}
            {client.screening_notes && <TextBlock label="Screening notes" text={client.screening_notes} />}
          </div>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_340px] items-start">
        <div className="bg-white rounded-2xl shadow-lg p-5 sm:p-6">
          <h2 className="font-semibold text-gray-800 mb-3">Appointments</h2>
          {appointments.length === 0 && <p className="text-sm text-gray-400">No appointments yet.</p>}
          {upcoming.length > 0 && (
            <>
              <h3 className="text-xs font-medium uppercase tracking-wide text-gray-400 mb-2">Coming up</h3>
              <ul className="space-y-2 mb-5">
                {upcoming.map((a) => <AppointmentItem key={a.id} appointment={a} actions={actions} showDate showClient={false} />)}
              </ul>
            </>
          )}
          {past.length > 0 && (
            <>
              <h3 className="text-xs font-medium uppercase tracking-wide text-gray-400 mb-2">History</h3>
              <ul className="space-y-2">
                {past.map((a) => <AppointmentItem key={a.id} appointment={a} actions={actions} showDate showClient={false} />)}
              </ul>
            </>
          )}
        </div>

        <div className="bg-white rounded-2xl shadow-lg p-5">
          <h2 className="font-semibold text-gray-800 mb-3">Notes</h2>
          <form onSubmit={addNote} className="mb-4">
            <textarea
              rows={3}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Add a note. It's saved with today's date."
              aria-label="New note"
              className={inputClass}
            />
            {noteError && <p className="text-sm text-red-600 mt-1">{noteError}</p>}
            <button type="submit" disabled={!note.trim()} className={`${buttonClass} mt-2`}>Add note</button>
          </form>
          {notes.length === 0 ? (
            <p className="text-sm text-gray-400">No notes yet.</p>
          ) : (
            <ul className="space-y-3">
              {notes.map((n) => (
                <li key={n.id} className="border-l-2 border-sworkr-200 pl-3">
                  <p className="text-xs text-gray-400 flex justify-between gap-2">
                    {shortDate(n.created_at)}
                    <button onClick={() => deleteNote(n)} className="text-gray-300 hover:text-red-500" aria-label="Delete note">✕</button>
                  </p>
                  <p className="text-sm text-gray-700 whitespace-pre-wrap break-words">{n.body}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {modal === 'edit' && (
        <Modal title="Edit contact" onClose={() => setModal(null)}>
          <ClientForm
            client={client}
            onSaved={() => { setModal(null); load(); }}
            onDeleted={() => navigate('/contacts')}
          />
        </Modal>
      )}
      {modal && modal !== 'edit' && (
        <Modal title={modal.appointment ? 'Edit appointment' : `Book ${client.display_name}`} onClose={() => setModal(null)}>
          <AppointmentForm
            appointment={modal.appointment}
            defaultClientId={client.id}
            onSaved={() => { setModal(null); act(async () => {}); }}
            onDeleted={() => { setModal(null); act(async () => {}); }}
          />
        </Modal>
      )}
    </div>
  );
}

function Stat({ label, value, sub, warn }) {
  return (
    <div className="rounded-xl border border-gray-100 px-3 py-2">
      <dt className="text-[11px] uppercase tracking-wide text-gray-400">{label}</dt>
      <dd className={`text-lg font-bold ${warn ? 'text-amber-700' : 'text-gray-800'}`}>{value}</dd>
      {sub && <dd className="text-xs text-gray-500">{sub}</dd>}
    </div>
  );
}

function BirthdayBlock({ birthday }) {
  const next = nextBirthday(birthday);
  const when = next.days === 0 ? 'Today! 🎂' : next.days === 1 ? 'Tomorrow' : `In ${next.days} days`;
  return (
    <div className={`rounded-xl px-3 py-2 ${next.days <= 7 ? 'bg-sworkr-50' : 'bg-gray-50'}`}>
      <p className="text-[11px] uppercase tracking-wide text-gray-400">Birthday</p>
      <p className="text-sm text-gray-700">
        {dayLabel(new Date(`${birthday}T12:00:00`), { month: 'long', day: 'numeric', year: 'numeric' })}
      </p>
      <p className="text-xs text-gray-500">{when} · turns {next.turns}</p>
    </div>
  );
}

function TextBlock({ label, text }) {
  return (
    <div className="rounded-xl bg-gray-50 px-3 py-2">
      <p className="text-[11px] uppercase tracking-wide text-gray-400">{label}</p>
      <p className="text-sm text-gray-700 whitespace-pre-wrap break-words">{text}</p>
    </div>
  );
}
