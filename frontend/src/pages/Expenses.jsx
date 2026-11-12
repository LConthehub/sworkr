import { useEffect, useState } from 'react';
import axios from 'axios';
import { CATEGORY_COLORS, money } from '../colors';

const CATEGORIES = ['equipment', 'marketing', 'travel', 'cleaning', 'other'];
const EMPTY_SUMMARY = { category_summary: [], top_clients: [], overall_total: 0, expense_count: 0, average: 0 };

export default function Expenses() {
  const [expenses, setExpenses] = useState([]);
  const [summary, setSummary] = useState(EMPTY_SUMMARY);
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [clientFilter, setClientFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('all');

  const loadExpenses = async () => {
    setLoading(true);
    try {
      const params = {};
      if (clientFilter) params.client_id = clientFilter;
      if (categoryFilter !== 'all') params.category = categoryFilter;
      const { data } = await axios.get('/api/expenses', { params });
      setExpenses(data);
    } catch (err) {
      console.error('Error loading expenses:', err);
    } finally {
      setLoading(false);
    }
  };

  const loadSummary = async () => {
    try {
      const { data } = await axios.get('/api/expenses/summary');
      setSummary({ ...EMPTY_SUMMARY, ...data });
    } catch (err) {
      console.error('Error loading summary:', err);
    }
  };

  const refresh = () => { loadExpenses(); loadSummary(); };

  useEffect(() => {
    loadSummary();
    axios.get('/api/clients', { params: { limit: 200 } }).then(({ data }) => setClients(data)).catch(() => {});
  }, []);

  useEffect(() => {
    loadExpenses();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientFilter, categoryFilter]);

  const remove = async (id) => {
    await axios.delete(`/api/expenses/${id}`);
    refresh();
  };

  return (
    <div className="bg-white rounded-2xl shadow-lg p-6">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <h1 className="text-xl font-bold text-gray-800">Expenses</h1>
        <div className="flex flex-wrap items-center gap-3">
          <select
            value={clientFilter}
            onChange={(e) => setClientFilter(e.target.value)}
            className="px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-sworkr-300"
          >
            <option value="">All clients</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          <div className="flex gap-1">
            {['all', ...CATEGORIES].map((cat) => (
              <button
                key={cat}
                onClick={() => setCategoryFilter(cat)}
                className={`px-3 py-1.5 rounded-full text-sm font-medium transition-colors ${
                  categoryFilter === cat ? 'text-white' : 'text-gray-400 hover:text-gray-600'
                }`}
                style={categoryFilter === cat ? { background: CATEGORY_COLORS[cat] || '#fc4c9c' } : undefined}
              >
                {cat.charAt(0).toUpperCase() + cat.slice(1)}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <SummaryCard label="Total spent" value={money(summary.overall_total)} color="#fc4c9c" />
        <SummaryCard label="Expenses" value={summary.expense_count} color="#e67eb6" />
        <SummaryCard label="Avg / expense" value={money(summary.average)} color="#a73178" />
        <SummaryCard label="Categories" value={summary.category_summary.length} color="#542b5c" />
      </div>

      <NewExpenseForm clients={clients} onCreated={refresh} />

      {loading ? (
        <p className="text-center py-8 text-gray-400">Loading expenses…</p>
      ) : expenses.length === 0 ? (
        <p className="text-center py-8 text-gray-400">No expenses found</p>
      ) : (
        <ul className="space-y-2">
          {expenses.map((exp) => (
            <li key={exp.id} className="flex items-center gap-4 bg-white rounded-xl p-4 border border-gray-100">
              <div className="flex-1 min-w-0">
                <p className="font-medium text-sm">{exp.description}</p>
                <p className="text-xs text-gray-400">
                  {new Date(exp.date).toLocaleDateString()}
                  {exp.client_name && ` · ${exp.client_name}`}
                </p>
              </div>
              <span
                className="px-2.5 py-1 rounded-full text-[11px] font-medium text-white"
                style={{ background: CATEGORY_COLORS[exp.category] }}
              >
                {exp.category}
              </span>
              <p className="font-bold w-24 text-right">{money(exp.amount)}</p>
              <button onClick={() => remove(exp.id)} className="text-xs text-red-500 hover:text-red-700">
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}

      {summary.category_summary.length > 0 && (
        <div className="mt-8 bg-gray-50 rounded-xl p-4">
          <h2 className="text-sm font-semibold text-gray-600 mb-3">Breakdown by category</h2>
          <div className="space-y-3">
            {summary.category_summary.map((cat) => (
              <div key={cat.category}>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-700">{cat.category}</span>
                  <span className="font-semibold">{money(cat.total)}</span>
                </div>
                <div className="w-full h-1.5 bg-gray-200 rounded-full overflow-hidden mt-1">
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${summary.overall_total ? (cat.total / summary.overall_total) * 100 : 0}%`,
                      backgroundColor: CATEGORY_COLORS[cat.category],
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {summary.top_clients.length > 0 && (
        <div className="mt-8 bg-gray-50 rounded-xl p-4">
          <h2 className="text-sm font-semibold text-gray-600 mb-3">Expenses by client</h2>
          <ul>
            {summary.top_clients.map((c) => (
              <li key={c.name} className="flex justify-between py-2 border-b last:border-none border-gray-100 text-sm">
                <span className="text-gray-700">{c.name}</span>
                <span>
                  <span className="font-semibold">{money(c.total_spent)}</span>
                  <span className="text-xs text-gray-400 ml-2">({c.expense_count})</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function SummaryCard({ label, value, color }) {
  return (
    <div className="bg-white rounded-xl p-4 border border-gray-100">
      <p className="text-xs text-gray-500 uppercase tracking-wide">{label}</p>
      <p className="text-2xl font-bold mt-1" style={{ color }}>{value}</p>
    </div>
  );
}

function NewExpenseForm({ clients, onCreated }) {
  const [form, setForm] = useState({ description: '', amount: '', category: 'other', client_id: '' });
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const input = 'bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-sworkr-300';

  const submit = async (e) => {
    e.preventDefault();
    await axios.post('/api/expenses', {
      description: form.description,
      amount: parseFloat(form.amount),
      category: form.category,
      client_id: form.client_id ? Number(form.client_id) : null,
    });
    setForm({ description: '', amount: '', category: 'other', client_id: '' });
    onCreated();
  };

  return (
    <form onSubmit={submit} className="flex flex-wrap gap-2 mb-6 p-3 bg-gray-50 rounded-xl">
      <input required placeholder="Description" value={form.description} onChange={set('description')} className={`${input} flex-1 min-w-40`} />
      <input required type="number" min="0" step="0.01" placeholder="Amount" value={form.amount} onChange={set('amount')} className={`${input} w-28`} />
      <select value={form.category} onChange={set('category')} className={input}>
        {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
      <select value={form.client_id} onChange={set('client_id')} className={input}>
        <option value="">No client</option>
        {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select>
      <button type="submit" className="px-4 py-2 bg-sworkr-500 text-white rounded-lg hover:bg-sworkr-600 text-sm">
        Add expense
      </button>
    </form>
  );
}
