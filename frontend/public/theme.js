// Light or dark (Settings > Look, kept on this device). Runs before the page draws, so dark mode never
// flashes white first. A file, not an inline script, so the Content-Security-Policy can keep refusing inline scripts.
(function () {
  var choice = 'light';
  try { choice = localStorage.getItem('sworkr:theme') || 'light'; } catch (e) { /* storage unavailable */ }
  var media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  function apply() {
    var dark = choice === 'dark' || (choice === 'system' && media && media.matches);
    document.documentElement.classList.toggle('dark', !!dark);
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', dark ? '#1b141e' : '#a73178');
  }
  window.sworkrTheme = function (next) {
    choice = next;
    try { localStorage.setItem('sworkr:theme', next); } catch (e) { /* not remembered */ }
    apply();
  };
  if (media && media.addEventListener) media.addEventListener('change', apply);
  apply();
})();
