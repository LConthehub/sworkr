import { useCallback, useEffect, useState } from 'react';
import { BrowserRouter, Routes, Route, NavLink, Navigate } from 'react-router-dom';
import axios from 'axios';
import ClientList from './pages/ClientList';
import AppointmentCalendar from './pages/AppointmentCalendar';
import Expenses from './pages/Expenses';
import Account from './pages/Account';
import Login from './pages/Login';
import SearchBar from './components/SearchBar';

const navClass = ({ isActive }) =>
  `transition-colors ${isActive ? 'text-white font-semibold' : 'text-white/80 hover:text-white'}`;

function App() {
  // undefined = still checking, null = logged out
  const [auth, setAuth] = useState({ user: undefined, setupRequired: false });

  const checkAuth = useCallback(async () => {
    try {
      const { data } = await axios.get('/api/auth/status');
      setAuth({ user: data.user, setupRequired: data.setup_required });
    } catch {
      setAuth({ user: null, setupRequired: false, offline: true });
    }
  }, []);

  useEffect(() => {
    checkAuth();
    // If any request comes back "not logged in" (e.g. session expired), show the login screen.
    const id = axios.interceptors.response.use(
      (r) => r,
      (err) => {
        const url = err.config?.url || '';
        if (err.response?.status === 401 && !url.startsWith('/api/auth/')) {
          setAuth((a) => ({ ...a, user: null }));
        }
        return Promise.reject(err);
      }
    );
    return () => axios.interceptors.response.eject(id);
  }, [checkAuth]);

  const logout = async () => {
    try { await axios.post('/api/auth/logout'); } catch { /* already logged out */ }
    setAuth({ user: null, setupRequired: false });
  };

  if (auth.user === undefined) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin border-4 rounded-full border-white/30 border-t-white w-12 h-12" />
      </div>
    );
  }

  if (!auth.user) {
    return (
      <>
        {auth.offline && (
          <p className="fixed top-4 inset-x-0 text-center text-white text-sm">Can't reach the server. Is the api container running?</p>
        )}
        <Login setup={auth.setupRequired} onLoggedIn={(user) => setAuth({ user, setupRequired: false })} />
      </>
    );
  }

  return (
    <BrowserRouter>
      <div className="min-h-screen">
        <nav className="bg-white/20 backdrop-blur-md border-b border-white/30 sticky top-0 z-40">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex items-center justify-between h-16 gap-4">
              <NavLink to="/" className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-sworkr-500 to-sworkr-800 flex items-center justify-center text-white font-bold text-xl">
                  SW
                </div>
                <span className="hidden sm:inline text-white font-bold text-xl tracking-tight">Sworkr</span>
              </NavLink>

              <div className="flex items-center gap-4 sm:gap-6 text-sm">
                <NavLink to="/" end className={navClass}>Calendar</NavLink>
                <NavLink to="/clients" className={navClass}>Clients</NavLink>
                <NavLink to="/expenses" className={navClass}>Expenses</NavLink>
                <SearchBar />
                <NavLink to="/account" className={navClass} title="Account">{auth.user.username}</NavLink>
              </div>
            </div>
          </div>
        </nav>

        <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <Routes>
            <Route path="/" element={<AppointmentCalendar />} />
            <Route path="/appointments" element={<Navigate to="/" replace />} />
            <Route path="/clients" element={<ClientList />} />
            <Route path="/expenses" element={<Expenses />} />
            <Route path="/account" element={<Account user={auth.user} onLogout={logout} />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

export default App;
