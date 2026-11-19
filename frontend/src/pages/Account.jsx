import { useCallback, useEffect, useState } from 'react';
import { Link, Navigate, useLocation, useNavigate, useParams } from 'react-router-dom';
import axios from 'axios';
import { CategoryManager } from '../components/MoneyForms';
import { PersonaSettings } from '../components/Personas';
import { BlocklistSettings } from '../components/Blocklist';
import MedsSettings from '../components/Meds';
import DocumentsSettings from '../components/Documents';
import { TestKindsSettings } from '../components/TestKinds';
import { DiscreetSettings } from '../components/Discreet';
import LookSettings from '../components/Look';
import { ReceiptSettings } from '../components/Receipts';
import { SocialAccounts } from '../components/Social';
import { AssistantSettings } from '../components/Assistant';
import { WellnessSettings } from '../components/Wellness';
import { ProgressSettings } from '../components/Progress';
import { Incidents, PrivacyCheckup } from '../components/Everyday';
import DecoyPassword from '../components/Decoy';
import HomeScreenSettings from '../components/HomeScreen';
import { NutritionSettings } from '../components/MealPlanner';
import { reloadFeatures } from '../features';
import HolidaySettings from '../components/Holidays';
import { AwayFromHome, PasskeySettings, SignedInDevices, TwoStepSettings } from '../components/SignInSecurity';
import { WorkTypesPicker } from '../components/WorkTypes';
import { Field, inputClass, errorMessage, buttonClass, quietButtonClass, Section, Notice } from '../components/Modal';
import CalendarSync from '../components/CalendarSync';
import EmailSettings from '../components/EmailSettings';
import PhoneAccess from '../components/PhoneAccess';
import NtfySettings from '../components/NtfySettings';
import ContentSettings from '../components/ContentSettings';
import { CycleSettings } from '../components/Cycle';
import { notificationsSupported, reminderSettings, saveReminderSettings } from '../components/Reminders';
import { downloadBlob, isDemo } from '../api';

const idleLabel = (m) => (m === 0 ? 'Never (stay logged in for 30 days)' : m < 60 ? `${m} minutes` : m === 60 ? '1 hour' : `${m / 60} hours`);

// ==================== LAYOUT ====================

