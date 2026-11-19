import { useEffect, useState } from 'react';
import axios from 'axios';
import { Field, inputClass, errorMessage, buttonClass, quietButtonClass } from './Modal';

const PRESETS = [
  ['LM Studio', 'http://host.docker.internal:1234/v1'],
  ['Ollama', 'http://host.docker.internal:11434/v1'],
  ['llama.cpp', 'http://host.docker.internal:8080/v1'],
];

/** Settings > Connections > Assistant: which model to ask, on this computer unless you say otherwise. */
export function AssistantSettings() {
  const [form, setForm] = useState(null);
  const [message, setMessage] = useState('');
  const [models, setModels] = useState([]);
  useEffect(() => {
    axios.get('/api/assistant/settings').then(({ data }) => setForm({ ...data, key: '' })).catch(() => {});
  }, []);
  if (!form) return null;
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const save = async (e) => {
    e?.preventDefault();
    setMessage('');
    try {
      const { data } = await axios.put('/api/assistant/settings', form);
      setForm({ ...data, key: '' });
      setMessage('Saved.');
      return true;
    } catch (err) {
      setMessage(errorMessage(err, "Couldn't save"));
      return false;
    }
  };
  const test = async () => {
    if (!(await save())) return;
    try {
      const { data } = await axios.post('/api/assistant/test');
      setModels(data.models);
      setMessage(data.models.length ? `Connected. Models: ${data.models.join(', ')}` : 'Connected, but no model is loaded.');
    } catch (err) {
      setMessage(errorMessage(err, "Couldn't reach it"));
    }
  };
  return (
    <form onSubmit={save} className="space-y-3">
      <p className="text-sm text-gray-600">
        Ask questions about your own numbers (best months, what costs most, where clients come from). It runs on a model
        on your own computer: install <a href="https://lmstudio.ai" className="text-sworkr-600 underline">LM Studio</a>,
        Ollama or llama.cpp, load a model and start its server. It only sees totals, never names or notes, and it won't write
        posts or messages for you.
      </p>
      <label className="flex items-center gap-2 text-sm text-gray-700"><input type="checkbox" checked={form.enabled} onChange={set('enabled')} /> Turn on the assistant</label>
      <Field label="Model server address">
        <input value={form.url} onChange={set('url')} className={inputClass} />
        <span className="mt-1 flex flex-wrap gap-1">
          {PRESETS.map(([name, url]) => (
            <button key={name} type="button" onClick={() => setForm({ ...form, url })} className="text-xs px-2 py-0.5 rounded-full border border-gray-200 text-gray-600 hover:bg-gray-50">{name}</button>
          ))}
        </span>
        <span className="block text-xs text-gray-500 mt-1">With the Windows app, use localhost instead of host.docker.internal.</span>
      </Field>
      <Field label="Model (optional)">
        <input list="ai-models" value={form.model} onChange={set('model')} placeholder="The server's default" className={inputClass} />
        <datalist id="ai-models">{models.map((m) => <option key={m} value={m} />)}</datalist>
      </Field>
      <details className="rounded-lg border border-gray-200 px-3 py-2">
        <summary className="text-sm text-gray-700 cursor-pointer">A cloud AI instead (off by default)</summary>
        <div className="mt-2 space-y-2">
          <label className="flex items-start gap-2 text-sm text-red-700">
            <input type="checkbox" checked={form.cloud_ok} onChange={set('cloud_ok')} className="mt-1" />
            Allow an address outside my computer and network. My totals will be sent to that company.
          </label>
          <Field label={form.key_saved ? 'API key (saved; type to replace)' : 'API key'}>
            <input type="password" value={form.key} onChange={set('key')} autoComplete="off" className={inputClass} />
          </Field>
        </div>
      </details>
      {message && <p className="text-sm text-gray-600">{message}</p>}
      <div className="flex gap-2">
        <button type="submit" className={buttonClass}>Save</button>
        <button type="button" onClick={test} className={quietButtonClass}>Save and test</button>
      </div>
    </form>
  );
}

/** Dashboard card: ask a question about your numbers. Shows only when the assistant is on. */
export function AskCard() {
  const [on, setOn] = useState(false);
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    axios.get('/api/assistant/settings').then(({ data }) => setOn(data.enabled)).catch(() => {});
  }, []);
  if (!on) return null;
  const ask = async (e) => {
    e.preventDefault();
    setBusy(true);
    setAnswer('');
    try {
      const { data } = await axios.post('/api/assistant/ask', { question });
      setAnswer(data.answer);
    } catch (err) {
      setAnswer(errorMessage(err, "Couldn't get an answer"));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-5">
      <h2 className="font-semibold text-gray-800 mb-2">Ask your numbers</h2>
      <form onSubmit={ask} className="flex gap-2">
        <input value={question} onChange={(e) => setQuestion(e.target.value)} required placeholder="e.g. Which month was best? What costs me most?" className={inputClass} />
        <button type="submit" disabled={busy} className={buttonClass}>{busy ? '…' : 'Ask'}</button>
      </form>
      {answer && <p className="mt-3 text-sm text-gray-700 whitespace-pre-wrap">{answer}</p>}
      <p className="mt-2 text-xs text-gray-400">Answers come from your own model and can be wrong: check the numbers in Money.</p>
    </div>
  );
}
