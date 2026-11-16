import { useCallback, useEffect, useRef, useState } from 'react';
import { BrowserRouter, Routes, Route, NavLink, Navigate, useParams } from 'react-router-dom';
import axios from 'axios';
import ClientList from './pages/ClientList';
import ClientDetail from './pages/ClientDetail';
import AppointmentCalendar from './pages/AppointmentCalendar';
import MoneyHub from './pages/MoneyHub';
import Dashboard from './pages/Dashboard';
import Content from './pages/Content';
import Account from './pages/Account';
import Login from './pages/Login';
import Inquiries, { GoneQuiet } from './pages/Inquiries';
import SearchBar from './components/SearchBar';
import CheckInBanner from './components/CheckInBanner';
import QuickCash from './components/QuickCash';
import { DecoyScreen, useDiscreet, usePanicKey } from './components/Discreet';
import Reminders from './components/Reminders';
import { WorkTypesFirstRun } from './components/WorkTypes';
import { clearCaches } from './api';

const navClass = ({ isActive }) =>
  `transition-colors ${isActive ? 'text-white font-semibold' : 'text-white/80 hover:text-white'}`;
const tabClass = ({ isActive }) =>
  `whitespace-nowrap px-3 py-1.5 rounded-full text-sm font-medium ${isActive ? 'bg-white text-sworkr-600 shadow' : 'text-white hover:bg-white/20'}`;

const PAGES = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/calendar', label: 'Calendar' },
  { to: '/contacts', label: 'Contacts' },
  { to: '/content', label: 'Content' },
  { to: '/money', label: 'Money' },
];

/** Logs out after the chosen time without any mouse, touch or keyboard use, so an open tab doesn't stay readable. */
function useIdleLogout(idleMinutes, logout) {
  const lastActive = useRef(Date.now());
  useEffect(() => {
    if (!idleMinutes) return undefined;
    lastActive.current = Date.now();
    const touch = () => { lastActive.current = Date.now(); };
    const events = ['mousemove', 'mousedown', 'keydown', 'touchstart', 'scroll'];
    events.forEach((e) => window.addEventListener(e, touch, { passive: true }));
    const id = setInterval(() => {
      if (Date.now() - lastActive.current > idleMinutes * 60000) logout('idle');
    }, 15000);
    return () => {
      events.forEach((e) => window.removeEventListener(e, touch));
      clearInterval(id);
    };
  }, [idleMinutes, logout]);
}

