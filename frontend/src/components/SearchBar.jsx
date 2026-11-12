import { useEffect, useState } from 'react';
import SearchOverlay from '../SearchOverlay';

export default function SearchBar() {
  const [isOpen, setIsOpen] = useState(false);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') setIsOpen(false);
      if (e.key === '/' && !isOpen && document.activeElement?.tagName !== 'INPUT') {
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
        className="px-3 py-1.5 rounded-lg bg-white/20 text-white/90 hover:bg-white/30 transition-colors"
      >
        Search…
      </button>
      <SearchOverlay isOpen={isOpen} onClose={() => setIsOpen(false)} />
    </>
  );
}
