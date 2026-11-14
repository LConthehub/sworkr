import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import ClientCard from '../components/ClientCard';
import Modal from '../components/Modal';
import ClientForm from '../components/ClientForm';
import CsvTools from '../components/CsvTools';

const LIMIT = 21;
const FILTERS = [
  { id: 'all', label: 'All', params: {} },
  { id: 'clients', label: 'Clients', params: { role: 'client' } },
  { id: 'partners', label: 'Co-workers', params: { role: 'partner' } },
  { id: 'crew', label: 'Crew', params: { role: 'crew' } },
  { id: 'active', label: 'Active', params: { is_active: 1 } },
  { id: 'inactive', label: 'Inactive', params: { is_active: 0 } },
  { id: 'unverified', label: 'Not verified', params: { screening: 'unscreened' } },
  { id: 'pending', label: 'Pending', params: { screening: 'pending' } },
  { id: 'dns', label: 'Do not see', params: { do_not_see: 1 } },
];

export default function ClientList() {
  const navigate = useNavigate();
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);   // true from the start, so "No contacts yet" never flashes before the first load
  const [error, setError] = useState('');
  const [filter, setFilter] = useState('all');
  const [sort, setSort] = useState('recent');
  const [searchQuery, setSearchQuery] = useState('');
  const [page, setPage] = useState(1);
  const [adding, setAdding] = useState(false);

  const loadClients = async () => {
    setLoading(true);
    try {
      const params = { page, limit: LIMIT, sort, ...FILTERS.find((f) => f.id === filter).params };
      if (searchQuery.trim()) params.search = searchQuery.trim();
      const { data } = await axios.get('/api/clients', { params });
      setClients(data);
      setError('');
    } catch (err) {
      if (err?.response?.status !== 401) setError("Couldn't load contacts. Check that sworkr is running.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const t = setTimeout(loadClients, 200);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter, sort, searchQuery, page]);

  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h1 className="text-xl font-bold text-gray-800">Contacts</h1>
        <div className="flex flex-wrap items-center gap-2">
          <CsvTools kind="clients" onImported={loadClients} />
          <button
            onClick={() => setAdding(true)}
            className="px-4 py-2 rounded-full text-sm font-medium bg-sworkr-500 text-white hover:bg-sworkr-600"
          >
            + Add contact
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 mb-4">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            onClick={() => { setFilter(f.id); setPage(1); }}
            aria-pressed={filter === f.id}
            className={`px-3 py-1.5 rounded-full text-sm font-medium transition-colors border ${
              filter === f.id
                ? 'bg-sworkr-500/20 text-sworkr-600 border-sworkr-300'
                : 'text-gray-500 hover:text-gray-700 border-gray-200'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className="flex gap-2 mb-6">
        <input
          type="search"
          value={searchQuery}
          onChange={(e) => { setSearchQuery(e.target.value); setPage(1); }}
          placeholder="Search by name, handle, industry, email or phone…"
          aria-label="Search contacts"
          className="flex-1 min-w-0 bg-gray-50 border border-gray-200 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:border-sworkr-300"
        />
        <select
          value={sort}
          onChange={(e) => { setSort(e.target.value); setPage(1); }}
          aria-label="Sort contacts"
          className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-sworkr-300"
        >
          <option value="recent">Newest first</option>
          <option value="name">A to Z</option>
        </select>
      </div>

      {adding && (
        <Modal title="New contact" onClose={() => setAdding(false)}>
          <ClientForm onSaved={(c) => { setAdding(false); navigate(`/contacts/${c.id}`); }} />
        </Modal>
      )}

      {error && <p className="mb-3 text-sm rounded-lg px-3 py-2 bg-red-50 text-red-700">{error}</p>}

      {loading && clients.length === 0 ? (
        <div className="flex justify-center py-12">
          <div className="animate-spin border-4 rounded-full border-sworkr-500/20 border-t-sworkr-500 w-12 h-12" role="status" aria-label="Loading" />
        </div>
      ) : clients.length === 0 ? (
        <p className="text-center py-12 text-gray-400">
          {searchQuery.trim() || filter !== 'all' ? 'No contacts match' : 'No contacts yet. Add your first one.'}
        </p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {clients.map((client) => (
            <ClientCard key={client.id} client={client} onClick={() => navigate(`/contacts/${client.id}`)} />
          ))}
        </div>
      )}

      {(page > 1 || clients.length === LIMIT) && (
        <div className="flex justify-between items-center mt-6">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-4 py-2 bg-gray-100 rounded-lg hover:bg-gray-200 disabled:opacity-50 text-sm"
          >
            Previous
          </button>
          <span className="text-sm text-gray-500">Page {page}</span>
          <button
            onClick={() => setPage((p) => p + 1)}
            disabled={clients.length < LIMIT}
            className="px-4 py-2 bg-sworkr-500 text-white rounded-lg hover:bg-sworkr-600 disabled:opacity-50 text-sm"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
