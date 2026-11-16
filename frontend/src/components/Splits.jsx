import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { Field, inputClass } from './Modal';
import { fetchAll } from '../api';
import { money } from '../colors';

const shareOf = (base, p) => {
  const b = Math.max(Number(base) || 0, 0);
  const v = Number(p.share_value) || 0;
  return p.share_type === 'percent' ? (v / 100) * b : Math.min(v, b);
};

/**
 * The split on one booking, income or cost: load it (when editing), change it, save it once the record exists.
 * `split` is null until it's loaded or opened; saving a null split changes nothing.
 */
export function useSplit(recordType, recordId) {
  const [split, setSplit] = useState(null);
  useEffect(() => {
    if (!recordId) return;
    axios.get(`/api/splits/${recordType}/${recordId}`).then(({ data }) => {
      if (data.parties.length) {
        setSplit({
          handled_by: data.handled_by, agreement_id: data.agreement_id,
          parties: data.parties.map((p) => ({ partner_id: p.partner_id, share_type: p.share_type, share_value: String(p.share_value) })),
        });
      }
    }).catch(() => {});
  }, [recordType, recordId]);
  const save = useCallback(async (id) => {
    if (!split || !id) return;
    const parties = split.parties.filter((p) => p.partner_id && p.share_value !== '');
    await axios.put(`/api/splits/${recordType}/${id}`, {
      handled_by: parties.some((p) => String(p.partner_id) === String(split.handled_by)) ? Number(split.handled_by) : null,
      agreement_id: split.agreement_id || null,
      parties: parties.map((p) => ({ partner_id: Number(p.partner_id), share_type: p.share_type, share_value: Number(p.share_value) })),
    });
  }, [split, recordType]);
  return [split, setSplit, save];
}

/**
 * "Split with partners": which collaborators share this, how much each gets (a percentage or an amount), and who
 * handled the money. `kind` is booking, content or costs: it picks which share an agreement fills in.
 */
