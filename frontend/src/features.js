import { useEffect, useState } from 'react';
import axios from 'axios';

// Which parts of sworkr fit this person's kinds of work (from "How do you work?"). One fetch, shared.
// Until it arrives, and if it fails, everything shows: hiding by mistake is worse than showing too much.
let pending = null;
const listeners = new Set();

const load = (fresh = false) => {
  if (fresh || !pending) {
    // A failure (not signed in yet) isn't remembered: the next screen that asks tries again.
    pending = axios.get('/api/work-profile').then(({ data }) => data.features || {}).catch(() => { pending = null; return {}; });
    pending.then((f) => listeners.forEach((fn) => fn(f)));
  }
  return pending;
};

/** Call after the kinds of work (or "show everything") change, so every screen catches up. */
export const reloadFeatures = () => load(true);

/** `has('rates')` is true when that part of sworkr is for this person. */
export function useFeatures() {
  const [features, setFeatures] = useState(null);
  useEffect(() => {
    let alive = true;
    const set = (f) => { if (alive) setFeatures(f); };
    listeners.add(set);
    load().then(set);
    return () => { alive = false; listeners.delete(set); };
  }, []);
  return (name) => !features || features[name] !== false;
}
