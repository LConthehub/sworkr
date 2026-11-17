import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { Field, inputClass, errorMessage, buttonClass } from './Modal';
import { fetchAll } from '../api';
import { dayLabel, fromDateInput, fromDateTimeInputs, toDateInput, toTimeInput } from '../colors';

const shortDay = (value) => dayLabel(fromDateInput(value), { weekday: 'short', month: 'short', day: 'numeric' });

/** Add or edit a task. */
export function TaskForm({ task, defaultDate, onSaved }) {
  const [form, setForm] = useState({
    title: task?.title || '',
    due_date: task?.due_date || (defaultDate ? toDateInput(defaultDate) : ''),
    due_time: task?.due_at ? toTimeInput(new Date(task.due_at)) : '',
    notes: task?.notes || '',
    client_id: task?.client_id ? String(task.client_id) : '',
    tour_id: task?.tour_id ? String(task.tour_id) : '',
    done: !!task?.done,
  });
  const [contacts, setContacts] = useState([]);
  const [tours, setTours] = useState([]);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });

  useEffect(() => {
    fetchAll('/api/clients', { sort: 'name' }, 200).then(setContacts).catch(() => {});
    axios.get('/api/tours', { params: { kind: 'tour' } }).then(({ data }) => setTours(data)).catch(() => {});
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    if (form.due_time && !form.due_date) return setError('Choose a day for the time');
    const body = {
      title: form.title.trim(),
      notes: form.notes.trim() || null,
      due_date: form.due_date || null,
      due_at: form.due_date && form.due_time ? fromDateTimeInputs(form.due_date, form.due_time).toISOString() : null,
      client_id: form.client_id ? Number(form.client_id) : null,
      tour_id: form.tour_id ? Number(form.tour_id) : null,
      done: form.done,
    };
    setSaving(true);
    try {
      const { data } = task ? await axios.put(`/api/tasks/${task.id}`, body) : await axios.post('/api/tasks', body);
      onSaved(data);
    } catch (err) {
      setError(errorMessage(err, 'Could not save the task'));
    } finally {
      setSaving(false);
    }
  };
  const remove = async () => {
    if (!window.confirm(`Delete the task "${task.title}"?`)) return;
    await axios.delete(`/api/tasks/${task.id}`).catch(() => {});
    onSaved(null);
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <Field label="Task *">
        <input required autoFocus value={form.title} onChange={set('title')} placeholder="e.g. Book the Miami hotel" className={inputClass} />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Due (optional)">
          <input type="date" value={form.due_date} onChange={set('due_date')} className={inputClass} />
        </Field>
        <Field label="Time (optional)">
          <input type="time" value={form.due_time} onChange={set('due_time')} disabled={!form.due_date} className={inputClass} />
        </Field>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Field label="About a contact">
          <select value={form.client_id} onChange={set('client_id')} className={inputClass}>
            <option value="">No one</option>
            {contacts.map((c) => <option key={c.id} value={c.id}>{c.display_name}</option>)}
          </select>
        </Field>
        <Field label="For a tour">
          <select value={form.tour_id} onChange={set('tour_id')} className={inputClass}>
            <option value="">No tour</option>
            {[...tours].reverse().map((t) => <option key={t.id} value={t.id}>{t.name} ({t.start_date})</option>)}
          </select>
        </Field>
      </div>
      <Field label="Notes">
        <textarea rows={2} value={form.notes} onChange={set('notes')} className={inputClass} />
      </Field>
      {task && (
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={form.done} onChange={set('done')} /> Done
        </label>
      )}
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex items-center justify-between pt-1">
        {task ? <button type="button" onClick={remove} className="text-sm text-red-500 hover:text-red-700">Delete task</button> : <span />}
        <button type="submit" disabled={saving} className={buttonClass}>{saving ? 'Saving…' : task ? 'Save changes' : 'Add task'}</button>
      </div>
    </form>
  );
}

/** One task with its tick box. */
export function TaskItem({ task, onToggle, onOpen }) {
  const today = toDateInput(new Date());
  const overdue = !task.done && task.due_date && task.due_date < today;
  return (
    <li className="flex items-start gap-2 py-1.5">
      <input type="checkbox" checked={task.done} onChange={() => onToggle(task)} className="mt-1 shrink-0" aria-label={`Done: ${task.title}`} />
      <button onClick={() => onOpen(task)} className="flex-1 min-w-0 text-left">
        <span className={`block text-sm break-words ${task.done ? 'line-through text-gray-400' : 'text-gray-800'}`}>{task.title}</span>
        <span className="block text-xs text-gray-500">
          {[
            task.due_date && (overdue ? <span key="d" className="text-red-600">Overdue · {shortDay(task.due_date)}</span> : shortDay(task.due_date)),
            task.due_at && new Date(task.due_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }),
            task.client_name, task.tour_name && `✈ ${task.tour_name}`,
          ].filter(Boolean).map((x, i) => <span key={i}>{i > 0 && ' · '}{x}</span>)}
        </span>
      </button>
    </li>
  );
}

/**
 * The open to-do list: overdue first, then by due day, then those with no day. A quick-add box at the top.
 * `version` changes when tasks change elsewhere (for example on the calendar), so the list reloads.
 */
export function TasksPanel({ version, onChanged, onOpen }) {
  const [tasks, setTasks] = useState(null);
  const [title, setTitle] = useState('');
  const [showDone, setShowDone] = useState(false);
  const [done, setDone] = useState([]);

  const load = useCallback(async () => {
    try {
      const [{ data: open }, { data: finished }] = await Promise.all([
        axios.get('/api/tasks'),
        axios.get('/api/tasks', { params: { status: 'done', limit: 20 } }),
      ]);
      setTasks(open);
      setDone(finished.sort((a, b) => (b.done_at || '').localeCompare(a.done_at || '')));
    } catch {
      setTasks([]);
    }
  }, []);
  useEffect(() => { load(); }, [load, version]);

  const add = async (e) => {
    e.preventDefault();
    if (!title.trim()) return;
    await axios.post('/api/tasks', { title: title.trim() }).catch(() => {});
    setTitle('');
    onChanged();
  };
  const toggle = async (task) => {
    await axios.post(`/api/tasks/${task.id}/done`, { done: !task.done }).catch(() => {});
    onChanged();
  };

  return (
    <div className="bg-white rounded-2xl border border-line shadow-sm p-4 sm:p-5">
      <div className="flex items-center justify-between mb-2">
        <h2 className="font-semibold text-gray-800">Tasks</h2>
        <button onClick={() => onOpen(null)} className="text-sm text-sworkr-600 hover:text-sworkr-800">+ Task with a day</button>
      </div>
      <form onSubmit={add} className="mb-2">
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Add a task and press Enter" aria-label="New task" className={inputClass} />
      </form>
      {tasks === null ? null : tasks.length === 0 ? (
        <p className="text-sm text-gray-400 py-2">Nothing to do. 🎉</p>
      ) : (
        <ul className="divide-y divide-gray-100">
          {tasks.map((t) => <TaskItem key={t.id} task={t} onToggle={toggle} onOpen={onOpen} />)}
        </ul>
      )}
      {done.length > 0 && (
        <div className="mt-2">
          <button onClick={() => setShowDone(!showDone)} className="text-xs text-gray-500 hover:text-gray-800">
            {showDone ? 'Hide done' : `Show recently done (${done.length})`}
          </button>
          {showDone && (
            <ul className="divide-y divide-gray-100 mt-1">
              {done.map((t) => <TaskItem key={t.id} task={t} onToggle={toggle} onOpen={onOpen} />)}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
