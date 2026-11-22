// Shows a thank-you / "give what fits" box when someone starts a download on sworkr.com.
// The download itself is never blocked or delayed. Nothing is sent anywhere and nothing is stored on this
// computer: the box shows at most once per page visit (a plain variable, not a cookie).
(function () {
  'use strict';
  var box = document.getElementById('thanks');
  if (!box || typeof box.showModal !== 'function') return;     // old browser: downloads still work
  var shown = false;
  var links = document.querySelectorAll('a[href^="/downloads/"]');
  Array.prototype.forEach.call(links, function (a) {
    a.addEventListener('click', function () {
      if (shown) return;
      shown = true;
      setTimeout(function () { box.showModal(); }, 400);      // let the download start first
    });
  });
  // Click outside the box to close it.
  box.addEventListener('click', function (e) {
    var r = box.getBoundingClientRect();
    var inside = e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom;
    if (!inside) box.close();
  });
})();
