import { useEffect, useState } from 'react';
import axios from 'axios';
import ClientCard from './components/ClientCard';
import { formatDuration, money } from './colors';

const TYPES = ['all', 'clients', 'appointments', 'expenses'];

export default function SearchOverlay({ isOpen, onClose }) {
  const [query, setQuery] = useState('');
  const [entityType, setEntityType] = useState('all');
  // The results on screen, kept together with the search they belong to. That way
  // "No results found" can only show for a search that has actually finished.
  const [found, setFound] = useState({ key: '', results: [] });
  const searchKey = `${entityType}:${query.trim()}`;
  const searching = found.key !== searchKey;
  const results = found.results;

  const changeQuery = (value) => {
    setQuery(value);
    if (!value.trim()) setFound({ key: '', results: [] }); // clearing the box clears the old results with it
  };

  useEffect(() => {
    const q = query.trim();
    if (!q) return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      let next = null;
      try {
        const { data } = await axios.get('/api/search', { params: { q, entity_type: entityType } });
        next = data.results;
      } catch (err) {
        console.error('Search failed:', err);
      }
      // If the search failed, keep showing what was there before.
      if (!cancelled) setFound((prev) => ({ key: searchKey, results: next ?? prev.results }));
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query, entityType]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-24 px-4">
      <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />

      <div className="relative w-full max-w-2xl bg-white rounded-2xl shadow-xl overflow-hidden">
        <div className="flex items-center gap-3 p-4 border-b border-gray-100">
          <input
            autoFocus
            type="text"
            value={query}
            onChange={(e) => changeQuery(e.target.value)}
            placeholder="Search clients, appointments, or expenses..."
            className="flex-1 text-gray-800 placeholder-gray-400 outline-none px-2 py-2"
          />
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700">✕</button>
        </div>
        <div className="flex gap-2 px-4 py-2 border-b border-gray-100">
          {TYPES.map((type) => (
            <button
              key={type}
              onClick={() => setEntityType(type)}
              className={`px-3 py-1 rounded-md text-sm transition-colors ${
                entityType === type ? 'bg-sworkr-500 text-white' : 'text-gray-500 hover:text-gray-800'
              }`}
            >
              {type.charAt(0).toUpperCase() + type.slice(1)}
            </button>
          ))}
        </div>

        <div className="max-h-96 overflow-y-auto p-3 space-y-2">
          {!query.trim() ? (
            <p className="text-center text-gray-400 py-6">Type to search</p>
          ) : searching && results.length === 0 ? (
            <p className="text-center text-gray-400 py-6">Searching…</p>
          ) : results.length === 0 ? (
            <p className="text-center text-gray-400 py-6">No results found</p>
          ) : (
            results.map((item) => (
              <div key={`${item.entity_type}-${item.id}`}>
                {item.entity_type === 'client' ? (
                  <ClientCard client={item} />
                ) : item.entity_type === 'appointment' ? (
                  <div className="rounded-xl p-3 border border-gray-100">
                    <p className="text-xs font-medium text-gray-400 uppercase">Appointment</p>
                    <p className="font-medium">{item.client_name || 'Unknown client'} · {item.service_type}</p>
                    <p className="text-sm text-gray-500">
                      {new Date(item.scheduled_date).toLocaleString()} · {formatDuration(item.duration_minutes)} · {item.status}
                    </p>
                  </div>
                ) : (
                  <div className="rounded-xl p-3 border border-gray-100">
                    <p className="text-xs font-medium text-gray-400 uppercase">Expense</p>
                    <p className="font-medium">{item.description}</p>
                    <p className="text-sm text-green-600 font-semibold">{money(item.amount)} · {item.category}</p>
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
