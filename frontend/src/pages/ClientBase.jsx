import { useEffect, useState } from 'react';
import axios from 'axios';
import { PeopleNav } from './Inquiries';

/** One group as horizontal bars: the label, a bar sized against the biggest, the count. */
function Bars({ title, bars }) {
  const most = Math.max(1, ...bars.map((b) => b.count));
  const total = bars.reduce((s, b) => s + b.count, 0);
  return (
    <section className="bg-white rounded-2xl shadow-lg p-4 sm:p-5">
      <h2 className="font-semibold text-gray-800 mb-3">{title}</h2>
      {bars.length === 0 ? <p className="text-sm text-gray-400">Nothing noted yet.</p> : (
        <ul className="space-y-1.5">
          {bars.map((b) => (
            <li key={b.label} className="grid grid-cols-[minmax(6rem,10rem)_1fr_auto] items-center gap-2 text-sm">
              <span className="truncate text-gray-700" title={b.label}>{b.label}</span>
              <span className="h-3 rounded-full bg-gray-100 overflow-hidden" aria-hidden="true">
                <span className="block h-full rounded-full bg-sworkr-500" style={{ width: `${(b.count / most) * 100}%` }} />
              </span>
              <span className="tabular-nums text-gray-600 text-xs w-16 text-right">{b.count} · {Math.round((b.count / total) * 100)}%</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Contacts > Client base: who your clients are, from their profiles. */
export default function ClientBase() {
  const [data, setData] = useState(null);
  useEffect(() => {
    axios.get('/api/client-base').then(({ data: d }) => setData(d)).catch(() => setData({ clients: 0, groups: [] }));
  }, []);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold text-white">Contacts</h1>
        <PeopleNav />
      </div>
      {data && (
        <>
          <p className="text-sm text-white/90">
            {data.clients} client{data.clients === 1 ? '' : 's'}, from what you've noted on their profiles. The more you fill in
            (birthday, how they found you, line of work, languages, how it went), the clearer this gets.
          </p>
          <div className="grid gap-4 md:grid-cols-2">
            {data.groups.map((g) => <Bars key={g.title} title={g.title} bars={g.bars} />)}
          </div>
        </>
      )}
    </div>
  );
}
