// Where a contact's handle opens: their page (or chat) on the platform itself, in a new tab.
// sworkr never signs in anywhere and never reads messages; this is only a link, worked out from what was typed.

const digits = (s) => s.replace(/[^\d]/g, '');

const BY_PLATFORM = {
  instagram: (u) => `https://ig.me/m/${u}`,
  'x (twitter)': (u) => `https://x.com/${u}`,
  x: (u) => `https://x.com/${u}`,
  twitter: (u) => `https://x.com/${u}`,
  of: (u) => `https://onlyfans.com/${u}`,
  onlyfans: (u) => `https://onlyfans.com/${u}`,
  fansly: (u) => `https://fansly.com/${u}`,
  tiktok: (u) => `https://www.tiktok.com/@${u}`,
  snapchat: (u) => `https://www.snapchat.com/add/${u}`,
  telegram: (u) => `https://t.me/${u}`,
  reddit: (u) => `https://www.reddit.com/user/${u}`,
  bluesky: (u) => `https://bsky.app/profile/${u.includes('.') ? u : `${u}.bsky.social`}`,
  facebook: (u) => `https://m.me/${u}`,
  linkedin: (u) => `https://www.linkedin.com/in/${u}`,
};

// These two are reached by phone number, not by a username.
const BY_NUMBER = {
  whatsapp: (n) => `https://wa.me/${n}`,
  signal: (n) => `https://signal.me/#p/+${n}`,
};

export function handleLink(platform, handle) {
  const text = (handle || '').trim();
  if (/^https?:\/\/\S+$/i.test(text)) return text;   // a pasted link opens as it is
  const key = (platform || '').trim().toLowerCase();
  if (BY_NUMBER[key]) {
    const n = digits(text);
    return n.length >= 8 && /^[+\d\s().-]+$/.test(text) ? BY_NUMBER[key](n) : null;
  }
  const user = text.replace(/^@/, '').replace(key === 'reddit' ? /^\/?u\//i : /^$/, '');
  if (!BY_PLATFORM[key] || !/^[\w.-]+$/.test(user) || user.includes('..')) return null;
  return BY_PLATFORM[key](user);
}
