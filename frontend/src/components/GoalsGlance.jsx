import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { money } from '../colors';

/** Each goal's progress at a glance, with a link to the Goals tab. */
export default function GoalsGlance({ version }) {
  const [goals, setGoals] = useState(null);
  useEffect(() => {
    axios.get('/api/goals').then(({ data }) => setGoals(data.filter((g) => !g.archived))).catch(() => setGoals([]));
  }, [version]);
  if (!goals) return null;
  const toSetAside = goals.reduce((sum, g) => sum + (g.suggested || 0), 0);
  return (
    <div className="bg-white rounded-2xl border border-line shadow-sm p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <h2 className="font-semibold text-gray-800">Savings goals</h2>
        <Link to="/money/goals" className="text-sm text-sworkr-600 hover:text-sworkr-800">
          {goals.length ? 'All goals →' : 'Start a goal →'}
        </Link>
      </div>
      {goals.length === 0 ? (
        <p className="text-sm text-gray-400">No goals yet. Set money aside for taxes, an emergency fund, gear or retirement.</p>
      ) : (
        <>
          {toSetAside > 0 && (
            <p className="text-sm text-amber-800 mb-3">Your rules say to set aside <strong>{money(toSetAside)}</strong> now.</p>
          )}
          <ul className="grid gap-3 sm:grid-cols-2">
            {goals.map((g) => (
              <li key={g.id} className="text-sm">
                <div className="flex flex-wrap items-baseline justify-between gap-x-2">
                  <span className="font-medium text-gray-800">{g.name}</span>
                  <span className="text-xs text-gray-500">
                    {money(g.balance, g.currency)}{g.target_amount ? ` of ${money(g.target_amount, g.currency)}` : ''}
                    {g.suggested > 0 && <span className="text-amber-700"> · set aside {money(g.suggested, g.currency)}</span>}
                  </span>
                </div>
                {g.target_amount ? (
                  <div className="mt-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                    <div className="h-full rounded-full" style={{ width: `${Math.max(g.progress * 100, g.balance > 0 ? 2 : 0)}%`, background: g.color || '#059669' }} />
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
