import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import Modal, { Field, inputClass, errorMessage, buttonClass, quietButtonClass } from '../components/Modal';
import CsvTools from '../components/CsvTools';
import GoalsGlance from '../components/GoalsGlance';
import { CategoryManager, CategorySelect, chargeSummary, IncomeForm, LogChargeForm, SourceForm, sourceFees } from '../components/MoneyForms';
import { SplitEditor, useSplit } from '../components/Splits';
import { downloadBlob, fetchAll, toCsv, useCategories } from '../api';
import { CHART, dayLabel, INCOME_KINDS, money, moneyShort, SOURCE_KINDS, TEST_TYPES, toDateInput } from '../colors';
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const shortDate = (iso) => dayLabel(new Date(iso), { month: 'short', day: 'numeric' });

/**
 * Income, expenses and profit for a year.
 * Income is what clients have actually paid (counted in the month of the appointment), plus other income
 * that has been paid out (payouts, tips, sales, shifts), after the venue's or platform's fees.
 */
export default function Money({ view = 'overview', year: shownYear, setYear: setShownYear }) {
  const thisYear = new Date().getFullYear();
  const [ownYear, setOwnYear] = useState(thisYear);
  // The Money page's tabs share one year; on its own, this keeps its own.
  const year = shownYear ?? ownYear;
  const setYear = setShownYear ?? setOwnYear;
  const overview = view === 'overview';
  const [appointments, setAppointments] = useState([]);
  const [expenses, setExpenses] = useState([]);
  const [clients, setClients] = useState([]);
  const [tours, setTours] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [category, setCategory] = useState('all');
  const [editing, setEditing] = useState(null); // an expense, or {} for a new one
  const [incomeRows, setIncomeRows] = useState([]);
  const [sources, setSources] = useState([]);
  const [charges, setCharges] = useState([]);
  const [modal, setModal] = useState(null); // { income } | { source } | 'categories'
  const cats = useCategories();

  const load = useCallback(async () => {
    setLoading(true);
    const range = { start: new Date(year, 0, 1).toISOString(), end: new Date(year + 1, 0, 1).toISOString() };
    try {
      const [appts, exps, inc] = await Promise.all([
        fetchAll('/api/appointments', range, 1000),
        fetchAll('/api/expenses', range, 500),
        fetchAll('/api/income', range, 1000),
      ]);
      setAppointments(appts);
      setExpenses(exps);
      setIncomeRows(inc);
      setError('');
    } catch (err) {
      if (err?.response?.status !== 401) setError("Couldn't load your numbers. Check that sworkr is running.");
    } finally {
      setLoading(false);
    }
  }, [year]);

  useEffect(() => { load(); }, [load]);
  const loadSources = useCallback(() => {
    axios.get('/api/income-sources').then(({ data }) => setSources(data)).catch(() => {});
    axios.get('/api/place-charges').then(({ data }) => setCharges(data)).catch(() => {});
  }, []);
  useEffect(() => {
    loadSources();
    cats.reload().catch(() => {});
    fetchAll('/api/clients', { sort: 'name' }, 200).then(setClients).catch(() => {});
    axios.get('/api/tours', { params: { kind: 'tour' } }).then(({ data }) => setTours(data)).catch(() => {});
  }, []);

  const figures = useMemo(() => {
    const months = MONTHS.map((label) => ({ label, income: 0, expenses: 0, visits: 0 }));
    let owed = 0;
    let ahead = 0;
    const now = new Date();
    for (const a of appointments) {
      const when = new Date(a.scheduled_date);
      const m = months[when.getMonth()];
      m.income += a.my_amount_paid ?? a.amount_paid ?? 0;   // your share, after partners'
      if (a.status === 'completed' && a.kind !== 'test') m.visits += 1;
      const unpaid = Math.max((a.rate || 0) - (a.amount_paid || 0), 0);
      if (a.status === 'completed') owed += unpaid;
      if (a.status === 'scheduled' && when >= now) ahead += unpaid;
    }
    for (const e of expenses) months[new Date(e.date).getMonth()].expenses += e.my_amount ?? e.amount;
    let pending = 0;
    for (const r of incomeRows) {
      if (r.status === 'received') months[new Date(r.date).getMonth()].income += r.my_net ?? r.net;
      else pending += r.net;
    }
    const income = months.reduce((s, m) => s + m.income, 0);
    const spent = months.reduce((s, m) => s + m.expenses, 0);
    return { months, income, spent, profit: income - spent, owed, ahead, pending };
  }, [appointments, expenses, incomeRows]);

  const unpaid = appointments
    .filter((a) => a.status === 'completed' && (a.rate || 0) > (a.amount_paid || 0))
    .sort((a, b) => a.scheduled_date.localeCompare(b.scheduled_date));
  // Picking a main category shows its subcategories' expenses too.
  const shownExpenses = expenses.filter((e) => category === 'all' || e.category === category || cats.topOf(e.category) === category);
  const totals = {};
  for (const e of expenses) totals[e.category] = (totals[e.category] || 0) + (e.my_amount ?? e.amount);
  // Totals by main category, each with what its subcategories add up to.
  const groups = {};
  for (const [key, total] of Object.entries(totals)) {
    const top = cats.topOf(key);
    groups[top] ||= { category: top, total: 0, parts: [] };
    groups[top].total += total;
    groups[top].parts.push({ category: key, total });
  }
  const byCategory = Object.values(groups).sort((a, b) => b.total - a.total);
  for (const g of byCategory) g.parts.sort((a, b) => b.total - a.total);
  // Filter chips: main categories in use this year, plus every visible one; and, once one is picked, its subcategories.
  const chips = cats.tops.filter((c) => !c.hidden || groups[c.key]).map((c) => c.key);
  for (const key of Object.keys(groups)) if (!chips.includes(key)) chips.push(key);
  const pickedTop = category === 'all' ? null : cats.topOf(category);
  const subChips = pickedTop ? cats.subsOf(pickedTop).filter((c) => !c.hidden || totals[c.key]).map((c) => c.key) : [];
  const testTotals = Object.keys(TEST_TYPES)
    .map((type) => ({ type, total: expenses.filter((e) => e.category === 'medical' && e.test_type === type).reduce((s, e) => s + e.amount, 0) }))
    .filter((t) => t.total > 0);

  const markPaid = async (a) => {
    try { await axios.post(`/api/appointments/${a.id}/mark-paid`); } catch (err) { console.error(err); }
    load();
  };
  const removeExpense = async (exp) => {
    if (!window.confirm(`Delete "${exp.description}" (${money(exp.amount)})?`)) return;
    try { await axios.delete(`/api/expenses/${exp.id}`); } catch (err) { console.error(err); }
    load();
  };

  const removeIncome = async (r) => {
    if (!window.confirm(`Delete "${r.description || INCOME_KINDS[r.kind]}" (${money(r.net)})?`)) return;
    try { await axios.delete(`/api/income/${r.id}`); } catch (err) { console.error(err); }
    load();
  };
  const markReceived = async (r) => {
    try { await axios.post(`/api/income/${r.id}/received`); } catch (err) { console.error(err); }
    load();
  };

  /** Income is listed in full (before fees) with the fees as a separate expense line, the way an accountant expects. */
  const exportYear = () => {
    const rows = [];
    let income = 0;
    let spent = 0;
    for (const a of appointments) {
      const yours = a.my_amount_paid ?? a.amount_paid;
      if (!(yours > 0)) continue;
      const how = [a.payment_method, a.partner_names && `your share; split with ${a.partner_names}`].filter(Boolean).join('; ');
      rows.push([toDateInput(new Date(a.scheduled_date)), 'Income', a.service_type, how, a.client_name || '', yours.toFixed(2), '']);
      income += yours;
    }
    for (const r of incomeRows) {
      if (r.status !== 'received') continue;
      const when = toDateInput(new Date(r.date));
      const partnersGot = (r.net ?? 0) - (r.my_net ?? r.net ?? 0);
      const kindText = r.partner_names ? `${INCOME_KINDS[r.kind]}; split with ${r.partner_names}` : INCOME_KINDS[r.kind];
      rows.push([when, 'Income', r.description || INCOME_KINDS[r.kind], kindText, r.source_name || '', (r.gross - partnersGot).toFixed(2), '']);
      income += r.gross - partnersGot;
      if (r.fees > 0) {
        rows.push([when, 'Expense', `Fees${r.source_name ? ` to ${r.source_name}` : ''}`, 'Platform and venue fees', r.source_name || '', '', r.fees.toFixed(2)]);
        spent += r.fees;
      }
    }
    for (const e of expenses) {
      const cost = e.my_amount ?? e.amount;
      const label = e.partner_names ? `${cats.fullLabel(e.category)}; your share, split with ${e.partner_names}` : cats.fullLabel(e.category);
      rows.push([toDateInput(new Date(e.date)), 'Expense', e.description, label, e.client_name || '', '', cost.toFixed(2)]);
      spent += cost;
    }
    rows.sort((a, b) => a[0].localeCompare(b[0]));
    rows.push([], ['', 'Total income', '', '', '', income.toFixed(2), '']);
    rows.push(['', 'Total expenses', '', '', '', '', spent.toFixed(2)]);
    rows.push(['', 'Profit', '', '', '', (income - spent).toFixed(2), '']);
    downloadBlob(toCsv(['Date', 'Type', 'Description', 'Category / paid by', 'Client / place', 'Income', 'Expense'], rows), `sworkr-${year}-income-and-expenses.csv`);
  };
  const shownIncome = [...incomeRows].sort((a, b) => b.date.localeCompare(a.date));

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
          <div className="flex items-center gap-2">
            <button onClick={() => setYear(year - 1)} className="w-9 h-9 rounded-lg hover:bg-gray-100 text-gray-600" aria-label="Previous year">←</button>
            <h2 className="text-xl font-bold text-gray-800">{year}</h2>
            <button onClick={() => setYear(year + 1)} disabled={year >= thisYear + 1} className="w-9 h-9 rounded-lg hover:bg-gray-100 text-gray-600 disabled:opacity-30" aria-label="Next year">→</button>
            {loading && <span className="w-4 h-4 animate-spin border-2 rounded-full border-sworkr-500/20 border-t-sworkr-500" role="status" aria-label="Loading" />}
          </div>
          <button onClick={exportYear} className={quietButtonClass} title="One file with every payment and expense this year, for your tax return or accountant">
            Export {year} for taxes (CSV)
          </button>
        </div>

        {error && <p className="mb-3 text-sm rounded-lg px-3 py-2 bg-red-50 text-red-700">{error}</p>}

        {overview ? (<>
        <dl className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3">
          <Tile label="Income" value={money(figures.income)} hint="Received, after fees" />
          <Tile label="Expenses" value={money(figures.spent)} />
          <Tile label="Profit" value={money(figures.profit)} strong negative={figures.profit < 0} />
          <Tile label="Still owed" value={money(figures.owed)} hint="Completed, not fully paid" warn={figures.owed > 0} />
          <Tile label="Booked ahead" value={money(figures.ahead)} hint="Upcoming, not yet paid" />
          <Tile label="Pending payouts" value={money(figures.pending)} hint="Earned, not paid out yet" />
        </dl>

        <MonthChart months={figures.months} year={year} />
        </>) : (
          <dl className="grid grid-cols-3 gap-3">
            <Tile label="Income" value={money(figures.income)} hint="Received, after fees" />
            <Tile label="Expenses" value={money(figures.spent)} />
            <Tile label="Profit" value={money(figures.profit)} strong negative={figures.profit < 0} />
          </dl>
        )}
      </div>

      {overview && <GoalsGlance />}

      {overview && unpaid.length > 0 && (
        <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
          <h2 className="font-semibold text-gray-800 mb-3">Still owed</h2>
          <ul className="divide-y divide-gray-100">
            {unpaid.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-3 py-2 text-sm">
                <span className="text-gray-500 w-16">{shortDate(a.scheduled_date)}</span>
                <Link to={`/contacts/${a.client_id}`} className="font-medium text-gray-800 hover:text-sworkr-600">{a.client_name || 'Unknown client'}</Link>
                <span className="text-gray-500">{a.service_type}</span>
                <span className="ml-auto text-amber-700 font-semibold">{money(a.rate - a.amount_paid)}</span>
                {a.amount_paid > 0 && <span className="text-xs text-gray-400">of {money(a.rate)}</span>}
                <button onClick={() => markPaid(a)} className="text-xs px-2.5 py-1.5 rounded-lg bg-amber-50 text-amber-800 hover:bg-amber-100">$ Mark paid</button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {!overview && (<>
      <div className="grid gap-4 lg:grid-cols-[1fr_340px] items-start">
        <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-1">
            <h2 className="font-semibold text-gray-800">Other income in {year}</h2>
            <button onClick={() => setModal({ income: null })} className="px-4 py-2 rounded-full text-sm font-medium bg-sworkr-500 text-white hover:bg-sworkr-600">+ Add income</button>
          </div>
          <p className="text-xs text-gray-500 mb-3">Payouts, tips, sales and shifts that aren't a booking on the calendar.</p>
          {shownIncome.length === 0 ? (
            <p className="text-center py-6 text-gray-400 text-sm">{loading ? 'Loading…' : `Nothing yet for ${year}.`}</p>
          ) : (
            <ul className="divide-y divide-gray-100">
              {shownIncome.map((r) => (
                <li key={r.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5">
                  <span className="text-sm text-gray-500 w-16">{shortDate(r.date)}</span>
                  <div className="flex-1 min-w-40">
                    <p className="font-medium text-sm text-gray-800">{r.description || INCOME_KINDS[r.kind]}</p>
                    <p className="text-xs text-gray-400">
                      {[r.source_name, INCOME_KINDS[r.kind], r.fees > 0 && `${money(r.gross)} − ${money(r.fees)} fees`,
                        r.partner_names && `split with ${r.partner_names}, yours ${money(r.my_net)}`].filter(Boolean).join(' · ')}
                    </p>
                  </div>
                  {r.status === 'pending' && (
                    <button onClick={() => markReceived(r)} className="text-xs px-2.5 py-1.5 rounded-lg bg-amber-50 text-amber-800 hover:bg-amber-100" title={r.payout_date ? `Expected ${r.payout_date}` : undefined}>
                      Pending · mark paid out
                    </button>
                  )}
                  <span className={`font-semibold w-24 text-right ${r.net < 0 ? 'text-red-600' : r.status === 'pending' ? 'text-gray-400' : 'text-gray-800'}`}>{money(r.net, r.currency)}</span>
                  <button onClick={() => setModal({ income: r })} className="text-xs text-sworkr-600 hover:text-sworkr-800">Edit</button>
                  <button onClick={() => removeIncome(r)} className="text-xs text-red-500 hover:text-red-700">Delete</button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-semibold text-gray-800">Places you earn</h2>
            <button onClick={() => setModal({ source: null })} className="text-sm text-sworkr-600 hover:text-sworkr-800">+ Add</button>
          </div>
          {sources.length === 0 ? (
            <p className="text-sm text-gray-400">Clubs, platforms, agencies or phone lines, with their fees. Add one, or tick how you work on the Account page.</p>
          ) : (
            <ul className="space-y-2">
              {sources.map((x) => (
                <li key={x.id} className={`rounded-xl border border-gray-100 ${x.archived ? 'opacity-60' : ''}`}>
                  <button onClick={() => setModal({ source: x })} className="w-full text-left rounded-xl px-3 py-2 hover:bg-gray-50">
                    <span className="block text-sm font-medium text-gray-800">{x.name}{x.archived && <span className="text-xs text-gray-400"> · archived</span>}</span>
                    <span className="block text-xs text-gray-500">{[SOURCE_KINDS[x.kind], sourceFees(x)].filter(Boolean).join(' · ')}</span>
                    {x.payout_note && <span className="block text-xs text-gray-400">{x.payout_note}</span>}
                  </button>
                  {charges.some((c) => c.source_id === x.id) && (
                    <ul className="border-t border-gray-100 px-3 py-1.5 space-y-1">
                      {charges.filter((c) => c.source_id === x.id).map((c) => (
                        <li key={c.id} className="flex items-center gap-2 text-xs text-gray-600">
                          <span className="flex-1">{chargeSummary(c)}</span>
                          {c.amount != null ? (
                            <button onClick={() => setModal({ charge: c })} className="text-sworkr-600 hover:text-sworkr-800" title={`Log a payment of ${c.label}`}>Log</button>
                          ) : (
                            <button onClick={() => setModal({ source: x })} className="text-gray-400 hover:text-sworkr-700">Set amount</button>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <h2 className="font-semibold text-gray-800">Expenses in {year}</h2>
          <div className="flex flex-wrap items-center gap-2">
            <button onClick={() => setModal('categories')} className={quietButtonClass}>Categories</button>
            <CsvTools kind="expenses" onImported={load} />
            <button onClick={() => setEditing({})} className="px-4 py-2 rounded-full text-sm font-medium bg-sworkr-500 text-white hover:bg-sworkr-600">+ Add expense</button>
          </div>
        </div>

        {byCategory.length > 0 && (
          <div className="mb-4 space-y-2">
            {byCategory.map((c) => {
              const parts = c.parts.filter((p) => p.category !== c.category || c.parts.length > 1);
              return (
                <div key={c.category}>
                  <div className="flex items-center gap-3 text-sm">
                    <span className="w-28 sm:w-40 text-gray-600 truncate">{cats.label(c.category)}</span>
                    <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                      <div className="h-full rounded-full" style={{ width: `${(c.total / figures.spent) * 100}%`, background: cats.color(c.category) }} />
                    </div>
                    <span className="w-24 text-right font-medium text-gray-700">{money(c.total)}</span>
                  </div>
                  {parts.length > 0 && (
                    <p className="text-xs text-gray-500 pl-1 sm:pl-[10.75rem]">
                      {parts.map((p) => `${p.category === c.category ? 'general' : cats.label(p.category).toLowerCase()} ${money(p.total)}`).join(' · ')}
                    </p>
                  )}
                </div>
              );
            })}
            {testTotals.length > 0 && (
              <p className="text-xs text-gray-500 pl-1">
                Health tests: {testTotals.map((t) => `${TEST_TYPES[t.type].replace(' test', '').toLowerCase()} ${money(t.total)}`).join(' · ')}
              </p>
            )}
          </div>
        )}

        <div className="flex flex-wrap gap-1 mb-3">
          {['all', ...chips].map((cat) => (
            <button
              key={cat}
              onClick={() => setCategory(cat)}
              aria-pressed={category === cat || pickedTop === cat}
              className={`px-3 py-1.5 rounded-full text-sm font-medium border ${
                category === cat || pickedTop === cat ? 'bg-sworkr-500/20 text-sworkr-600 border-sworkr-300' : 'text-gray-500 hover:text-gray-700 border-gray-200'
              }`}
            >
              {cat === 'all' ? 'All' : cats.label(cat)}
            </button>
          ))}
        </div>
        {subChips.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-3 pl-3 border-l-2 border-sworkr-200" aria-label={`Subcategories of ${cats.label(pickedTop)}`}>
            {subChips.map((cat) => (
              <button
                key={cat}
                onClick={() => setCategory(category === cat ? pickedTop : cat)}
                aria-pressed={category === cat}
                className={`px-2.5 py-1 rounded-full text-xs font-medium border ${
                  category === cat ? 'bg-sworkr-500/20 text-sworkr-600 border-sworkr-300' : 'text-gray-500 hover:text-gray-700 border-gray-200'
                }`}
              >
                {cats.label(cat)}
              </button>
            ))}
          </div>
        )}

        {shownExpenses.length === 0 ? (
          <p className="text-center py-6 text-gray-400 text-sm">{loading ? 'Loading…' : `No expenses${category === 'all' ? '' : ` in ${cats.label(category).toLowerCase()}`} for ${year}`}</p>
        ) : (
          <ul className="divide-y divide-gray-100">
            {shownExpenses.map((exp) => (
              <li key={exp.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5">
                <span className="text-sm text-gray-500 w-16">{shortDate(exp.date)}</span>
                <div className="flex-1 min-w-40">
                  <p className="font-medium text-sm text-gray-800">{exp.description}</p>
                  {(exp.client_name || exp.tour_name || exp.notes || exp.partner_names) && (
                    <p className="text-xs text-gray-400">{[exp.tour_name && `✈ ${exp.tour_name}`, exp.client_name,
                      exp.partner_names && `split with ${exp.partner_names}, yours ${money(exp.my_amount)}`, exp.notes].filter(Boolean).join(' · ')}</p>
                  )}
                </div>
                <span className="flex items-center gap-1.5 text-xs text-gray-600">
                  <span className="w-2.5 h-2.5 rounded-full" style={{ background: cats.color(exp.category) }} />
                  {cats.label(exp.category)}
                </span>
                <span className="font-semibold w-24 text-right text-gray-800">{money(exp.amount)}</span>
                {exp.source === 'tour_room' || exp.source === 'stay_charge' ? (
                  <Link to="/money/compare" className="text-xs text-gray-500 hover:text-sworkr-700" title={exp.source === 'stay_charge' ? "Logged for a stay from its place's charges. Change the stay or the place's charges." : 'Room & board comes from the tour. Change it there.'}>From tour</Link>
                ) : exp.appointment_id ? (
                  <Link to="/calendar" className="text-xs text-gray-500 hover:text-sworkr-700" title="This is a health test's cost. Change the test on the calendar.">From test</Link>
                ) : (
                  <>
                    <button onClick={() => setEditing(exp)} className="text-xs text-sworkr-600 hover:text-sworkr-800">Edit</button>
                    <button onClick={() => removeExpense(exp)} className="text-xs text-red-500 hover:text-red-700">Delete</button>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      </>)}

      {modal?.income !== undefined && (
        <Modal title={modal.income ? 'Edit income' : 'New income'} onClose={() => setModal(null)}>
          <IncomeForm
            income={modal.income}
            sources={sources}
            defaultDate={new Date().getFullYear() === year ? new Date() : new Date(year, 11, 31)}
            onSaved={() => { setModal(null); load(); }}
          />
        </Modal>
      )}
      {modal?.source !== undefined && (
        <Modal title={modal.source ? `Edit ${modal.source.name}` : 'New place you earn'} onClose={() => setModal(null)}>
          <SourceForm source={modal.source} onSaved={() => { setModal(null); loadSources(); load(); }} />
        </Modal>
      )}
      {modal?.charge && (
        <Modal title={`Log ${modal.charge.label} – ${modal.charge.place_name}`} onClose={() => setModal(null)}>
          <LogChargeForm charge={modal.charge} onSaved={() => { setModal(null); loadSources(); load(); }} />
        </Modal>
      )}
      {modal === 'categories' && (
        <Modal title="Expense categories" onClose={() => { setModal(null); load(); }}>
          <CategoryManager />
        </Modal>
      )}
      {editing && (
        <Modal title={editing.id ? 'Edit expense' : 'New expense'} onClose={() => setEditing(null)}>
          <ExpenseForm expense={editing.id ? editing : null} clients={clients} tours={tours} year={year} onSaved={() => { setEditing(null); load(); }} />
        </Modal>
      )}
    </div>
  );
}

function Tile({ label, value, hint, strong, warn, negative }) {
  return (
    <div className={`rounded-xl border px-3 py-2.5 ${strong ? 'border-sworkr-200 bg-sworkr-50' : 'border-gray-100'}`}>
      <dt className="text-[11px] uppercase tracking-wide text-gray-500">{label}</dt>
      <dd className={`text-xl font-bold ${negative ? 'text-red-600' : warn ? 'text-amber-700' : 'text-gray-800'}`}>{value}</dd>
      {hint && <dd className="text-[11px] text-gray-400">{hint}</dd>}
    </div>
  );
}

/** Income and expenses side by side for each month, with the same numbers in a table underneath. */
function MonthChart({ months, year }) {
  const [hover, setHover] = useState(null);
  const [showTable, setShowTable] = useState(false);
  const top = Math.max(...months.map((m) => Math.max(m.income, m.expenses)), 0);
  if (top === 0) {
    return <p className="mt-6 text-sm text-gray-400 text-center py-8">No income or expenses recorded for {year} yet. Add a rate to an appointment and mark it paid to see it here.</p>;
  }
  // A round number just above the biggest bar, for the scale.
  const magnitude = 10 ** Math.floor(Math.log10(top));
  const max = Math.ceil(top / magnitude * 2) / 2 * magnitude;
  const HEIGHT = 168;
  const bar = (value, color) => (
    <div
      className="w-2.5 sm:w-3.5"
      style={{ height: Math.max(value / max * HEIGHT, value > 0 ? 2 : 0), background: color, borderRadius: '4px 4px 0 0' }}
    />
  );

  return (
    <div className="mt-6">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-4 text-xs text-gray-600">
          <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm" style={{ background: CHART.income }} /> Income</span>
          <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm" style={{ background: CHART.expenses }} /> Expenses</span>
        </div>
        <button onClick={() => setShowTable(!showTable)} className="text-xs text-sworkr-600 hover:text-sworkr-800">
          {showTable ? 'Hide table' : 'Show as table'}
        </button>
      </div>

      <div className="flex" role="img" aria-label={`Income and expenses by month for ${year}. Use "Show as table" for the numbers.`}>
        <div className="relative w-12 shrink-0 text-[10px] text-gray-400" style={{ height: HEIGHT }}>
          {[1, 0.5, 0].map((f) => (
            <span key={f} className="absolute right-2 -translate-y-1/2" style={{ top: (1 - f) * HEIGHT }}>{moneyShort(max * f)}</span>
          ))}
        </div>
        <div className="relative flex-1">
          {[1, 0.5].map((f) => (
            <div key={f} className="absolute left-0 right-0 border-t border-gray-100" style={{ top: (1 - f) * HEIGHT }} />
          ))}
          <div className="relative flex border-b border-gray-300" style={{ height: HEIGHT }}>
            {months.map((m, i) => (
              <div
                key={m.label}
                className={`relative flex-1 flex items-end justify-center gap-0.5 ${hover === i ? 'bg-gray-50' : ''}`}
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
                onFocus={() => setHover(i)}
                onBlur={() => setHover(null)}
                tabIndex={0}
                aria-label={`${m.label}: income ${money(m.income)}, expenses ${money(m.expenses)}`}
              >
                {bar(m.income, CHART.income)}
                {bar(m.expenses, CHART.expenses)}
                {hover === i && (
                  <div className={`absolute bottom-full mb-1 z-10 w-40 rounded-lg bg-gray-900 text-white text-xs px-3 py-2 shadow-lg pointer-events-none ${i > 8 ? 'right-0' : i < 3 ? 'left-0' : 'left-1/2 -translate-x-1/2'}`}>
                    <p className="font-semibold mb-1">{m.label} {year}</p>
                    <p className="flex justify-between"><span>Income</span><span>{money(m.income)}</span></p>
                    <p className="flex justify-between"><span>Expenses</span><span>{money(m.expenses)}</span></p>
                    <p className="flex justify-between border-t border-white/20 mt-1 pt-1"><span>Profit</span><span>{money(m.income - m.expenses)}</span></p>
                  </div>
                )}
              </div>
            ))}
          </div>
          <div className="flex">
            {months.map((m) => <span key={m.label} className="flex-1 text-center text-[10px] text-gray-500 pt-1">{m.label}</span>)}
          </div>
        </div>
      </div>

      {showTable && (
        <div className="overflow-x-auto mt-4">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500 border-b border-gray-200">
                <th className="py-1.5 font-medium">Month</th>
                <th className="py-1.5 font-medium text-right">Visits</th>
                <th className="py-1.5 font-medium text-right">Income</th>
                <th className="py-1.5 font-medium text-right">Expenses</th>
                <th className="py-1.5 font-medium text-right">Profit</th>
              </tr>
            </thead>
            <tbody>
              {months.map((m) => (
                <tr key={m.label} className="border-b border-gray-50">
                  <td className="py-1.5 text-gray-700">{m.label}</td>
                  <td className="py-1.5 text-right text-gray-600">{m.visits}</td>
                  <td className="py-1.5 text-right text-gray-700">{money(m.income)}</td>
                  <td className="py-1.5 text-right text-gray-700">{money(m.expenses)}</td>
                  <td className={`py-1.5 text-right font-medium ${m.income - m.expenses < 0 ? 'text-red-600' : 'text-gray-800'}`}>{money(m.income - m.expenses)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ExpenseForm({ expense, clients, tours, year, onSaved }) {
  const [split, setSplit, saveSplit] = useSplit('expense', expense?.id);
  const today = new Date();
  // A new expense on a past year's page defaults to that year, not today.
  const defaultDate = today.getFullYear() === year ? today : new Date(year, 11, 31);
  const [form, setForm] = useState({
    description: expense?.description || '',
    amount: expense ? String(expense.amount) : '',
    category: expense?.category || 'other',
    client_id: expense?.client_id ? String(expense.client_id) : '',
    date: toDateInput(expense ? new Date(expense.date) : defaultDate),
    notes: expense?.notes || '',
    tour_id: expense?.tour_id ? String(expense.tour_id) : '',
  });
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    const amount = parseFloat(form.amount);
    if (!(amount >= 0)) return setError('Enter an amount of 0 or more');
    if (!form.date) return setError('Choose a date');
    const [y, m, d] = form.date.split('-').map(Number);
    const body = {
      description: form.description.trim(),
      amount,
      category: form.category,
      client_id: form.client_id ? Number(form.client_id) : null,
      date: new Date(y, m - 1, d, 12).toISOString(), // noon, so it stays on this day in any time zone nearby
      notes: form.notes.trim() || null,
      tour_id: form.tour_id ? Number(form.tour_id) : null,
    };
    setSaving(true);
    try {
      const { data } = expense ? await axios.put(`/api/expenses/${expense.id}`, body) : await axios.post('/api/expenses', body);
      await saveSplit(data.id);
      onSaved();
    } catch (err) {
      setError(errorMessage(err, 'Could not save the expense'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <Field label="What was it? *">
        <input required autoFocus value={form.description} onChange={set('description')} className={inputClass} />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Amount ($) *">
          <input required type="number" min="0" step="0.01" inputMode="decimal" value={form.amount} onChange={set('amount')} className={inputClass} />
        </Field>
        <Field label="Date *">
          <input required type="date" value={form.date} onChange={set('date')} className={inputClass} />
        </Field>
        <Field label="Category">
          <CategorySelect value={form.category} onChange={set('category')} />
        </Field>
        <Field label="For a client (optional)">
          <select value={form.client_id} onChange={set('client_id')} className={inputClass}>
            <option value="">No client</option>
            {clients.map((c) => <option key={c.id} value={c.id}>{c.display_name}</option>)}
          </select>
        </Field>
      </div>
      <SplitEditor split={split} onChange={setSplit} base={Number(form.amount) || 0} kind="costs" handledLabel="Who paid" />
      {tours.length > 0 && (
        <Field label="Tour (optional)">
          <select value={form.tour_id} onChange={set('tour_id')} className={inputClass}>
            <option value="">No tour (counts toward a tour if dated during it)</option>
            {[...tours].reverse().map((t) => <option key={t.id} value={t.id}>{t.name} ({t.start_date} – {t.end_date})</option>)}
          </select>
        </Field>
      )}
      <Field label="Notes">
        <textarea rows={2} value={form.notes} onChange={set('notes')} className={inputClass} />
      </Field>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex justify-end pt-1">
        <button type="submit" disabled={saving} className={buttonClass}>{saving ? 'Saving…' : expense ? 'Save changes' : 'Add expense'}</button>
      </div>
    </form>
  );
}
