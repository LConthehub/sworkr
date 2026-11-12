import { useEffect, useState } from 'react';
import axios from 'axios';
import ClientCard from '../components/ClientCard';
import Modal from '../components/Modal';
import ClientForm from '../components/ClientForm';

const LIMIT = 21;

export default function ClientList() {
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(false);
  const [activeFilter, setActiveFilter] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [page, setPage] = useState(1);
  const [modal, setModal] = useState(null); // { client } to edit, {} to add

  const loadClients = async () => {
    setLoading(true);
    try {
      const params = { page, limit: LIMIT };
      if (activeFilter === 'active') params.is_active = 1;
      if (activeFilter === 'inactive') params.is_active = 0;
      if (searchQuery.trim()) params.search = searchQuery.trim();
      const { data } = await axios.get('/api/clients', { params });
      setClients(data);
    } catch (err) {
      console.error('Error loading clients:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const t = setTimeout(loadClients, 200);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeFilter, searchQuery, page]);

  return (
    <div className="bg-white rounded-2xl shadow-lg p-6">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <h1 className="text-xl font-bold text-gray-800">Client Profiles</h1>
        <div className="flex gap-2">
          {['all', 'active', 'inactive'].map((filter) => (
            <button
              key={filter}
              onClick={() => { setActiveFilter(filter); setPage(1); }}
              className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors border ${
                activeFilter === filter
                  ? 'bg-sworkr-500/20 text-sworkr-600 border-sworkr-300'
                  : 'text-gray-400 hover:text-gray-600 border-transparent'
              }`}
            >
              {filter.charAt(0).toUpperCase() + filter.slice(1)}
            </button>
          ))}
          <button
            onClick={() => setModal({})}
            className="px-4 py-1.5 rounded-full text-sm font-medium bg-sworkr-500 text-white hover:bg-sworkr-600"
          >
            + Add Client
          </button>
        </div>
      </div>

      {modal && (
        <Modal title={modal.client ? 'Edit client' : 'New client'} onClose={() => setModal(null)}>
          <ClientForm
            client={modal.client}
            onSaved={() => { setModal(null); loadClients(); }}
            onDeleted={() => { setModal(null); loadClients(); }}
          />
        </Modal>
      )}

      <input
        type="text"
        value={searchQuery}
        onChange={(e) => { setSearchQuery(e.target.value); setPage(1); }}
        placeholder="Search clients by name or email..."
        className="w-full mb-6 bg-gray-50 border border-gray-200 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:border-sworkr-300"
      />

      {loading && clients.length === 0 ? (
        <div className="flex justify-center py-12">
          <div className="animate-spin border-4 rounded-full border-sworkr-500/20 border-t-sworkr-500 w-12 h-12" />
        </div>
      ) : clients.length === 0 ? (
        <p className="text-center py-12 text-gray-400">No clients found</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {clients.map((client) => (
            <ClientCard key={client.id} client={client} onClick={() => setModal({ client })} />
          ))}
        </div>
      )}

      <div className="flex justify-between items-center mt-6">
        <button
          onClick={() => setPage((p) => Math.max(1, p - 1))}
          disabled={page === 1}
          className="px-4 py-2 bg-gray-100 rounded-lg hover:bg-gray-200 disabled:opacity-50"
        >
          Previous
        </button>
        <span className="text-sm text-gray-500">Page {page}</span>
        <button
          onClick={() => setPage((p) => p + 1)}
          disabled={clients.length < LIMIT}
          className="px-4 py-2 bg-sworkr-500 text-white rounded-lg hover:bg-sworkr-600 disabled:opacity-50"
        >
          Next
        </button>
      </div>
    </div>
  );
}