// Settings are split into groups, one shown at a time. Each section has an id, so a link like
// /account/connections#email (or an old /account#email) opens the right group and scrolls to it.
// `words` are extra search terms for the filter box.
const GROUPS = [
  {
    id: 'work', label: 'My work', icon: 'briefcase',
    sections: [
      { id: 'kinds', title: 'Kinds of work', words: 'brothel dancer cam content escort presets', render: () => <WorkTypes /> },
      { id: 'style', title: 'How I work', words: 'tours full time', render: () => <WorkStyle /> },
      {
        id: 'personas', title: 'Personas', words: 'stage name working name alias persona',
        render: () => (
          <Section title="Personas (optional)" hint="If you work under more than one name, add each here. Contacts, workplaces and platforms and posts can then say which name they're under, and Money can compare them. Skip it if you use one name.">
            <PersonaSettings />
          </Section>
        ),
      },
      { id: 'policy', title: 'Deposits & cancellations', words: 'deposit no-show no show cancellation fee late policy', render: () => <BookingPolicy /> },
      {
        id: 'documents', title: 'Licenses & documents', words: 'license work card id passport verification expiry expire renew insurance',
        render: () => (
          <Section title="Licenses & documents" hint="What runs out and when, with a reminder before it does.">
            <DocumentsSettings />
          </Section>
        ),
      },
      {
        id: 'holidays', title: 'Holidays', words: 'holiday public bank holidays calendar country state',
        render: () => <Section title="Holidays" hint="Public holidays on your calendar."><HolidaySettings /></Section>,
      },
    ],
  },
  {
    id: 'money', label: 'Money', icon: 'money',
    sections: [
      { id: 'categories', title: 'Expense categories', words: 'rename hide colour color', render: () => <ExpenseCategories /> },
      {
        id: 'receipts', title: 'Receipts', words: 'receipt invoice discreet business name client paid print pdf',
        render: () => <Section title="Receipts" hint="Plain receipts for clients who ask: your choice of name and wording, nothing about the work."><ReceiptSettings /></Section>,
      },
    ],
  },
  {
    id: 'safety', label: 'Safety', icon: 'shield',
    sections: [
      { id: 'safety', title: 'Safety check-in', words: 'trusted contact alert emergency timer push', render: () => <SafetyCheckIn /> },
      {
        id: 'baddates', title: 'Bad-date list', words: 'blocklist ugly mugs warning list blacklist dangerous clients upload',
        render: () => (
          <Section title="Bad-date list" hint="People to warn about or refuse. A contact or booking whose phone, email or handle matches shows a warning; nothing is blocked without you seeing it. Only you can see your list.">
            <BlocklistSettings />
          </Section>
        ),
      },
      {
        id: 'incidents', title: 'Incident log', words: 'incident report what happened evidence log harassment record',
        render: () => <Section title="Incident log" hint="What happened, written down the same day. Private, and never sent anywhere."><Incidents /></Section>,
      },
    ],
  },
  {
    id: 'privacy', label: 'Security & privacy', icon: 'lock',
    sections: [
      { id: 'password', title: 'Password', words: 'login', render: () => <Password /> },
      {
        id: 'passkeys', title: 'Passkeys', words: 'passkey webauthn face id fingerprint touch id windows hello biometric login',
        render: () => <Section title="Passkeys" hint="Log in with this phone or computer's face, fingerprint or PIN instead of a password."><PasskeySettings /></Section>,
      },
      {
        id: 'twostep', title: 'Two-step sign-in', words: '2fa two factor mfa code email verification authenticator app totp recovery codes',
        render: () => <Section title="Two-step sign-in" hint="A code from an app or by email after your password."><TwoStepSettings /></Section>,
      },
      {
        id: 'away', title: 'Away from home', words: 'internet public remote passkey only password off new sign-in alert email notify',
        render: () => <Section title="Away from home" hint="For when sworkr can be reached from the internet."><AwayFromHome /></Section>,
      },
      { id: 'logout', title: 'Automatic log-out', words: 'idle timeout', render: ({ onIdleChange }) => <AutoLogout onIdleChange={onIdleChange} /> },
      {
        id: 'discreet', title: 'Discreet mode', words: 'panic hide tab title privacy disguise decoy',
        render: () => (
          <Section title="Discreet mode" hint="For a shared or borrowed device, or a screen others can see.">
            <DiscreetSettings />
          </Section>
        ),
      },
      {
        id: 'decoy', noDemo: true, title: 'Decoy password', words: 'decoy duress second password forced unlock border search hide panic fake',
        render: () => <Section title="Decoy password" hint="A second password that opens a harmless account, for when someone makes you unlock Sworkr."><DecoyPassword /></Section>,
      },
      {
        id: 'checkup', title: 'Privacy check-up', words: 'privacy checklist check-up work phone location photos data brokers',
        render: () => <Section title="Privacy check-up" hint="A checklist for keeping work and private life apart."><PrivacyCheckup /></Section>,
      },
      {
        id: 'devices', noDemo: true, title: 'Signed-in devices', words: 'sessions devices log out everywhere history sign-ins activity recent',
        render: () => <Section title="Signed-in devices" hint="Where your account is open right now, and recent sign-ins."><SignedInDevices /></Section>,
      },
    ],
  },
  {
    id: 'health', label: 'Health', icon: 'heart',
    sections: [
      {
        id: 'tests', title: 'Health tests', words: 'test testing sti std screening doctor weekly monthly schedule interval cost county rules',
        render: () => <Section title="Health tests" hint="How often each test is due and what it costs, set to the rules where you work."><TestKindsSettings /></Section>,
      },
      {
        id: 'meds', title: 'Birth control & regular meds', words: 'contraception pill patch ring shot depo implant iud prep doxypep hormones hrt',
        render: () => (
          <Section title="Birth control & regular meds (optional)" hint="What you take and when: sworkr shows what's due next and reminds you of changes, shots and refills. Only you can see it.">
            <MedsSettings />
          </Section>
        ),
      },
      {
        id: 'cycle', title: 'Period tracker', words: 'cycle menstrual',
        render: () => (
          <Section title="Period tracker (optional)" hint="Off unless you turn it on, and nothing about it shows anywhere until you do. Skip it if it isn't for you.">
            <CycleSettings />
          </Section>
        ),
      },
      {
        id: 'wellness', title: 'Daily check-in', words: 'daily check-in sleep water food energy wellness health apple health',
        render: () => <Section title="Daily check-in (optional)" hint="Sleep, water, food and energy, and how they line up with your earnings."><WellnessSettings /></Section>,
      },
      {
        id: 'nutrition', title: 'Calories & macros', words: 'calories macros protein carbs fat food diet nutrition meals',
        render: () => <Section title="Calories & macros (optional)" hint="Off unless you turn it on. For meals under Calendar → Meals."><NutritionSettings /></Section>,
      },
    ],
  },
  {
    id: 'notifications', label: 'Notifications', icon: 'bell',
    sections: [
      { id: 'reminders', title: 'In this browser', words: 'notifications reminders discreet browser', render: () => <ReminderSettings /> },
      {
        id: 'ntfy', title: 'Phone notifications', words: 'ntfy push notification phone alert reminder morning summary',
        render: () => <Section title="Phone notifications (ntfy)" hint="A message on your phone before a booking, and a summary each morning."><NtfySettings /></Section>,
      },
    ],
  },
  {
    id: 'connections', label: 'Connections', icon: 'link',
    sections: [
      {
        id: 'phone', title: 'On your phone', words: 'phone iphone android mobile tailscale remote home screen app away',
        render: () => <Section title="On your phone" hint="Use sworkr from your phone, privately, and put it on your home screen like an app."><PhoneAccess /></Section>,
      },
      { id: 'email', title: 'Email', words: 'imap smtp mail inbox', render: () => <Section title="Email"><EmailSettings /></Section> },
      { id: 'calendar', title: 'Calendar & task sync', words: 'caldav nextcloud ical', render: () => <Section title="Calendar & task sync"><CalendarSync /></Section> },
      { id: 'content', title: 'Content library', words: 'folder photos videos webdav', render: () => <Section title="Content library"><ContentSettings /></Section> },
      {
        id: 'social', title: 'Social accounts', words: 'bluesky mastodon reddit social post posting accounts',
        render: () => <Section title="Social accounts" hint="Post planned posts straight to Bluesky, Mastodon or Reddit."><SocialAccounts plain /></Section>,
      },
      {
        id: 'assistant', title: 'Assistant (AI)', words: 'ai assistant llm lm studio ollama llama model local questions statistics',
        render: () => <Section title="Assistant (AI)" hint="Questions about your own numbers, answered by a model on your own computer."><AssistantSettings /></Section>,
      },
    ],
  },
  {
    id: 'look', label: 'Look', icon: 'moon',
    sections: [
      {
        id: 'theme', title: 'Light or dark', words: 'dark mode night theme light colours colors appearance',
        render: () => <Section title="Light or dark" hint="How sworkr looks on this phone or computer."><LookSettings /></Section>,
      },
      {
        id: 'homescreen', title: 'Home screen name & icon', words: 'icon home screen app name favicon discreet phone shortcut',
        render: ({ me }) => <Section title="Home screen name & icon" hint="What a phone shows when sworkr is on its home screen."><HomeScreenSettings isAdmin={!!me?.is_admin} /></Section>,
      },
      {
        id: 'progress', title: 'Progress', words: 'streaks goals badges bests gamify progress',
        render: () => <Section title="Progress" hint="Private streaks, goals you set, personal bests and badges. Never shown to anyone."><ProgressSettings /></Section>,
      },
    ],
  },
  {
    id: 'data', label: 'Data & users', icon: 'database',
    sections: [
      { id: 'backups', title: 'Backups', words: 'export restore encrypted', admin: true, render: () => <Backups /> },
      { id: 'yours', title: 'Your data', words: 'download export everything erase delete wipe remove all privacy', render: () => <YourData /> },
      { id: 'sample', title: 'Example data', words: 'demo sample', render: () => <SampleData /> },
      { id: 'users', title: 'Users', words: 'accounts people', admin: true, render: ({ me }) => <Users me={me} /> },
    ],
  },
];

const ICONS = {
  briefcase: 'M20 7h-4V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2H4a1 1 0 0 0-1 1v11a1 1 0 0 0 1 1h16a1 1 0 0 0 1-1V8a1 1 0 0 0-1-1ZM10 5h4v2h-4V5Z',
  lock: 'M7 10V7a5 5 0 0 1 10 0v3h1a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1h1Zm2 0h6V7a3 3 0 0 0-6 0v3Z',
  bell: 'M12 22a2.5 2.5 0 0 0 2.45-2h-4.9A2.5 2.5 0 0 0 12 22Zm7-6V11a7 7 0 0 0-5-6.71V4a2 2 0 0 0-4 0v.29A7 7 0 0 0 5 11v5l-2 2v1h18v-1l-2-2Z',
  link: 'M10.6 13.4a1 1 0 0 1 0-1.4l3.5-3.5a3 3 0 1 1 4.2 4.2l-2 2-1.4-1.4 2-2a1 1 0 1 0-1.4-1.4L12 13.4a1 1 0 0 1-1.4 0Zm2.8-2.8a1 1 0 0 1 0 1.4l-3.5 3.5a3 3 0 1 1-4.2-4.2l2-2 1.4 1.4-2 2a1 1 0 1 0 1.4 1.4l3.5-3.5a1 1 0 0 1 1.4 0Z',
  heart: 'M12 21s-7.5-4.6-9.5-9.2C1.1 8.5 3.2 5 6.6 5c2 0 3.4 1.1 4.4 2.5C12 6.1 13.4 5 15.4 5c3.4 0 5.5 3.5 4.1 6.8C17.5 16.4 12 21 12 21Z',
  money: 'M3 6h18a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1Zm9 3a3 3 0 1 0 0 6 3 3 0 0 0 0-6ZM5 9v6h1V9H5Zm13 0v6h1V9h-1Z',
  shield: 'M12 2 4 5v6c0 5 3.4 9.4 8 11 4.6-1.6 8-6 8-11V5l-8-3Zm-1 13.6-3.3-3.3 1.4-1.4 1.9 1.9 4.3-4.3 1.4 1.4-5.7 5.7Z',
  moon: 'M20.5 14.4A8.5 8.5 0 0 1 9.6 3.5a8.5 8.5 0 1 0 10.9 10.9Z',
  database: 'M12 3c4.4 0 8 1.3 8 3v12c0 1.7-3.6 3-8 3s-8-1.3-8-3V6c0-1.7 3.6-3 8-3Zm6 9.4c-1.5.7-3.7 1.1-6 1.1s-4.5-.4-6-1.1V15c0 .5 2.3 1.5 6 1.5s6-1 6-1.5v-2.6Zm0-4.5c-1.5.7-3.7 1.1-6 1.1s-4.5-.4-6-1.1v2.6c0 .5 2.3 1.5 6 1.5s6-1 6-1.5V7.9Z',
};

