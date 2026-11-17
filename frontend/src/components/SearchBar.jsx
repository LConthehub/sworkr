import { useEffect, useState } from 'react';
import SearchOverlay from '../SearchOverlay';

export default function SearchBar() {
  const [isOpen, setIsOpen] = useState(false);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') setIsOpen(false);
      // "/" opens search, but not while typing in a field (e.g. a date like 11/12 in a Notes box).
      const el = document.activeElement;
      const typing = el && (['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) || el.isContentEditable);
      if (e.key === '/' && !isOpen && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();
        setIsOpen(true);
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [isOpen]);

  return (
    <>
      <button
        onClick={() => setIsOpen(true)}
        className="w-full flex items-center gap-2 px-3 py-2 rounded-full bg-white border border-line text-muted hover:border-sworkr-300 transition-colors text-sm text-left"
        aria-label="Search contacts, bookings and expenses"
      >
        <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" className="w-4 h-4 shrink-0" aria-hidden="true">
          <circle cx="8.5" cy="8.5" r="5.5" /><path d="M13 13l4 4" strokeLinecap="round" />
        </svg>
        <span className="flex-1 truncate">Search…</span>
        <kbd className="hidden md:inline text-[11px] px-1.5 rounded border border-line bg-blush text-muted font-sans">/</kbd>
      </button>
      <SearchOverlay isOpen={isOpen} onClose={() => setIsOpen(false)} />
    </>
  );
}
