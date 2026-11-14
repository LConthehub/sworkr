// Discreet mode (set on this device): the plain tab title from the very first moment, not only once the app
// has loaded. A file, not an inline script, so the Content-Security-Policy can keep refusing inline scripts.
try {
  var discreet = JSON.parse(localStorage.getItem('sworkr:discreet') || '{}');
  if (discreet.enabled) document.title = discreet.title || 'Notes';
} catch (e) { /* storage unavailable: the app sets it once loaded */ }