function Icon({ name, className = 'w-5 h-5' }) {
  return <svg viewBox="0 0 24 24" fill="currentColor" className={`${className} shrink-0`} aria-hidden="true"><path d={ICONS[name]} /></svg>;
}

const visibleGroups = (user) => GROUPS
  .map((g) => ({ ...g, sections: g.sections.filter((s) => (!s.admin || user.is_admin) && !(s.noDemo && isDemo())) }))
  .filter((g) => g.sections.length);

const RAIL_KEY = 'sworkr:settings-rail-collapsed';

export default function Account({ user, onLogout, onIdleChange }) {
  const { group: groupId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const groups = visibleGroups(user);
  const group = groups.find((g) => g.id === groupId);
  const [query, setQuery] = useState('');
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(RAIL_KEY) === '1'; } catch { return false; }
  });
  const toggleRail = () => setCollapsed((c) => {
    try { localStorage.setItem(RAIL_KEY, c ? '0' : '1'); } catch { /* not remembered, that's fine */ }
    return !c;
  });

  // Old links (/account#email) and links to the wrong group still find their section.
  const hash = location.hash.slice(1);
  const owner = hash && groups.find((g) => g.sections.some((s) => s.id === hash));

  // Scroll to #section once the group has drawn it.
  useEffect(() => {
    if (!hash || !group) return undefined;
    // Again a little later: sections above it load their settings and grow, pushing it down.
    const go = () => document.getElementById(hash)?.scrollIntoView({ behavior: 'smooth' });
    const timers = [setTimeout(go, 300), setTimeout(go, 1000)];
    return () => timers.forEach(clearTimeout);
  }, [hash, group]);

  if (owner && owner.id !== groupId) return <Navigate to={`/account/${owner.id}#${hash}`} replace />;
  if (groupId && !group) return <Navigate to="/account" replace />;

  const q = query.trim().toLowerCase();
  const matches = q
    ? groups.flatMap((g) => g.sections
      .filter((s) => `${s.title} ${s.words || ''} ${g.label}`.toLowerCase().includes(q))
      .map((s) => ({ group: g, section: s })))
    : null;
  const open = (g, s) => {
    setQuery('');
    navigate(s ? `/account/${g.id}#${s.id}` : `/account/${g.id}`);
  };

  // On a phone, /account is the list of groups and a group opens on its own page.
  // On a wider screen the rail is always there and /account shows the first group.
  const shown = group || groups[0];

  const search = (
    <input
      type="search"
      value={query}
      onChange={(e) => setQuery(e.target.value)}
      placeholder="Find a setting"
      aria-label="Find a setting"
      className={inputClass}
    />
  );
  const results = matches && (
    <ul className="space-y-1">
      {matches.length === 0 && <li className="px-3 py-2 text-sm text-gray-500">Nothing matches “{query}”.</li>}
      {matches.map(({ group: g, section: s }) => (
        <li key={`${g.id}-${s.id}`}>
          <button type="button" onClick={() => open(g, s)} className="w-full text-left px-3 py-2 rounded-lg hover:bg-sworkr-50 text-sm">
            <span className="text-gray-800">{s.title}</span>
            <span className="block text-xs text-gray-500">{g.label}</span>
          </button>
        </li>
      ))}
    </ul>
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-white">Settings</h1>
          <p className="text-sm text-white/90">Logged in as <span className="font-semibold">{user.username}</span>{user.is_admin && ' (admin)'}</p>
        </div>
        <button onClick={onLogout} className="px-4 py-2 rounded-lg bg-white/20 text-white hover:bg-white/30 text-sm">Log out</button>
      </div>

      {/* Phone: the list of groups, until one is picked. */}
      {!group && (
        <div className="md:hidden bg-white rounded-2xl shadow-lg p-3 space-y-3">
          {search}
          {results || (
            <ul className="divide-y divide-gray-100">
              {groups.map((g) => (
                <li key={g.id}>
                  <Link to={`/account/${g.id}`} className="flex items-center gap-3 px-2 py-3 text-gray-800">
                    <Icon name={g.icon} className="w-5 h-5 text-sworkr-600" />
                    <span className="flex-1">
                      <span className="block font-medium">{g.label}</span>
                      <span className="block text-xs text-gray-500">{g.sections.map((s) => s.title).join(', ')}</span>
                    </span>
                    <span className="text-gray-400" aria-hidden="true">›</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className={`${group ? '' : 'hidden md:grid'} md:grid gap-4 items-start ${collapsed ? 'md:grid-cols-[3.5rem_1fr]' : 'md:grid-cols-[13rem_1fr]'}`}>
        {/* Wider screens: the rail. */}
        <nav aria-label="Settings" className="hidden md:block sticky top-20 bg-white rounded-2xl shadow-lg p-2 space-y-2">
          {!collapsed && search}
          {!collapsed && results}
          {!results && (
            <ul className="space-y-1">
              {groups.map((g) => {
                const active = g.id === shown.id;
                return (
                  <li key={g.id}>
                    <Link
                      to={`/account/${g.id}`}
                      title={collapsed ? g.label : undefined}
                      aria-current={active ? 'page' : undefined}
                      className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm ${collapsed ? 'justify-center px-0' : ''} ${
                        active ? 'bg-sworkr-50 text-sworkr-700 font-semibold' : 'text-gray-700 hover:bg-gray-50'
                      }`}
                    >
                      <Icon name={g.icon} />
                      {!collapsed && <span>{g.label}</span>}
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
          <button
            type="button"
            onClick={toggleRail}
            className={`w-full rounded-lg text-gray-500 hover:text-gray-800 hover:bg-gray-50 ${collapsed ? 'py-2 text-lg leading-none' : 'py-1 text-xs'}`}
            aria-label={collapsed ? 'Show the settings menu' : 'Shrink the settings menu'}
            title={collapsed ? 'Show the settings menu' : 'Shrink the settings menu'}
          >
            {collapsed ? '»' : '« Shrink'}
          </button>
        </nav>

        <div className="space-y-4 max-w-2xl min-w-0">
          <Link to="/account" className="md:hidden inline-flex items-center gap-1 text-sm text-white hover:underline">‹ All settings</Link>
          <h2 className="text-lg font-semibold text-white flex items-center gap-2"><Icon name={shown.icon} />{shown.label}</h2>
          {shown.sections.map((s) => (
            <div key={s.id} id={s.id} className="scroll-mt-20">
              {s.render({ onIdleChange, me: user })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function BookingPolicy() {
  const [form, setForm] = useState(null);
  const [message, setMessage] = useState(null);
  useEffect(() => {
    axios.get('/api/booking-policy').then(({ data }) => setForm(Object.fromEntries(Object.entries(data).map(([k, v]) => [k, String(v)])))).catch(() => {});
  }, []);
  if (!form) return null;
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const save = async (e) => {
    e.preventDefault();
    setMessage(null);
    try {
      await axios.put('/api/booking-policy', Object.fromEntries(Object.entries(form).map(([k, v]) => [k, Number(v) || 0])));
      setMessage({ ok: 'Saved.' });
    } catch (err) {
      setMessage({ error: errorMessage(err, 'Could not save') });
    }
  };
  const num = (k, props) => <input type="number" min="0" step="1" inputMode="decimal" value={form[k]} onChange={set(k)} className={inputClass} {...props} />;
  return (
    <Section title="Deposits & cancellations" hint="Suggests a deposit when you book, and a fee when a client cancels late or doesn't turn up. You can change the fee every time.">
      <form onSubmit={save} className="space-y-3">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Field label="Deposit (% of rate)">{num('deposit_percent', { max: 100 })}</Field>
          <Field label="Late means within (hours)">{num('late_cancel_hours', { max: 336 })}</Field>
          <Field label="Late cancellation fee (%)">{num('late_cancel_fee_percent', { max: 100 })}</Field>
          <Field label="No-show fee (%)">{num('no_show_fee_percent', { max: 100 })}</Field>
        </div>
        <Notice message={message} />
        <button type="submit" className={buttonClass}>Save</button>
      </form>
    </Section>
  );
}

function ExpenseCategories() {
  return (
    <Section title="Expense categories">
      <CategoryManager />
    </Section>
  );
}

// ==================== SAMPLE DATA ====================

function SampleData() {
  const [status, setStatus] = useState(null);
  const [message, setMessage] = useState(null);

  useEffect(() => {
    axios.get('/api/sample-data').then(({ data }) => setStatus(data)).catch(() => {});
  }, []);

  if (!status) return null;
  if (!status.present && !message) {
    return <Section title="Example data" hint="The made-up clients, appointments and expenses sworkr started with have been removed." />;
  }

  const remove = async () => {
    if (!window.confirm('Delete the example clients, their appointments and the example expenses? Anything you added yourself stays.')) return;
    try {
      const { data } = await axios.delete('/api/sample-data');
      setStatus({ present: false });
      setMessage({ ok: `Removed ${data.clients} example clients, ${data.appointments} appointments and ${data.expenses} expenses.` });
      window.dispatchEvent(new Event('sworkr:appointments-changed'));
    } catch (err) {
      setMessage({ error: errorMessage(err, 'Could not remove the sample data') });
    }
  };

  return (
    <Section title="Example data" hint="sworkr started with a few made-up clients, appointments and expenses so there was something to look at.">
      <div className="space-y-3">
        <Notice message={message} />
        {status?.present && (
          <button onClick={remove} className={quietButtonClass}>
            Remove the example data ({status.clients} clients, {status.expenses} expenses)
          </button>
        )}
      </div>
    </Section>
  );
}

// ==================== PASSWORD ====================

function Password() {
  const [form, setForm] = useState({ current: '', next: '', confirm: '' });
  const [message, setMessage] = useState(null);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setMessage(null);
    if (form.next !== form.confirm) return setMessage({ error: "New passwords don't match" });
    try {
      await axios.post('/api/auth/change-password', { current_password: form.current, new_password: form.next });
      setForm({ current: '', next: '', confirm: '' });
      setMessage({ ok: 'Password changed. Any other devices have been logged out.' });
    } catch (err) {
      setMessage({ error: errorMessage(err, 'Could not change password') });
    }
  };

  return (
    <Section title="Password">
      <form onSubmit={submit} className="space-y-3">
        <Field label="Current password">
          <input required type="password" autoComplete="current-password" value={form.current} onChange={set('current')} className={inputClass} />
        </Field>
        <div className="grid sm:grid-cols-2 gap-3">
          <Field label="New password">
            <input required type="password" minLength={12} autoComplete="new-password" value={form.next} onChange={set('next')} className={inputClass} />
          </Field>
          <Field label="Confirm new password">
            <input required type="password" autoComplete="new-password" value={form.confirm} onChange={set('confirm')} className={inputClass} />
          </Field>
        </div>
        <Notice message={message} />
        <button type="submit" className={buttonClass}>Change password</button>
        <p className="text-xs text-gray-400">
          Forgot it? On the computer sworkr runs on, open a terminal in the sworkr folder and run{' '}
          <code className="bg-gray-100 px-1 rounded">docker compose exec sworkr python manage.py reset-password</code>
        </p>
      </form>
    </Section>
  );
}

// ==================== HOW I WORK ====================

const WORK_STYLES = [
  { value: 'tours', label: 'On tours', hint: 'Earnings opens on your tours.' },
  { value: 'full_time', label: 'Full time, in one place', hint: 'Earnings opens by month, and Tour is left out of the + New menu.' },
  { value: 'both', label: 'Both', hint: 'Everything is shown.' },
];

function ShowEverything() {
  const [on, setOn] = useState(null);
  useEffect(() => { axios.get('/api/work-profile').then(({ data }) => setOn(!!data.show_everything)).catch(() => {}); }, []);
  if (on === null) return null;
  const toggle = async (e) => {
    const { data } = await axios.put('/api/work-profile/show-everything', { show_everything: e.target.checked });
    setOn(data.show_everything);
    reloadFeatures();
  };
  return (
    <label className="mt-3 flex items-start gap-2 text-sm text-gray-700">
      <input type="checkbox" checked={on} onChange={toggle} className="mt-1" />
      <span>Show everything<span className="block text-xs text-gray-500">Parts of sworkr that don't fit your kinds of work are tucked away. Tick this to see them all.</span></span>
    </label>
  );
}

function WorkTypes() {
  return (
    <Section title="Kinds of work" hint="Tick everything you do. sworkr shows the parts that fit, and adds starter expense categories, workplaces and platforms.">
      <WorkTypesPicker />
      <ShowEverything />
    </Section>
  );
}

function WorkStyle() {
  const [style, setStyle] = useState(null);
  const [message, setMessage] = useState(null);

  useEffect(() => {
    axios.get('/api/account/settings').then(({ data }) => setStyle(data.work_style)).catch(() => {});
  }, []);

  const change = async (value) => {
    setMessage(null);
    try {
      const { data } = await axios.put('/api/account/settings', { work_style: value });
      setStyle(data.work_style);
      setMessage({ ok: 'Saved.' });
    } catch (err) {
      setMessage({ error: errorMessage(err, 'Could not save') });
    }
  };

  if (!style) return null;
  return (
    <Section title="How I work" hint="Changes what sworkr shows first. Tours, time off and every comparison stay available either way.">
      <div className="space-y-2">
        {WORK_STYLES.map((w) => (
          <label key={w.value} className="flex items-start gap-2 text-sm text-gray-700">
            <input type="radio" name="work_style" checked={style === w.value} onChange={() => change(w.value)} className="mt-1" />
            <span>{w.label}<span className="block text-xs text-gray-500">{w.hint}</span></span>
          </label>
        ))}
        <Notice message={message} />
      </div>
    </Section>
  );
}

// ==================== AUTO LOG-OUT ====================

function AutoLogout({ onIdleChange }) {
  const [settings, setSettings] = useState(null);
  const [message, setMessage] = useState(null);

  useEffect(() => {
    axios.get('/api/account/settings').then(({ data }) => setSettings(data)).catch(() => {});
  }, []);

  const change = async (e) => {
    const idle_minutes = Number(e.target.value);
    setMessage(null);
    try {
      const { data } = await axios.put('/api/account/settings', { idle_minutes });
      setSettings(data);
      onIdleChange?.(data.idle_minutes);
      setMessage({ ok: 'Saved.' });
    } catch (err) {
      setMessage({ error: errorMessage(err, 'Could not save') });
    }
  };

  if (!settings) return null;
  return (
    <Section title="Automatic log-out" hint="If sworkr is left open and unused for this long, it logs you out and hides everything.">
      <div className="space-y-3">
        <Field label="Log me out after">
          <select value={settings.idle_minutes} onChange={change} className={inputClass}>
            {settings.idle_choices.map((m) => <option key={m} value={m}>{idleLabel(m)}</option>)}
          </select>
        </Field>
        <Notice message={message} />
      </div>
    </Section>
  );
}

// ==================== SAFETY CHECK-IN ====================

function SafetyCheckIn() {
  const [form, setForm] = useState(null);
  const [status, setStatus] = useState(null);
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState('');
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });

  useEffect(() => {
    axios.get('/api/safety').then(({ data }) => {
      setStatus(data);
      setForm({ contact_name: data.contact_name, contact_email: data.contact_email, grace_minutes: data.grace_minutes,
                include_details: data.include_details, instructions: data.instructions, contact_push: data.contact_push || '' });
    }).catch(() => {});
  }, []);

  if (!form) return null;

  const save = async (e) => {
    e.preventDefault();
    setBusy('save');
    setMessage(null);
    try {
      const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
      const { data } = await axios.put('/api/safety', { ...form, grace_minutes: Number(form.grace_minutes), timezone });
      setStatus(data);
      setMessage({ ok: data.armed ? 'Saved. Alerts are switched on.' : 'Saved.' });
    } catch (err) {
      setMessage({ error: errorMessage(err, 'Could not save') });
    } finally {
      setBusy('');
    }
  };

  const test = async () => {
    setBusy('test');
    setMessage(null);
    try {
      const { data } = await axios.post('/api/safety/test');
      setMessage({ ok: `Test email sent to ${data.sent_to}. Ask them to check it arrived (and their spam folder).` });
    } catch (err) {
      setMessage({ error: errorMessage(err, 'The test email could not be sent') });
    } finally {
      setBusy('');
    }
  };

  return (
    <Section
      title="Safety check-in"
      hint="Tick “Safety check-in” on an appointment. If you don't check in after it ends, sworkr emails someone you trust."
    >
      <form onSubmit={save} className="space-y-3">
        <div className={`text-sm rounded-lg px-3 py-2 ${status.armed ? 'bg-emerald-50 text-emerald-800' : 'bg-amber-50 text-amber-900'}`}>
          {status.armed ? (
            <>Alerts are <strong>on</strong>. They go to {status.contact_name || status.contact_email}.</>
          ) : !status.email_configured ? (
            <>
              Alerts are <strong>off</strong>: sworkr has no email account to send from yet. Copy <code>.env.example</code> to{' '}
              <code>.env</code> in the sworkr folder, fill in the email settings, and restart sworkr. Until then you'll only be reminded inside the app.
            </>
          ) : (
            <>Alerts are <strong>off</strong>: add your trusted contact's email below.</>
          )}
        </div>

        <div className="grid sm:grid-cols-2 gap-3">
          <Field label="Trusted contact's name">
            <input value={form.contact_name} onChange={set('contact_name')} className={inputClass} />
          </Field>
          <Field label="Their email">
            <input type="email" value={form.contact_email} onChange={set('contact_email')} className={inputClass} />
          </Field>
        </div>
        <Field label="Push to their phone (faster than email)">
          <input value={form.contact_push} onChange={set('contact_push')} placeholder="https://ntfy.sh/a-long-random-name" autoComplete="off" className={inputClass} />
          <span className="block text-xs text-gray-500 mt-1">
            Your contact installs the free ntfy app and subscribes to a long, random name you agree on; put the full address here.
            The alert reaches them in seconds, and it also powers the safety timer on your dashboard. Use Send a test below.
          </span>
        </Field>
        <Field label="Email them if I haven't checked in this long after the appointment ends">
          <select value={form.grace_minutes} onChange={set('grace_minutes')} className={inputClass}>
            {status.grace_choices.map((m) => <option key={m} value={m}>{m} minutes</option>)}
          </select>
        </Field>
        <Field label="What should they do? (included in the email)">
          <textarea rows={2} maxLength={500} value={form.instructions} onChange={set('instructions')} placeholder="e.g. Call me. If I don't answer in 10 minutes, call …" className={inputClass} />
        </Field>
        <label className="flex items-start gap-2 text-sm text-gray-700">
          <input type="checkbox" className="mt-1" checked={form.include_details} onChange={set('include_details')} />
          <span>
            Include the appointment details
            <span className="block text-xs text-gray-500">The client's name and phone number, the place and the start time. Without this, the email only says you haven't checked in.</span>
          </span>
        </label>

        <Notice message={message} />
        {status.last_error && <p className="text-xs text-red-600">Last alert problem: {status.last_error}</p>}

        <div className="flex flex-wrap gap-2">
          <button type="submit" disabled={!!busy} className={buttonClass}>{busy === 'save' ? 'Saving…' : 'Save'}</button>
          <button type="button" onClick={test} disabled={!!busy || !status.armed} className={quietButtonClass} title={status.armed ? '' : 'Save a contact and set up email first'}>
            {busy === 'test' ? 'Sending…' : 'Send a test email'}
          </button>
        </div>
        <p className="text-xs text-gray-500">
          The alert is sent by this computer, so it only works while sworkr is running and online. Treat it as a backup, not your only safety plan.
        </p>
      </form>
    </Section>
  );
}

// ==================== REMINDERS ====================

function ReminderSettings() {
  const [settings, setSettings] = useState(reminderSettings);
  const [message, setMessage] = useState(null);
  const supported = notificationsSupported();

  const update = (changes) => {
    const next = { ...settings, ...changes };
    setSettings(next);
    saveReminderSettings(next);
  };

  const toggle = async (e) => {
    setMessage(null);
    if (!e.target.checked) return update({ enabled: false });
    const permission = Notification.permission === 'granted' ? 'granted' : await Notification.requestPermission();
    if (permission !== 'granted') {
      return setMessage({ error: 'Your browser is blocking notifications for this page. Allow them in the address bar, then try again.' });
    }
    update({ enabled: true });
  };

  return (
    <Section title="Notifications in this browser" hint="A notification on this computer before each appointment, and when a post or ad is due. It only works in this browser, while sworkr is open in a tab.">
      {!supported ? (
        <p className="text-sm text-gray-500">This browser doesn't support notifications.</p>
      ) : (
        <div className="space-y-3">
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input type="checkbox" checked={settings.enabled && Notification.permission === 'granted'} onChange={toggle} />
            Remind me before appointments
          </label>
          {settings.enabled && (
            <>
              <Field label="How long before">
                <select value={settings.minutes} onChange={(e) => update({ minutes: Number(e.target.value) })} className={inputClass}>
                  {[15, 30, 60, 120].map((m) => <option key={m} value={m}>{m < 60 ? `${m} minutes` : `${m / 60} hour${m > 60 ? 's' : ''}`}</option>)}
                </select>
              </Field>
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input type="checkbox" checked={settings.posts} onChange={(e) => update({ posts: e.target.checked })} />
                Also remind me when a post or ad renewal is due
              </label>
              <label className="flex items-start gap-2 text-sm text-gray-700">
                <input type="checkbox" className="mt-1" checked={settings.discreet} onChange={(e) => update({ discreet: e.target.checked })} />
                <span>
                  Discreet
                  <span className="block text-xs text-gray-500">The notification only says “Appointment soon” or “Reminder” and the time, with no names or sites.</span>
                </span>
              </label>
            </>
          )}
          <Notice message={message} />
        </div>
      )}
    </Section>
  );
}

// ==================== BACKUPS (admin) ====================

function Backups() {
  const [status, setStatus] = useState(null);
  const [passphrase, setPassphrase] = useState('');
  const [autoPassphrase, setAutoPassphrase] = useState('');
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState('');

  const load = useCallback(() => {
    axios.get('/api/backup').then(({ data }) => setStatus(data)).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);

  const run = async (what, fn) => {
    setBusy(what);
    setMessage(null);
    try {
      await fn();
    } catch (err) {
      let text = errorMessage(err, 'Something went wrong');
      // A failed download comes back as a file-like blob; read the real message out of it.
      if (err?.response?.data instanceof Blob) {
        try { text = JSON.parse(await err.response.data.text()).detail || text; } catch { /* keep the fallback */ }
      }
      setMessage({ error: text });
    } finally {
      setBusy('');
    }
  };

  const download = (e) => {
    e.preventDefault();
    run('download', async () => {
      const response = await axios.post('/api/backup/download', { passphrase }, { responseType: 'blob' });
      const name = /filename="([^"]+)"/.exec(response.headers['content-disposition'] || '')?.[1] || 'sworkr-backup.swbak';
      downloadBlob(response.data, name);
      setPassphrase('');
      setMessage({ ok: `Saved ${name}. Keep it somewhere other than this computer, and remember the passphrase: without it the file can't be opened.` });
    });
  };

  const saveAuto = (enabled) => run('auto', async () => {
    const { data } = await axios.put('/api/backup/auto', { enabled, passphrase: autoPassphrase });
    setStatus(data);
    setAutoPassphrase('');
    setMessage(data.last_error
      ? { error: `Automatic backups are on, but the first one failed: ${data.last_error}` }
      : { ok: enabled ? 'Automatic backups are on. The first one was just made.' : 'Automatic backups are off.' });
  });

  if (!status) return null;
  return (
    <Section title="Backups" hint="An encrypted copy of everything in sworkr. Without the passphrase, nobody can read it.">
      <div className="space-y-5">
        <form onSubmit={download} className="space-y-2">
          <Field label="Download a backup now. Choose a passphrase (at least 10 characters)">
            <input type="password" required minLength={10} autoComplete="new-password" value={passphrase} onChange={(e) => setPassphrase(e.target.value)} className={inputClass} />
          </Field>
          <button type="submit" disabled={!!busy} className={buttonClass}>{busy === 'download' ? 'Preparing…' : 'Download backup'}</button>
        </form>

        <div className="border-t border-gray-100 pt-4 space-y-2">
          <p className="text-sm font-medium text-gray-700">
            Automatic daily backups: {status.auto_enabled ? <span className="text-emerald-700">on</span> : <span className="text-gray-500">off</span>}
          </p>
          <p className="text-xs text-gray-500">
            Saved every day into the <code className="bg-gray-100 px-1 rounded">backups</code> folder inside your sworkr folder. The newest {status.keep} are kept.
            {status.auto_enabled && (
              <> {status.files} there now{status.last_backup_at && <>, the latest from {new Date(status.last_backup_at).toLocaleString()}</>}.</>
            )}
          </p>
          {status.last_error && <p className="text-xs text-red-600">Last problem: {status.last_error}</p>}
          <Field label={status.auto_enabled ? 'New passphrase (leave empty to keep the current one)' : 'Passphrase for the automatic backups (at least 10 characters)'}>
            <input type="password" minLength={10} autoComplete="new-password" value={autoPassphrase} onChange={(e) => setAutoPassphrase(e.target.value)} className={inputClass} />
          </Field>
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={!!busy || (!status.auto_enabled && autoPassphrase.length < 10)} onClick={() => saveAuto(true)} className={buttonClass}>
              {busy === 'auto' ? 'Working…' : status.auto_enabled ? 'Update' : 'Turn on'}
            </button>
            {status.auto_enabled && (
              <button type="button" disabled={!!busy} onClick={() => saveAuto(false)} className={quietButtonClass}>Turn off</button>
            )}
          </div>
          <p className="text-xs text-gray-500">
            That folder is on the same computer as sworkr, so copy the files somewhere else now and then (a USB stick, or cloud storage).
            To restore one: <code className="bg-gray-100 px-1 rounded">docker compose exec sworkr python manage.py restore-backup /backups/&lt;file&gt;</code>
          </p>
        </div>
        <Notice message={message} />
        <OffsiteBackups autoOn={status.auto_enabled} />
      </div>
    </Section>
  );
}

function OffsiteBackups({ autoOn }) {
  const [status, setStatus] = useState(null);
  const [form, setForm] = useState({ url: '', username: '', password: '' });
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState(null);
  const apply = (data) => {
    setStatus(data);
    setForm({ url: data.url || '', username: data.username || '', password: '' });
  };
  useEffect(() => { axios.get('/api/backup/offsite').then(({ data }) => apply(data)).catch(() => {}); }, [autoOn]);

  const run = async (what, action) => {
    setBusy(what);
    setMessage(null);
    try {
      await action();
    } catch (err) {
      setMessage({ error: errorMessage(err, "That didn't work") });
    } finally {
      setBusy('');
    }
  };
  const save = (e) => {
    e.preventDefault();
    run('save', async () => {
      const { data } = await axios.put('/api/backup/offsite', { enabled: true, ...form });
      apply(data);
      setMessage(data.last_error
        ? { error: `Saved, but the copy failed: ${data.last_error}` }
        : { ok: data.last_file ? `Off-site copies are on. ${data.last_file} is there now.` : 'Off-site copies are on. The next automatic backup will be sent there.' });
    });
  };
  const turnOff = () => run('off', async () => {
    const { data } = await axios.put('/api/backup/offsite', { enabled: false });
    apply(data);
    setMessage({ ok: 'Off-site copies are off. Files already sent stay where they are.' });
  });
  const test = () => run('test', async () => {
    const { data } = await axios.post('/api/backup/verify');
    setStatus(data);
    setMessage(data.result.ok
      ? { ok: `${data.result.file} opened and checked out fine.` }
      : { error: `${data.result.file} could not be restored: ${data.result.error}` });
  });

  if (!status) return null;
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });
  return (
    <>
      <form onSubmit={save} className="border-t border-gray-100 pt-4 space-y-2">
        <p className="text-sm font-medium text-gray-700">
          Copies off this computer: {status.enabled ? <span className="text-emerald-700">on</span> : <span className="text-gray-500">off</span>}
        </p>
        <p className="text-xs text-gray-500">
          Each automatic backup is also sent to a folder on your Nextcloud (or any WebDAV server), so a fire, a theft or a dead disk doesn't take the backups with it.
          The file is encrypted before it leaves: that server can't read it.
          {status.last_at && <> Last sent {new Date(status.last_at).toLocaleString()}.</>}
        </p>
        {status.last_error && <p className="text-xs text-red-600">Last problem: {status.last_error}</p>}
        <Field label="Folder address (WebDAV)">
          <input type="url" required placeholder="https://cloud.example.com/remote.php/dav/files/you/sworkr-backups" value={form.url} onChange={set('url')} className={inputClass} />
        </Field>
        <Field label="Username">
          <input type="text" required autoComplete="off" value={form.username} onChange={set('username')} className={inputClass} />
        </Field>
        <Field label={status.has_password ? 'App password (leave empty to keep the saved one)' : 'App password (make one in Nextcloud: Settings, Security)'}>
          <input type="password" required={!status.has_password} autoComplete="new-password" value={form.password} onChange={set('password')} className={inputClass} />
        </Field>
        <div className="flex flex-wrap gap-2">
          <button type="submit" disabled={!!busy} className={buttonClass}>{busy === 'save' ? 'Trying the folder…' : status.enabled ? 'Update' : 'Turn on'}</button>
          {status.enabled && <button type="button" disabled={!!busy} onClick={turnOff} className={quietButtonClass}>Turn off</button>}
        </div>
        {!autoOn && <p className="text-xs text-amber-700">Automatic daily backups are off, so there is nothing to send yet. Turn them on above.</p>}
      </form>

      <div className="border-t border-gray-100 pt-4 space-y-2">
        <p className="text-sm font-medium text-gray-700">Restore test</p>
        <p className="text-xs text-gray-500">
          About every {status.verify_every_days} days sworkr opens the newest backup with the saved passphrase and checks it, so you know it would really restore.
          {status.verified_at
            ? <> Last tested {new Date(status.verified_at).toLocaleString()}{status.verified_file && <> ({status.verified_file})</>}: {status.verify_error ? 'it failed.' : 'it was fine.'}</>
            : <> Not tested yet.</>}
        </p>
        {status.verify_error && <p className="text-xs text-red-600">Problem: {status.verify_error}</p>}
        <button type="button" disabled={!!busy || !autoOn} onClick={test} className={quietButtonClass}>{busy === 'test' ? 'Testing…' : 'Test the newest backup now'}</button>
      </div>
      <Notice message={message} />
      <RestoreBackup />
    </>
  );
}

function RestoreBackup() {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState(null);
  const [form, setForm] = useState({ passphrase: '', password: '', confirm: '' });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  const restore = async (e) => {
    e.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary = '';
      for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
      await axios.post('/api/backup/restore', { file: btoa(binary), ...form });
      window.location.assign('/');   // everyone is signed out: sign in again with the account from the backup
    } catch (err) {
      setMessage({ error: err.response?.status === 413
        ? 'That backup is too big to restore from this page. Use the command in the README instead.'
        : errorMessage(err, 'Nothing was restored') });
      setBusy(false);
    }
  };

  return (
    <div className="border-t border-gray-100 pt-4 space-y-2">
      <p className="text-sm font-medium text-gray-700">Restore a backup</p>
      <p className="text-xs text-gray-500">
        Replaces everything in sworkr, for every account, with what is in a backup file. What is here now is kept as a copy next to the database, in case you need to go back.
      </p>
      {!open ? (
        <button type="button" onClick={() => setOpen(true)} className="text-sm text-red-600 hover:text-red-800 underline">Restore a backup…</button>
      ) : (
        <form onSubmit={restore} className="space-y-2 rounded-lg border border-red-200 bg-red-50 p-3">
          <Field label="Backup file (.swbak)">
            <input type="file" required accept=".swbak" onChange={(e) => setFile(e.target.files[0] || null)} className="block w-full text-sm" />
          </Field>
          <Field label="The passphrase that backup was made with">
            <input type="password" required autoComplete="off" value={form.passphrase} onChange={set('passphrase')} className={inputClass} />
          </Field>
          <Field label="Your sworkr password">
            <input type="password" required autoComplete="current-password" value={form.password} onChange={set('password')} className={inputClass} />
          </Field>
          <Field label="Type RESTORE to confirm">
            <input type="text" required autoComplete="off" autoCapitalize="characters" value={form.confirm} onChange={set('confirm')} className={inputClass} />
          </Field>
          <p className="text-xs text-red-800">Afterwards everyone is signed out. Sign in with the username and password that were in use when the backup was made.</p>
          <div className="flex flex-wrap gap-2">
            <button type="submit" disabled={busy || !file || form.confirm.trim() !== 'RESTORE'}
              className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50">
              {busy ? 'Restoring…' : 'Replace everything with this backup'}
            </button>
            <button type="button" disabled={busy} onClick={() => setOpen(false)} className={quietButtonClass}>Cancel</button>
          </div>
          <Notice message={message} />
        </form>
      )}
    </div>
  );
}

// ==================== YOUR DATA ====================

function YourData() {
  const [summary, setSummary] = useState(null);
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState(null);
  const [erasing, setErasing] = useState(false);
  const [countdown, setCountdown] = useState(null);   // seconds left before erasing; null when not counting
  const [password, setPassword] = useState('');
  const [word, setWord] = useState('');
  const load = useCallback(() => {
    axios.get('/api/account/data').then(({ data }) => setSummary(data)).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);

  const download = async () => {
    setBusy('download');
    setMessage(null);
    try {
      const response = await axios.get('/api/account/data/export', { responseType: 'blob' });
      const name = /filename="([^"]+)"/.exec(response.headers['content-disposition'] || '')?.[1] || 'sworkr-my-data.zip';
      downloadBlob(response.data, name, 'application/zip');
      setMessage({ ok: `Saved ${name}. It isn't encrypted: keep it somewhere safe, or delete it when you're done.` });
    } catch (err) {
      setMessage({ error: errorMessage(err, "The download didn't work") });
    } finally {
      setBusy('');
    }
  };

  // Submitting only starts a 10-second countdown with a Cancel button; nothing is sent until it reaches zero.
  const startErase = (e) => {
    e.preventDefault();
    setMessage(null);
    setCountdown(10);
  };
  useEffect(() => {
    if (countdown === null) return undefined;
    if (countdown === 0) { setCountdown(null); erase(); return undefined; }
    const t = setTimeout(() => setCountdown((n) => (n === null ? null : n - 1)), 1000);
    return () => clearTimeout(t);
  }, [countdown]); // eslint-disable-line react-hooks/exhaustive-deps

  const erase = async () => {
    setBusy('erase');
    setMessage(null);
    try {
      await axios.post('/api/account/data/erase', { password, confirm: word });
      window.location.assign('/');   // start again from an empty sworkr, with nothing left in memory
    } catch (err) {
      setMessage({ error: errorMessage(err, "Nothing was erased") });
      setBusy('');
    }
  };

  if (!summary) return null;
  return (
    <Section title="Your data" hint="Take everything with you, or wipe it all.">
      <div className="space-y-5">
        <div className="space-y-2">
          <p className="text-sm text-gray-700">
            sworkr holds {summary.records.toLocaleString()} {summary.records === 1 ? 'record' : 'records'} of yours.
          </p>
          <button type="button" disabled={!!busy} onClick={download} className={buttonClass}>
            {busy === 'download' ? 'Preparing…' : 'Download everything'}
          </button>
          <p className="text-xs text-gray-500">
            A zip with one readable file per kind of record: contacts, bookings, money, notes, tasks and settings. Saved passwords are left out.
          </p>
        </div>

        <div className="border-t border-gray-100 pt-4 space-y-2">
          <p className="text-sm font-medium text-gray-700">Erase everything</p>
          <p className="text-xs text-gray-500">
            Deletes every contact, booking, note, payment and setting of yours, and overwrites them in the database so they can't be recovered from it.
            Your login stays, so you can start again. Other devices are signed out.
          </p>
          <p className="text-xs text-gray-500">
            It can't reach copies made earlier: backup files in the <code className="bg-gray-100 px-1 rounded">backups</code> folder (delete those yourself),
            and bookings already sent to your Nextcloud calendar.
          </p>
          {!erasing ? (
            <button type="button" disabled={!!busy} onClick={() => setErasing(true)} className="text-sm text-red-600 hover:text-red-800 underline">
              Erase everything…
            </button>
          ) : (
            countdown !== null ? (
              <div className="space-y-3 rounded-lg border border-red-300 bg-red-50 p-4 text-center" role="alert">
                <p className="text-sm text-red-800">Erasing everything in</p>
                <p className="text-4xl font-bold text-red-700 tabular-nums">{countdown}</p>
                <button type="button" autoFocus onClick={() => setCountdown(null)}
                  className="w-full rounded-lg bg-white border-2 border-red-600 px-4 py-3 text-base font-semibold text-red-700 hover:bg-red-100">
                  Stop! Don't erase
                </button>
              </div>
            ) : (
            <form onSubmit={startErase} className="space-y-2 rounded-lg border border-red-200 bg-red-50 p-3">
              <p className="text-sm text-red-800">This can't be undone. Download a copy first if you might want any of it.</p>
              <Field label="Your password">
                <input type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className={inputClass} />
              </Field>
              <Field label={`Type ${summary.erase_word} to confirm`}>
                <input type="text" required autoComplete="off" autoCapitalize="characters" value={word} onChange={(e) => setWord(e.target.value)} className={inputClass} />
              </Field>
              <div className="flex flex-wrap gap-2">
                <button type="submit" disabled={!!busy || word.trim() !== summary.erase_word || !password}
                  className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50">
                  {busy === 'erase' ? 'Erasing…' : 'Erase everything of mine'}
                </button>
                <button type="button" disabled={!!busy} onClick={() => { setErasing(false); setPassword(''); setWord(''); }} className={quietButtonClass}>Cancel</button>
              </div>
              <p className="text-xs text-red-700">You'll get 10 seconds to change your mind.</p>
            </form>
            )
          )}
        </div>
        <Notice message={message} />
      </div>
    </Section>
  );
}

// ==================== USERS (admin) ====================

function Users({ me }) {
  const [users, setUsers] = useState([]);
  const [form, setForm] = useState({ username: '', password: '' });
  const [message, setMessage] = useState(null);

  const load = useCallback(() => {
    axios.get('/api/users').then(({ data }) => setUsers(data)).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);

  const add = async (e) => {
    e.preventDefault();
    setMessage(null);
    try {
      const { data } = await axios.post('/api/users', form);
      setForm({ username: '', password: '' });
      setMessage({ ok: `Added ${data.username}. Give them the username and password; they can change the password after logging in.` });
      load();
    } catch (err) {
      setMessage({ error: errorMessage(err, 'Could not add the user') });
    }
  };

  const setPassword = async (u) => {
    const password = window.prompt(`New password for ${u.username} (at least 12 characters):`);
    if (!password) return;
    try {
      await axios.post(`/api/users/${u.id}/password`, { password });
      setMessage({ ok: `Password changed for ${u.username}. Their devices have been logged out.` });
    } catch (err) {
      setMessage({ error: errorMessage(err, 'Could not change the password') });
    }
  };

  const remove = async (u) => {
    if (window.prompt(`This deletes ${u.username} and all ${u.clients} of their clients, with every appointment and expense. Type their username to confirm:`) !== u.username) return;
    try {
      await axios.delete(`/api/users/${u.id}`);
      setMessage({ ok: `Deleted ${u.username}.` });
      load();
    } catch (err) {
      setMessage({ error: errorMessage(err, 'Could not delete the user') });
    }
  };

  return (
    <Section title="Users" hint="Each person has their own login and their own separate clients, appointments and money. Nobody sees anyone else's.">
      <div className="space-y-4">
        <ul className="divide-y divide-gray-100">
          {users.map((u) => (
            <li key={u.id} className="flex flex-wrap items-center gap-3 py-2 text-sm">
              <span className="font-medium text-gray-800">{u.username}</span>
              {u.is_admin && <span className="px-2 py-0.5 rounded-full bg-sworkr-50 text-sworkr-600 text-xs">admin</span>}
              <span className="text-gray-400 text-xs">{u.clients} client{u.clients === 1 ? '' : 's'}</span>
              {u.id !== me.id && (
                <span className="ml-auto flex gap-3">
                  <button onClick={() => setPassword(u)} className="text-xs text-sworkr-600 hover:text-sworkr-800">Set password</button>
                  <button onClick={() => remove(u)} className="text-xs text-red-500 hover:text-red-700">Delete</button>
                </span>
              )}
            </li>
          ))}
        </ul>
        <form onSubmit={add} className="grid sm:grid-cols-[1fr_1fr_auto] gap-2 items-end">
          <Field label="New username">
            <input required minLength={2} autoComplete="off" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} className={inputClass} />
          </Field>
          <Field label="Their first password">
            <input required minLength={12} type="text" autoComplete="off" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} className={inputClass} />
          </Field>
          <button type="submit" className={buttonClass}>Add user</button>
        </form>
        <Notice message={message} />
      </div>
    </Section>
  );
}