export function SplitEditor({ split, onChange, base, kind = 'booking', handledLabel = 'Who was paid' }) {
  const [partners, setPartners] = useState([]);
  const [agreements, setAgreements] = useState([]);
  const open = !!split;

  useEffect(() => {
    if (!open) return;
    fetchAll('/api/clients', { sort: 'name' }, 200).then(setPartners).catch(() => {});
    axios.get('/api/agreements').then(({ data }) => setAgreements(data.filter((a) => a.active))).catch(() => {});
  }, [open]);

  // Closed (or emptied with "Don't split", which still removes a saved split): just the button.
  if (!open || split.parties.length === 0) {
    return (
      <button type="button" onClick={() => onChange({ handled_by: null, agreement_id: null, parties: [{ partner_id: '', share_type: 'percent', share_value: '50' }] })}
        className="text-sm text-sworkr-600 hover:text-sworkr-800">
        + Split with a collaborator
      </button>
    );
  }

  const listed = partners.filter((c) => c.role === 'partner' || split.parties.some((p) => String(p.partner_id) === String(c.id)));
  const others = partners.filter((c) => !listed.includes(c));
  const set = (changes) => onChange({ ...split, ...changes });
  const setParty = (i, changes) => set({ parties: split.parties.map((p, j) => (j === i ? { ...p, ...changes } : p)) });
  const useAgreement = (id) => {
    const a = agreements.find((x) => String(x.id) === id);
    if (!a) return set({ agreement_id: null });
    set({
      agreement_id: a.id,
      parties: a.parties.map((p) => ({ partner_id: p.partner_id, share_type: 'percent', share_value: String(p[`${kind}_pct`]) })),
    });
  };
  // Same rule as the server: shares that add up to more than the money are each scaled down to fit.
  const total = Math.max(Number(base) || 0, 0);
  const asked = split.parties.map((p) => shareOf(base, p));
  const askedSum = asked.reduce((s, a) => s + a, 0);
  const scaledDown = askedSum > total + 0.005;
  const amounts = scaledDown ? asked.map((a) => (a * total) / askedSum) : asked;
  const mine = total - amounts.reduce((s, a) => s + a, 0);
  const named = split.parties.filter((p) => p.partner_id);

  return (
    <fieldset className="rounded-lg border border-sworkr-200 bg-sworkr-50/40 px-3 pt-2 pb-3 space-y-2">
      <legend className="px-1 text-xs font-medium text-sworkr-600">Split with collaborators (private: only you see this)</legend>
      {agreements.length > 0 && (
        <Field label="Use an agreement">
          <select value={split.agreement_id || ''} onChange={(e) => useAgreement(e.target.value)} className={inputClass}>
            <option value="">No agreement: set the shares here</option>
            {agreements.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </Field>
      )}
      {split.parties.map((p, i) => (
        <div key={i} className="grid grid-cols-[1fr_5.5rem_4.5rem_auto] sm:grid-cols-[1fr_6rem_4.5rem_5rem_auto] items-center gap-2">
          <select value={p.partner_id} onChange={(e) => setParty(i, { partner_id: e.target.value })} className={inputClass} aria-label="Collaborator">
            <option value="">Choose a collaborator…</option>
            {listed.map((c) => <option key={c.id} value={c.id}>{c.display_name}</option>)}
            {others.length > 0 && <optgroup label="Other contacts">{others.map((c) => <option key={c.id} value={c.id}>{c.display_name}</option>)}</optgroup>}
          </select>
          <input type="number" min="0" step="0.01" inputMode="decimal" value={p.share_value} onChange={(e) => setParty(i, { share_value: e.target.value })}
            className={inputClass} aria-label="Their share" />
          <select value={p.share_type} onChange={(e) => setParty(i, { share_type: e.target.value })} className={inputClass} aria-label="Share as">
            <option value="percent">%</option>
            <option value="amount">$</option>
          </select>
          <span className="hidden sm:block text-xs text-gray-500 text-right">{money(amounts[i])}</span>
          <button type="button" onClick={() => set({ parties: split.parties.filter((_, j) => j !== i) })} className="text-gray-300 hover:text-red-500 px-1" aria-label="Remove this collaborator">✕</button>
        </div>
      ))}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button type="button" onClick={() => set({ parties: [...split.parties, { partner_id: '', share_type: 'percent', share_value: '' }] })} className="text-xs text-sworkr-600 hover:text-sworkr-800">
          + Another collaborator
        </button>
        <button type="button" onClick={() => onChange({ handled_by: null, agreement_id: null, parties: [] })} className="text-xs text-gray-500 hover:text-red-600">
          Don't split
        </button>
      </div>
      {named.length > 0 && (
        <Field label={handledLabel}>
          <select value={split.handled_by || ''} onChange={(e) => set({ handled_by: e.target.value || null })} className={inputClass}>
            <option value="">Me</option>
            {named.map((p) => {
              const c = partners.find((x) => String(x.id) === String(p.partner_id));
              return <option key={p.partner_id} value={p.partner_id}>{c?.display_name || 'Collaborator'}</option>;
            })}
          </select>
        </Field>
      )}
      <p className="text-sm text-gray-700">
        Your share: <strong>{money(mine)}</strong>{Number(base) ? ` of ${money(base)}` : ''}
        {!Number(base) && <span className="text-xs text-gray-400"> (worked out once money is {kind === 'costs' ? 'paid' : 'received'})</span>}
      </p>
      {scaledDown && (
        <p className="text-xs text-red-600" role="alert">
          The collaborators' shares add up to {money(askedSum)}, more than the {money(total)} {kind === 'costs' ? 'paid' : 'received'}.
          Each share has been scaled down to fit, so you get nothing. Lower a share if that isn't right.
        </p>
      )}
    </fieldset>
  );
}