function App() {
  // user: undefined = still checking, null = logged out
  const [auth, setAuth] = useState({ user: undefined, setupRequired: false });
  const [idleMinutes, setIdleMinutes] = useState(0);
  const [notice, setNotice] = useState('');

  const checkAuth = useCallback(async () => {
    try {
      const { data } = await axios.get('/api/auth/status');
      setAuth({ user: data.user, setupRequired: data.setup_required, demo: !!data.demo, demoLogin: data.demo_login || null, passkeyHint: !!data.passkey_hint });
    } catch {
      setAuth({ user: null, setupRequired: false, offline: true });
    }
  }, []);

  useEffect(() => {
    checkAuth();
    // If any request comes back "not logged in" (e.g. the session timed out), show the login screen.
    const id = axios.interceptors.response.use(
      (r) => r,
      (err) => {
        const url = err.config?.url || '';
        if (err.response?.status === 401 && !url.startsWith('/api/auth/')) {
          clearCaches();
          setAuth((a) => (a.user ? { ...a, user: null } : a));
        }
        return Promise.reject(err);
      }
    );
    return () => axios.interceptors.response.eject(id);
  }, [checkAuth]);

  const loggedInAs = auth.user?.id;
  useEffect(() => {
    if (!loggedInAs) return;
    setNotice('');
    axios.get('/api/account/settings').then(({ data }) => setIdleMinutes(data.idle_minutes)).catch(() => {});
  }, [loggedInAs]);

  const logout = useCallback(async (reason) => {
    try { await axios.post('/api/auth/logout'); } catch { /* already logged out */ }
    clearCaches();
    setAuth((a) => ({ ...a, user: null, setupRequired: false }));
    setNotice(reason === 'idle' ? 'You were logged out because sworkr was left unused.' : '');
  }, []);

  useIdleLogout(auth.user ? idleMinutes : 0, logout);

  // Discreet mode: a plain tab title, and a panic switch that hides everything and logs out.
  const discreet = useDiscreet();
  const [decoy, setDecoy] = useState(false);
  const panic = useCallback(() => {
    setDecoy(true);
    window.history.replaceState(null, '', '/');   // the address bar shouldn't say where you were
    logout();
  }, [logout]);
  usePanicKey(discreet.enabled && !!auth.user, panic);
  if (decoy) return <DecoyScreen title={discreet.title} />;

  if (auth.user === undefined) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin border-4 rounded-full border-white/30 border-t-white w-12 h-12" role="status" aria-label="Loading" />
      </div>
    );
  }

  if (!auth.user) {
    return (
      <>
        {(auth.offline || notice) && (
          <p className="fixed top-4 inset-x-0 px-4 text-center text-white text-sm">
            {auth.offline ? "Can't reach the server. Is the api container running?" : notice}
          </p>
        )}
        <Login setup={auth.setupRequired} demoLogin={auth.demoLogin} passkeyHint={auth.passkeyHint} onLoggedIn={(user) => setAuth((a) => ({ ...a, user, setupRequired: false }))} />
      </>
    );
  }

  return (
    <BrowserRouter>
      <div className="min-h-screen">
        <nav className="print:hidden bg-white/20 backdrop-blur-md border-b border-white/30 sticky top-0 z-40">
          <div className="max-w-7xl mx-auto px-3 sm:px-6 lg:px-8">
            {/* Pages on the left, search in the middle, settings on the right (like Nextcloud). */}
            <div className="grid grid-cols-[auto_1fr_auto] items-center h-14 sm:h-16 gap-3 sm:gap-6">
              <div className="flex items-center gap-4 lg:gap-6 text-sm">
                <NavLink to="/" className="flex items-center gap-3" aria-label="sworkr, dashboard">
                  <div className="w-9 h-9 sm:w-10 sm:h-10 rounded-lg bg-gradient-to-br from-sworkr-500 to-sworkr-800 flex items-center justify-center text-white font-bold text-lg sm:text-xl">
                    SW
                  </div>
                  <span className="hidden xl:inline text-white font-bold text-xl tracking-tight">Sworkr</span>
                </NavLink>
                <div className="hidden sm:flex items-center gap-4 lg:gap-6">
                  {PAGES.map((p) => <NavLink key={p.to} to={p.to} end={p.end} className={navClass}>{p.label}</NavLink>)}
                </div>
              </div>

              <div className="w-full max-w-md justify-self-center">
                <SearchBar />
              </div>

              <div className="flex items-center gap-2 sm:gap-3">
                {discreet.enabled && discreet.panicButton && (
                  <button type="button" onClick={panic} title="Hide sworkr now and log out"
                    className="px-2.5 py-1 rounded-lg bg-white/25 text-white text-xs font-semibold hover:bg-white/40">
                    Hide
                  </button>
                )}
                <NavLink to="/account" className={({ isActive }) => `${navClass({ isActive })} text-sm whitespace-nowrap`} title="Your account and settings">
                  <span className="hidden md:inline">{auth.user.username}'s settings</span>
                  <span className="md:hidden" aria-label={`${auth.user.username}'s settings`}>⚙</span>
                </NavLink>
              </div>
            </div>
            {/* On a phone the pages are a row under the header that scrolls sideways. */}
            <div className="sm:hidden flex gap-1 overflow-x-auto pb-2 -mx-1 px-1" aria-label="Pages">
              {PAGES.map((p) => <NavLink key={p.to} to={p.to} end={p.end} className={tabClass}>{p.label}</NavLink>)}
            </div>
          </div>
        </nav>

        <main className="max-w-7xl mx-auto px-3 sm:px-6 lg:px-8 py-4 sm:py-8">
          {auth.demo && <DemoBanner />}
          <CheckInBanner />
          <QuickCash userId={auth.user.id} />
          <Routes>
            <Route path="/" element={<Dashboard user={auth.user} />} />
            <Route path="/calendar" element={<AppointmentCalendar />} />
            <Route path="/contacts" element={<ClientList />} />
            <Route path="/contacts/:id" element={<ClientDetail />} />
            <Route path="/clients" element={<Navigate to="/contacts" replace />} />
            <Route path="/clients/:id" element={<OldContactLink />} />
            <Route path="/contacts/inquiries" element={<Inquiries />} />
            <Route path="/contacts/quiet" element={<GoneQuiet />} />
            <Route path="/inquiries" element={<Navigate to="/contacts/inquiries" replace />} />
            <Route path="/regulars" element={<Navigate to="/contacts/quiet" replace />} />
            <Route path="/content" element={<Content />} />
            <Route path="/content/:tab" element={<Content />} />
            <Route path="/money" element={<MoneyHub />} />
            <Route path="/money/:tab" element={<MoneyHub />} />
            <Route path="/earnings" element={<Navigate to="/money/compare" replace />} />
            <Route path="/tours" element={<Navigate to="/money/compare" replace />} />
            <Route path="/goals" element={<Navigate to="/money/goals" replace />} />
            <Route path="/account" element={<Account user={auth.user} onLogout={() => logout()} onIdleChange={setIdleMinutes} />} />
            <Route path="/account/:group" element={<Account user={auth.user} onLogout={() => logout()} onIdleChange={setIdleMinutes} />} />
            <Route path="/expenses" element={<Navigate to="/money" replace />} />
            <Route path="/appointments" element={<Navigate to="/calendar" replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>

        <Reminders />
        <WorkTypesFirstRun demo={auth.demo} />
      </div>
    </BrowserRouter>
  );
}

/** Links saved from before "clients" became "contacts" still work. */
function OldContactLink() {
  const { id } = useParams();
  return <Navigate to={`/contacts/${id}`} replace />;
}

/** Shown on the demo copy, so nobody mistakes the sample data for real records. */
function DemoBanner() {
  return (
    <p className="mb-4 rounded-xl bg-white/90 px-4 py-2.5 text-sm text-gray-700 shadow" role="note">
      <strong className="text-sworkr-600">Demo.</strong> Every client and number here is made up, and everything is reset to
      the sample data each night. Try anything, then share your feedback.
    </p>
  );
}

export default App;
