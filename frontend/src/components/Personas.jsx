import { useEffect, useState } from 'react';
import axios from 'axios';
import { Field, inputClass, errorMessage, buttonClass } from './Modal';

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
