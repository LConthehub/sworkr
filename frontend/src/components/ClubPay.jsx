import { useEffect, useState } from 'react';
import axios from 'axios';
import { Field, inputClass, errorMessage } from './Modal';
import { money } from '../colors';

export const BLANK_CLUB_PAY = {
  status: 'contractor', hourly_wage: null, house_fees: [], dance_price: null, dance_house: null,
  dance_house_kind: 'amount', vip_house_percent: null, tip_outs: [],
};
const n = (v) => (v === '' || v == null ? null : Number(v));
const small = `${inputClass} !py-1.5`;

/**
 * How a club pays. Every club is different, so everything is optional: fill in what yours does.
 * `value` is the club_pay object saved on the workplace.
 */
export function ClubPayEditor({ value, onChange }) {
  const pay = { ...BLANK_CLUB_PAY, ...(value || {}) };
  const set = (patch) => onChange({ ...pay, ...patch });
  const rows = (key, i, patch) => set({ [key]: pay[key].map((r, j) => (j === i ? { ...r, ...patch } : r)) });
  const drop = (key, i) => set({ [key]: pay[key].filter((_, j) => j !== i) });

  return (
    <fieldset className="rounded-lg border border-gray-200 px-3 pt-2 pb-3 space-y-3">
      <legend className="px-1 text-xs font-medium text-gray-500">How this club pays</legend>
      <div className="flex flex-wrap gap-4 text-sm text-gray-700">
        <label className="flex items-center gap-1.5"><input type="radio" checked={pay.status === 'contractor'} onChange={() => set({ status: 'contractor' })} /> Contractor (I pay the house)</label>
        <label className="flex items-center gap-1.5"><input type="radio" checked={pay.status === 'employee'} onChange={() => set({ status: 'employee' })} /> Employee (they pay me a wage)</label>
      </div>
      {pay.status === 'employee' && (
        <Field label="Hourly wage ($)">
          <input type="number" min="0" step="0.01" value={pay.hourly_wage ?? ''} onChange={(e) => set({ hourly_wage: n(e.target.value) })} className={`${small} max-w-[8rem]`} />
        </Field>
      )}

      {pay.status === 'contractor' && (
        <div className="space-y-1.5">
          <p className="text-sm text-gray-700">House fee, by when you arrive</p>
          {pay.house_fees.map((r, i) => (
            <div key={i} className="flex items-center gap-2 text-sm">
              <span className="text-gray-500 w-16">{r.until ? 'Before' : 'After that'}</span>
              {r.until !== null && (
                <input type="time" value={r.until || ''} onChange={(e) => rows('house_fees', i, { until: e.target.value })} aria-label="Arriving before" className={`${small} w-32`} />
              )}
              <span className="text-gray-500">$</span>
              <input type="number" min="0" step="1" value={r.fee} onChange={(e) => rows('house_fees', i, { fee: Number(e.target.value) || 0 })} aria-label="House fee" className={`${small} w-24`} />
              <button type="button" onClick={() => drop('house_fees', i)} className="text-xs text-red-500 hover:text-red-700">Remove</button>
            </div>
          ))}
          <div className="flex gap-3 text-xs">
            <button type="button" onClick={() => set({ house_fees: [...pay.house_fees, { until: '21:00', fee: 0 }] })} className="text-sworkr-600 hover:text-sworkr-800">+ A time</button>
            {!pay.house_fees.some((r) => r.until === null) && (
              <button type="button" onClick={() => set({ house_fees: [...pay.house_fees, { until: null, fee: 0 }] })} className="text-sworkr-600 hover:text-sworkr-800">+ Later than that</button>
            )}
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <Field label="Dance price ($)">
          <input type="number" min="0" step="1" value={pay.dance_price ?? ''} onChange={(e) => set({ dance_price: n(e.target.value) })} className={small} />
        </Field>
        <Field label="House keeps per dance">
          <input type="number" min="0" step="0.5" value={pay.dance_house ?? ''} onChange={(e) => set({ dance_house: n(e.target.value) })} className={small} />
        </Field>
        <Field label="As">
          <select value={pay.dance_house_kind} onChange={(e) => set({ dance_house_kind: e.target.value })} className={small}>
            <option value="amount">$ each</option><option value="percent">% of each</option>
          </select>
        </Field>
        <Field label="House's VIP share (%)">
          <input type="number" min="0" max="100" step="1" value={pay.vip_house_percent ?? ''} onChange={(e) => set({ vip_house_percent: n(e.target.value) })} className={small} />
        </Field>
      </div>

      <div className="space-y-1.5">
        <p className="text-sm text-gray-700">Tip-outs <span className="text-xs text-gray-500">(DJ, house mom, security…: whoever you pay each shift)</span></p>
        {pay.tip_outs.map((t, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2 text-sm">
            <input value={t.label} onChange={(e) => rows('tip_outs', i, { label: e.target.value })} placeholder="e.g. DJ" aria-label="Who" className={`${small} w-36`} />
            <input type="number" min="0" step="0.5" value={t.value} onChange={(e) => rows('tip_outs', i, { value: Number(e.target.value) || 0 })} aria-label="How much" className={`${small} w-24`} />
            <select value={t.kind} onChange={(e) => rows('tip_outs', i, { kind: e.target.value })} aria-label="Dollars or percent" className={`${small} w-36`}>
              <option value="amount">$ a shift</option><option value="percent">% of my take</option>
            </select>
            <button type="button" onClick={() => drop('tip_outs', i)} className="text-xs text-red-500 hover:text-red-700">Remove</button>
          </div>
        ))}
        <button type="button" onClick={() => set({ tip_outs: [...pay.tip_outs, { label: '', kind: 'amount', value: 0 }] })} className="text-xs text-sworkr-600 hover:text-sworkr-800">+ A tip-out</button>
      </div>
      <p className="text-xs text-gray-500">Fill in only what your club does. Fines are added per shift, when you log it.</p>
    </fieldset>
  );
}

/** A shift at a club: arrival, hours, dances, VIP, tips, fines, worked out into a statement. */
export function ClubShift({ sourceId, onResult }) {
  const [shift, setShift] = useState({ arrived: '', hours: '', dances: '', vip: '', tips: '', fines: '' });
  const [statement, setStatement] = useState(null);
  const [error, setError] = useState('');
  const set = (k) => (e) => setShift({ ...shift, [k]: e.target.value });

  useEffect(() => {
    const t = setTimeout(async () => {
      try {
        const num = (v) => Number(v) || 0;
        const { data } = await axios.post(`/api/income-sources/${sourceId}/club-shift`, {
          arrived: shift.arrived || null, hours: num(shift.hours), dances: Math.round(num(shift.dances)),
          vip: num(shift.vip), tips: num(shift.tips), fines: num(shift.fines),
        });
        setStatement(data);
        setError('');
        if (data.gross > 0) onResult(data);
      } catch (err) {
        setError(errorMessage(err, "Couldn't work out the shift"));
      }
    }, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shift, sourceId]);

  return (
    <div className="rounded-xl bg-gray-50 p-3 space-y-2">
      <p className="text-sm font-medium text-gray-700">This shift</p>
      <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
        <Field label="Arrived"><input type="time" value={shift.arrived} onChange={set('arrived')} className={small} /></Field>
        <Field label="Hours"><input type="number" min="0" step="0.25" value={shift.hours} onChange={set('hours')} className={small} /></Field>
        <Field label="Dances"><input type="number" min="0" step="1" value={shift.dances} onChange={set('dances')} className={small} /></Field>
        <Field label="VIP ($)"><input type="number" min="0" step="1" value={shift.vip} onChange={set('vip')} className={small} /></Field>
        <Field label="Tips ($)"><input type="number" min="0" step="1" value={shift.tips} onChange={set('tips')} className={small} /></Field>
        <Field label="Fines ($)"><input type="number" min="0" step="1" value={shift.fines} onChange={set('fines')} className={small} /></Field>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {statement && statement.gross > 0 && (
        <dl className="text-sm max-w-sm">
          <div className="flex justify-between"><dt>Made</dt><dd className="tabular-nums">{money(statement.gross)}</dd></div>
          {statement.taken.map((t) => (
            <div key={t.label} className="flex justify-between pl-3 text-gray-500"><dt>{t.label}</dt><dd className="tabular-nums">− {money(t.amount)}</dd></div>
          ))}
          <div className="flex justify-between font-semibold border-t border-gray-200 mt-1 pt-1"><dt>Take home</dt><dd className="tabular-nums">{money(statement.take_home)}</dd></div>
        </dl>
      )}
    </div>
  );
}
