import { useState } from 'react';
import { NavLink, Navigate, useParams } from 'react-router-dom';
import Money from './Money';
import Earnings from './Earnings';
import Goals from './Goals';
import Bank from '../components/Bank';
import Payouts from '../components/Payouts';
import { PerHour, SteadyPay } from '../components/MoneyTruth';
import { useFeatures } from '../features';
import Splits from './Splits';
import TaxSummary from './TaxSummary';
import Rates from './Rates';

const TABS = [
  { id: 'overview', to: '/money', label: 'Overview' },
  { id: 'records', to: '/money/records', label: 'Income & expenses' },
  { id: 'compare', to: '/money/compare', label: 'Compare' },
  { id: 'rates', to: '/money/rates', label: 'Rates' },
  { id: 'goals', to: '/money/goals', label: 'Wallet' },
  { id: 'payouts', to: '/money/payouts', label: 'Payouts' },
  { id: 'bank', to: '/money/bank', label: 'Bank' },
  { id: 'splits', to: '/money/splits', label: 'Splits' },
  { id: 'taxes', to: '/money/taxes', label: 'Taxes' },
];

/**
 * Everything about money in one place: the year at a glance, the records behind it, comparing tours, months
 * or weeks, and savings goals.
 */
export default function MoneyHub() {
  const { tab = 'overview' } = useParams();
  const [year, setYear] = useState(new Date().getFullYear());
  const has = useFeatures();
  if (!TABS.some((t) => t.id === tab)) return <Navigate to="/money" replace />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold text-white">Money</h1>
        <nav className="flex gap-1 overflow-x-auto rounded-full bg-white/20 p-1 backdrop-blur-sm" aria-label="Money">
          {TABS.filter((t) => t.id !== 'rates' || has('rates')).map((t) => (
            <NavLink
              key={t.id}
              to={t.to}
              end
              className={({ isActive }) => `whitespace-nowrap px-3 sm:px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
                isActive ? 'bg-white text-sworkr-600 shadow' : 'text-white hover:bg-white/20'
              }`}
            >
              {t.label}
            </NavLink>
          ))}
        </nav>
      </div>
      {(tab === 'overview' || tab === 'records') && <Money view={tab} year={year} setYear={setYear} />}
      {tab === 'overview' && <div className="grid gap-4 lg:grid-cols-2 items-start"><PerHour /><SteadyPay /></div>}
      {tab === 'compare' && <Earnings />}
      {tab === 'rates' && <Rates />}
      {tab === 'goals' && <Goals />}
      {tab === 'payouts' && <Payouts />}
      {tab === 'bank' && <Bank />}
      {tab === 'splits' && <Splits />}
      {tab === 'taxes' && <TaxSummary year={year} setYear={setYear} />}
    </div>
  );
}
