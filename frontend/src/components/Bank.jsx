import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { inputClass, errorMessage, buttonClass, quietButtonClass } from './Modal';
import { CategorySelect } from './MoneyForms';
import { money } from '../colors';

/** One bank transaction waiting to be added or ignored. */
function Row({ t, onDone }) {
  const [category, setCategory] = useState('other');
  const [busy, setBusy] = useState(false);
  const use = async (action) => {
    setBusy(true);
    try {
      await axios.post(`/api/bank/transactions/${t.id}`, { action, category });
      onDone();
    } catch (err) {
      window.alert(errorMessage(err, "Couldn't do that"));
      setBusy(false);
    }
  };
  const out = t.amount < 0;
  return (
    <li className="py-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
      <span className="w-24 shrink-0 text-xs text-gray-500">{t.day}{t.pending && ' · pending'}</span>
      <span className="flex-1 min-w-40">
        <span className="block text-sm text-gray-800">{t.description || 'Bank transaction'}</span>
        <span className="block text-xs text-gray-500">{t.account_name}</span>
      </span>
      <span className={`tabular-nums text-sm font-medium ${out ? 'text-gray-800' : 'text-emerald-700'}`}>{out ? '−' : '+'}{money(Math.abs(t.amount))}</span>
      <span className="flex flex-wrap items-center gap-2">
        {out ? (
          <>
            <CategorySelect value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Category" className={`${inputClass} !w-40 !py-1.5`} />
            <button disabled={busy} onClick={() => use('expense')} className="text-xs px-2.5 py-1.5 rounded-lg bg-sworkr-500 text-white disabled:opacity-50">Add expense</button>
          </>
        ) : (
          <button disabled={busy} onClick={() => use('income')} className="text-xs px-2.5 py-1.5 rounded-lg bg-emerald-600 text-white disabled:opacity-50">Add income</button>
        )}
        <button disabled={busy} onClick={() => use('ignore')} className="text-xs text-gray-500 hover:text-gray-800">Ignore</button>
      </span>
    </li>
  );
}

/** Money > Bank: transactions from your bank through SimpleFIN, to add or ignore one by one. */
export default function Bank() {
  const [status, setStatus] = useState(null);
  const [rows, setRows] = useState([]);
  const [token, setToken] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => {
    axios.get('/api/bank/status').then(({ data }) => setStatus(data)).catch(() => setStatus({ connected: false }));
    axios.get('/api/bank/transactions').then(({ data }) => setRows(data)).catch(() => setRows([]));
  }, []);
  useEffect(() => { load(); }, [load]);
  const connect = async (e) => {
    e.preventDefault();
    setBusy(true);
    setMessage('');
    try {
      await axios.post('/api/bank/connect', { setup_token: token });
      setToken('');
      const { data } = await axios.post('/api/bank/fetch');
      setMessage(`Connected. ${data.added} transactions brought in.`);
      load();
    } catch (err) {
      setMessage(errorMessage(err, "Couldn't connect"));
    } finally {
      setBusy(false);
    }
  };
  const fetchNow = async () => {
    setBusy(true);
    setMessage('');
    try {
      const { data } = await axios.post('/api/bank/fetch');
      setMessage([`${data.added} new transaction${data.added === 1 ? '' : 's'}.`, ...data.messages].join(' '));
      load();
    } catch (err) {
      setMessage(errorMessage(err, "Couldn't fetch"));
    } finally {
      setBusy(false);
    }
  };
  const disconnect = async () => {
    if (!window.confirm('Disconnect the bank? Transactions already brought in stay.')) return;
    await axios.delete('/api/bank/connect').catch(() => {});
    load();
  };
  if (!status) return null;
  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-bold text-gray-800">Bank</h2>
        {status.connected && (
          <span className="flex gap-2">
            <button onClick={fetchNow} disabled={busy} className={quietButtonClass}>{busy ? 'Fetching…' : 'Fetch new'}</button>
            <button onClick={disconnect} className="text-xs text-gray-500 hover:text-red-600">Disconnect</button>
          </span>
        )}
      </div>
      {!status.connected ? (
        <form onSubmit={connect} className="space-y-3">
          <p className="text-sm text-gray-600">
            Bring in your bank's transactions and add each one as an expense or income with a tap, instead of typing them.
            It works through <a href="https://bridge.simplefin.org" className="text-sworkr-600 underline">SimpleFIN Bridge</a>, an
            independent service (about $1.50 a month) that connects to your bank: your bank password goes to them, never to sworkr.
          </p>
          <ol className="text-sm text-gray-600 list-decimal pl-5 space-y-1">
            <li>Sign up at SimpleFIN Bridge and connect your bank there.</li>
            <li>Make a new <b>setup token</b> for an app, and copy it.</li>
            <li>Paste it here. It works once; sworkr keeps its own access, sealed on your computer.</li>
          </ol>
          <textarea required rows={3} value={token} onChange={(e) => setToken(e.target.value)} placeholder="Paste the setup token" className={inputClass} />
          <button type="submit" disabled={busy} className={buttonClass}>{busy ? 'Connecting…' : 'Connect'}</button>
        </form>
      ) : (
        <>
          <p className="text-xs text-gray-500">
            {status.accounts.map((a) => a.account_name).filter(Boolean).join(', ') || 'Connected'}
            {status.last_fetch && ` · last fetched ${status.last_fetch.slice(0, 16).replace('T', ' ')}`}. Nothing is added to your money until you say so.
          </p>
          {rows.length === 0 ? <p className="text-sm text-gray-400 py-6 text-center">Nothing waiting. Fetch new to check the bank.</p> : (
            <ul className="divide-y divide-gray-100">{rows.map((t) => <Row key={t.id} t={t} onDone={load} />)}</ul>
          )}
        </>
      )}
      {message && <p className="text-sm text-gray-700">{message}</p>}
    </div>
  );
}
