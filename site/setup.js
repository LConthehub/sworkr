// The setup builder on /docs/install.html. Runs only in your browser: nothing you type is sent anywhere.
// It writes a docker-compose.yml (and, for email, a .env) from the choices on the page.
(function () {
  'use strict';
  var form = document.getElementById('setup');
  if (!form) return;
  var out = document.getElementById('compose');
  var envBox = document.getElementById('env');
  var envWrap = document.getElementById('env-wrap');
  var steps = document.getElementById('steps');

  function val(name) {
    var el = form.elements[name];
    if (!el) return '';
    if (el.type === 'checkbox') return el.checked;
    return (el.value || '').trim();
  }
  // A path as Docker Compose wants it: forward slashes, quoted (paths can have spaces).
  function path(p) { return p.replace(/\\/g, '/').replace(/\/+$/, ''); }
  function q(s) { return '"' + String(s).replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"'; }
  function num(name, fallback, min, max) {
    var n = parseInt(val(name), 10);
    return isNaN(n) ? fallback : Math.max(min, Math.min(max, n));
  }

  function build() {
    var port = num('port', 8008, 1, 65535);
    var dataFolder = path(val('data_folder'));
    var keysFolder = path(val('keys_folder'));
    var backups = path(val('backups')) || './backups';
    var content = path(val('content'));
    var network = val('network') === 'network';
    var passkeys = val('passkey_address').replace(/\/+$/, '');
    var idle = num('idle', 120, 0, 1440);
    var keep = num('keep', 14, 1, 365);
    var email = val('email');

    var y = [];
    y.push('# Made with the setup builder at sworkr.com/docs/install.html');
    y.push('# Start:  docker compose up -d --build     (or double-click start)');
    y.push('# Stop:   docker compose down              (never add -v: it deletes your records)');
    y.push('');
    y.push('name: sworkr          # keep this name: it is how Docker finds your records again');
    y.push('');
    y.push('services:');
    y.push('  sworkr:');
    y.push('    build: .');
    y.push('    ports:');
    y.push('      - ' + q((network ? '' : '127.0.0.1:') + port + ':8008') + (network ? '      # other devices on your network can open it' : '      # this computer only'));
    y.push('    volumes:');
    y.push(dataFolder ? '      - ' + q(dataFolder + ':/data') + '        # your records' : '      - sworkr_data:/data                 # your records (kept by Docker)');
    y.push(keysFolder ? '      - ' + q(keysFolder + ':/keys') + '        # the key that locks them: keep it apart from backups' : '      - sworkr_keys:/keys                 # the key that locks them (kept by Docker)');
    y.push('      - ' + q(backups + ':/backups') + '        # encrypted daily backups');
    if (content) y.push('      - ' + q(content + ':/content:ro') + '        # content library (read only: sworkr never changes it)');
    y.push('    environment:');
    y.push('      - BACKUP_KEEP=' + keep);
    y.push('      - SESSION_IDLE_MINUTES=' + idle);
    if (passkeys) y.push('      - PASSKEY_ORIGINS=' + passkeys);
    if (email) {
      ['SMTP_HOST', 'SMTP_PORT', 'SMTP_USER', 'SMTP_PASSWORD', 'SMTP_FROM', 'SMTP_SECURITY'].forEach(function (k) {
        var fallback = k === 'SMTP_PORT' ? '587' : k === 'SMTP_SECURITY' ? 'starttls' : '';
        y.push('      - ' + k + '=${' + k + ':-' + fallback + '}      # from the .env file next to this one');
      });
    }
    y.push('    restart: unless-stopped');
    if (!dataFolder || !keysFolder) {
      y.push('');
      y.push('volumes:');
      if (!dataFolder) y.push('  sworkr_data:');
      if (!keysFolder) y.push('  sworkr_keys:');
    }
    out.value = y.join('\n') + '\n';

    envWrap.hidden = !email;
    if (email) {
      envBox.value = [
        '# Email sworkr sends from (safety check-in alerts, sign-in codes). Keep this file private.',
        'SMTP_HOST=' + val('smtp_host'),
        'SMTP_PORT=' + (val('smtp_port') || '587'),
        'SMTP_USER=' + val('smtp_user'),
        'SMTP_PASSWORD=',
        'SMTP_FROM=' + (val('smtp_from') || val('smtp_user')),
        'SMTP_SECURITY=' + (val('smtp_security') || 'starttls'),
        '',
      ].join('\n');
    }

    var url = 'http://localhost:' + port;
    steps.innerHTML = '';
    [
      'Download <a href="/downloads/sworkr-docker.zip">sworkr-docker.zip</a> and unzip it.',
      'In the <code>sworkr</code> folder, open <code>docker-compose.yml</code> in a text editor, replace everything in it with the text above, and save.',
      email ? 'Save the second box as a file called <code>.env</code> in the same folder, and type your email app password after <code>SMTP_PASSWORD=</code>.' : null,
      dataFolder || keysFolder || content ? 'Make sure the folders you chose exist. On Mac, Docker Desktop may ask to share them: say yes.' : null,
      'Double-click <code>start.bat</code> (Windows) or <code>start.command</code> (Mac), or run <code>docker compose up -d --build</code> in that folder.',
      'Open <a href="' + url + '">' + url + '</a> and make your account.',
    ].filter(Boolean).forEach(function (html) {
      var li = document.createElement('li');
      li.innerHTML = html;
      steps.appendChild(li);
    });
  }

  function copier(buttonId, box) {
    var b = document.getElementById(buttonId);
    if (!b) return;
    b.addEventListener('click', function () {
      box.select();
      var done = function () { b.textContent = 'Copied'; setTimeout(function () { b.textContent = 'Copy'; }, 1500); };
      if (navigator.clipboard) navigator.clipboard.writeText(box.value).then(done, function () { document.execCommand('copy'); done(); });
      else { document.execCommand('copy'); done(); }
    });
  }
  function downloader(buttonId, box, filename) {
    var b = document.getElementById(buttonId);
    if (!b) return;
    b.addEventListener('click', function () {
      var a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([box.value], { type: 'text/yaml' }));
      a.download = filename;
      a.click();
      setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
    });
  }

  form.addEventListener('input', build);
  form.addEventListener('change', function () {
    document.getElementById('email-fields').hidden = !val('email');
    build();
  });
  copier('copy-compose', out);
  copier('copy-env', envBox);
  downloader('download-compose', out, 'docker-compose.yml');
  downloader('download-env', envBox, '.env');
  document.getElementById('email-fields').hidden = !val('email');
  document.getElementById('builder').hidden = false;
  document.getElementById('no-script').hidden = true;
  build();
})();
