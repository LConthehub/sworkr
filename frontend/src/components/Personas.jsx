import { useEffect, useState } from 'react';
import axios from 'axios';
import Modal, { Field, inputClass, errorMessage, buttonClass } from './Modal';

// ----- the names you work under, loaded once and shared -----
let cache = null;
const listeners = new Set();

export async function reloadPersonas() {
  const { data } = await axios.get('/api/personas');
  cache = data;
  listeners.forEach((fn) => fn(data));
  return data;
}

/** Your personas (archived ones too, with archived: true), in name order. */
export function usePersonas() {
  const [list, setList] = useState(cache || []);
  useEffect(() => {
    listeners.add(setList);
    if (!cache) reloadPersonas().catch(() => {});
    return () => listeners.delete(setList);
  }, []);
  return list;
}

export function clearPersonaCache() {
  cache = null;
}

/**
 * "Which name is this under?" Shown only once you have a persona (or this already has one), so nobody who
 * works under one name sees it.
 */
export function PersonaSelect({ value, onChange, label = 'Persona (the name you use with them)' }) {
  const personas = usePersonas();
  const shown = personas.filter((p) => !p.archived || String(p.id) === String(value));
  if (shown.length === 0) return null;
  return (
    <Field label={label}>
      <select value={value ?? ''} onChange={onChange} className={inputClass}>
        <option value="">None</option>
        {shown.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select>
    </Field>
  );
}

/** A small coloured badge with a persona's name. */
export function PersonaBadge({ id }) {
  const persona = usePersonas().find((p) => p.id === id);
  if (!persona) return null;
  return (
    <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium text-white" style={{ background: persona.color }}>
      {persona.name}
    </span>
  );
}

/** Settings: add, rename, recolour, archive and delete personas. */
export function PersonaSettings() {
  const [kit, setKit] = useState(null);   // the persona whose kit is open
  const personas = usePersonas();
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const run = async (request) => {
    setError('');
    try {
      await request();
      await reloadPersonas();
      return true;
    } catch (err) {
      setError(errorMessage(err, 'Could not save'));
      return false;
    }
  };
  const save = (p, changes) => run(() => axios.put(`/api/personas/${p.id}`, { name: p.name, color: p.color, notes: p.notes, archived: p.archived, ...changes }));
  const add = async (e) => {
    e.preventDefault();
    if (name.trim() && await run(() => axios.post('/api/personas', { name: name.trim() }))) setName('');
  };
  const remove = (p) => {
    const used = p.contacts + p.places + p.posts;
    if (window.confirm(`Delete the persona "${p.name}"?${used ? ' Its contacts, places and posts stay, without a persona.' : ''}`)) {
      run(() => axios.delete(`/api/personas/${p.id}`));
    }
  };

  return (
    <div className="space-y-3">
      {kit && <PersonaKit persona={kit} onClose={() => setKit(null)} />}
      {personas.length > 0 && (
        <ul className="divide-y divide-gray-100">
          {personas.map((p) => (
            <li key={p.id} className="flex items-center gap-2 py-2">
              <input type="color" value={p.color || '#9ca3af'} onChange={(e) => save(p, { color: e.target.value })}
                className="w-8 h-8 shrink-0 rounded cursor-pointer border border-gray-200" aria-label={`Colour for ${p.name}`} />
              <input key={p.name} defaultValue={p.name} aria-label={`Name of persona ${p.name}`}
                onBlur={(e) => e.target.value.trim() && e.target.value.trim() !== p.name && save(p, { name: e.target.value.trim() })}
                className={`${inputClass} ${p.archived ? 'text-gray-400' : ''}`} />
              <span className="text-xs text-gray-400 shrink-0 w-28 text-right">
                {[p.contacts && `${p.contacts} contact${p.contacts === 1 ? '' : 's'}`, p.places && `${p.places} place${p.places === 1 ? '' : 's'}`]
                  .filter(Boolean).join(', ')}
              </span>
              <button type="button" onClick={() => save(p, { archived: !p.archived })} className="text-xs text-gray-500 hover:text-gray-800 w-14 shrink-0">
                {p.archived ? 'Restore' : 'Archive'}
              </button>
              <button type="button" onClick={() => setKit(p)} className="text-xs text-sworkr-600 hover:text-sworkr-800 w-8 shrink-0">Kit</button>
              <button type="button" onClick={() => remove(p)} className="text-xs text-red-500 hover:text-red-700 w-12 shrink-0">Delete</button>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={add} className="flex gap-2">
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="A name you work under" aria-label="New persona" className={inputClass} />
        <button type="submit" disabled={!name.trim()} className={buttonClass}>Add</button>
      </form>
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  );
}

const KIT_KINDS = [['bio', 'Bios', 'A bio for each platform'], ['link', 'Social links', 'Your accounts'], ['wishlist', 'Wishlists', 'Wishlist and gift links']];

/** A persona's kit: bios by platform, social links and wishlists, each one tap to copy. */
export function PersonaKit({ persona, onClose }) {
  const [items, setItems] = useState(null);
  const [form, setForm] = useState({ kind: 'bio', platform: '', body: '' });
  const [copied, setCopied] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    axios.get(`/api/personas/${persona.id}/kit`).then(({ data }) => setItems(data)).catch(() => setItems([]));
  }, [persona.id]);
  const add = async (e) => {
    e.preventDefault();
    setError('');
    try {
      const { data } = await axios.post(`/api/personas/${persona.id}/kit`, form);
      setItems(data);
      setForm({ ...form, platform: '', body: '' });
    } catch (err) {
      setError(errorMessage(err, "Couldn't add it"));
    }
  };
  const remove = async (item) => {
    await axios.delete(`/api/personas/${persona.id}/kit/${item.id}`).catch(() => {});
    setItems(items.filter((x) => x.id !== item.id));
  };
  const copy = async (item) => {
    try { await navigator.clipboard.writeText(item.body); setCopied(item.id); setTimeout(() => setCopied(null), 1500); } catch { /* blocked */ }
  };
  return (
    <Modal title={`${persona.name}: kit`} onClose={onClose} wide>
      {items === null ? null : (
        <div className="space-y-4">
          {KIT_KINDS.map(([kind, title]) => {
            const list = items.filter((i) => i.kind === kind);
            return list.length > 0 && (
              <section key={kind}>
                <h3 className="text-sm font-semibold text-gray-700 mb-1">{title}</h3>
                <ul className="divide-y divide-gray-100">
                  {list.map((i) => (
                    <li key={i.id} className="py-2 flex items-start gap-2">
                      <span className="flex-1 min-w-0">
                        {i.platform && <span className="block text-xs text-gray-500">{i.platform}</span>}
                        <span className="block text-sm text-gray-800 whitespace-pre-wrap break-words">{i.body}</span>
                      </span>
                      <button type="button" onClick={() => copy(i)} className="text-xs px-2.5 py-1 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 shrink-0">{copied === i.id ? 'Copied ✓' : 'Copy'}</button>
                      <button type="button" onClick={() => remove(i)} className="text-xs text-gray-400 hover:text-red-600 shrink-0" aria-label="Remove">✕</button>
                    </li>
                  ))}
                </ul>
              </section>
            );
          })}
          <form onSubmit={add} className="space-y-2 border-t border-gray-100 pt-3">
            <div className="grid grid-cols-2 gap-2">
              <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })} aria-label="What it is" className={inputClass}>
                <option value="bio">A bio</option><option value="link">A social link</option><option value="wishlist">A wishlist link</option>
              </select>
              <input value={form.platform} onChange={(e) => setForm({ ...form, platform: e.target.value })} placeholder="Where: X, Tryst, OF, my site…" aria-label="Platform" className={inputClass} />
            </div>
            {form.kind === 'bio'
              ? <textarea required rows={3} value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} placeholder="The bio, as you'd paste it" className={inputClass} />
              : <input required value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} placeholder="https://…" className={inputClass} />}
            {error && <p className="text-sm text-red-600">{error}</p>}
            <div className="flex justify-end"><button type="submit" className={buttonClass}>Add</button></div>
          </form>
        </div>
      )}
    </Modal>
  );
}
