"""
Builds site/docs/*.html from the pages below, so the header, menu and footer live in one place.

    python site/build_docs.py

The docs are plain HTML. The one exception is the setup builder on install.html (site/setup.js), which runs
only in the visitor's browser and sends nothing anywhere. Edit the text here, run this, commit both.
"""

import html
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "docs")

# (file, menu title, page title, body)
PAGES = [
("index", "Start here", "Sworkr documentation", """
<p class="lead">Everything about running Sworkr, in the order you'll need it. If you're new, read the first three pages, then come back for the rest when you need it.</p>
<div class="cards">
  <a href="/docs/getting-started.html"><b>Get started</b><span>Install it, make your account, and do the three things worth doing on day one.</span></a>
  <a href="/docs/privacy-and-backups.html"><b>Privacy &amp; backups</b><span>What's stored, how it's locked, and how to get everything back.</span></a>
  <a href="/docs/install.html"><b>Install with Docker</b><span>Pick your options and get a ready setup file to copy.</span></a>
  <a href="/docs/phone.html"><b>On your phone</b><span>Use it from your phone without opening anything to the internet.</span></a>
  <a href="/docs/web-address.html"><b>Your own web address</b><span>A free address with HTTPS, as an alternative to Tailscale.</span></a>
  <a href="/docs/people.html"><b>Clients &amp; inquiries</b><span>Screening, inquiries, ghosts (regulars who've gone quiet), prices by tag.</span></a>
  <a href="/docs/money.html"><b>Money &amp; houses</b><span>Workplaces and their rules, tips, rates and taxes.</span></a>
  <a href="/docs/content.html"><b>Content &amp; planning</b><span>The calendar, shoots, posts, campaigns, ads and custom orders.</span></a>
  <a href="/docs/health-and-safety.html"><b>Health &amp; safety</b><span>Tests on your own schedule, documents that expire, the check-in.</span></a>
  <a href="/docs/notifications.html"><b>Notifications</b><span>Messages on your phone with ntfy.</span></a>
  <a href="/docs/own-your-data.html"><b>Own your data</b><span>Why self-hosting matters, what else to run yourself, and when a VPN helps.</span></a>
  <a href="/docs/troubleshooting.html"><b>If something goes wrong</b><span>Forgot your password, lost your phone, won't start.</span></a>
</div>
"""),

("getting-started", "Get started", "Get started", """
<p>Sworkr runs on <strong>your own computer</strong>. There is no account with us and nothing is sent to us. Pick one way to run it.</p>

<h2>Docker (recommended: Windows, Mac, Linux or a home server)</h2>
<p>Never used Docker? That's fine: you won't need to type any commands.</p>
<ol>
  <li>Install <a href="https://www.docker.com/products/docker-desktop/">Docker Desktop</a>, open it, and wait until it says <em>Engine running</em>. (<a href="/docs/install.html#first-time">More help with this step</a>.)</li>
  <li>Download <a href="/downloads/sworkr-start.zip" download>sworkr-start.zip</a> and unzip it somewhere you'll keep it, like Documents.</li>
  <li><strong>Windows:</strong> double-click <em>Start sworkr</em>. <strong>Mac:</strong> right-click <em>Start sworkr.command</em>, choose <em>Open</em>, then <em>Open</em> again (only the first time: the Mac asks because the file didn't come from the App Store). <strong>Linux:</strong> run <code>./start.sh</code>.</li>
  <li>The first start downloads Sworkr (a few minutes), then your browser opens it.</li>
</ol>
<p>The same folder has <em>Update sworkr</em> and <em>Stop sworkr</em>. Your records stay through both.</p>
<p>Prefer a terminal, or want a different port, your content folder or your own web address? <a href="/docs/install.html">Make your setup file</a>: it's the same thing, with your choices in it.</p>

<h2>Windows without Docker</h2>
<ol>
  <li>Download <em>Sworkr-windows.zip</em> from the <a href="/#get">home page</a> and unzip it somewhere you'll keep it, like <code>Documents\\Sworkr</code>.</li>
  <li>Double-click <strong>Sworkr</strong>. Windows may say it "protected your PC" because the app is new: choose <em>More info</em>, then <em>Run anyway</em>.</li>
  <li>Your browser opens Sworkr. A small icon appears by the clock: click it to open Sworkr again, open your backups folder, or quit.</li>
</ol>
<p>Your records are kept in <code>%LOCALAPPDATA%\\Sworkr</code>, your backups in <code>Documents\\Sworkr backups</code>.</p>

<h2>Your first minutes</h2>
<p>Create your account. <strong>That first account is yours and is the admin.</strong> Use a password of 12 or more characters and keep it somewhere safe. Then tick the kinds of work you do, and Sworkr sets itself up to match (expense categories, workplaces and their usual charges). You can change it any time under <em>Settings → My work</em>. Prefer it dark? <em>Settings → Look</em>.</p>
<p>A new copy has a few made-up clients so you can look around. Remove them under <em>Settings → Data &amp; users → Example data</em>.</p>

<h2>Do these three things on day one</h2>
<ol>
  <li><strong>Turn on backups.</strong> <em>Settings → Data &amp; users → Backups</em>. Choose a passphrase and tick automatic daily backups. Write the passphrase down: without it nobody can read a backup, and neither can you.</li>
  <li><strong>Turn on two-step sign-in.</strong> <em>Settings → Security &amp; privacy → Two-step sign-in</em>, with an authenticator app. Save the recovery codes on paper.</li>
  <li><strong>Encrypt your computer's disk</strong> (BitLocker on Windows, FileVault on a Mac) and use a locked user account.</li>
</ol>

<h2>Your dashboard</h2>
<p>Sworkr shows the parts that fit the kinds of work you ticked, and tucks the rest away (<em>Settings → My work → Show everything</em> brings it all back).</p>
<p>The first page shows what needs doing. <em>Customize</em> chooses the cards and their order. At the top, made for a phone:</p>
<ul>
  <li><strong>Quick logs</strong> for your kind of work: one tap for a shift, a stream, calls, a scene or a sale. Add the hours and what came in, and it's in your income.</li>
  <li><strong>The safety timer</strong>: "tell my contact if I haven't tapped I'm safe in 20 minutes". For a walk home, a first meeting, anything.</li>
  <li><strong>What's running low</strong> from your supplies list.</li>
</ul>
<p>Below that, besides bookings, tasks and money:</p>
<ul>
  <li><strong>Routines</strong>: your own checklists (morning, night, before and after a booking), ticked off each day.</li>
  <li><strong>Notes</strong>: a scratch pad that saves itself.</li>
  <li><strong>Progress</strong>: private streaks, weekly goals you set, personal bests and badges. It never suggests working more, and <em>Settings → Look</em> turns it off.</li>
  <li><strong>Ask your numbers</strong>, if you turn on the assistant: questions about your own totals, answered by an AI model running on your own computer.</li>
</ul>

<h2>Updating</h2>
<p>Docker: double-click <em>Update sworkr</em> in your sworkr folder (or run <code>docker compose pull</code>, then <code>docker compose up -d</code> there). Windows app: quit it, unzip the new version over the old folder, start it. Either way your records are upgraded by themselves, and a copy is saved first.</p>
"""),

("privacy-and-backups", "Privacy & backups", "Privacy &amp; backups", """
<h2>What's stored, and where</h2>
<p>Everything is in one database file on your computer: clients, bookings, money, plans, settings. Sworkr doesn't send it anywhere. The only things it talks to are services <em>you</em> connect: your own email, a Nextcloud calendar or content folder, ntfy if you turn on notifications, SimpleFIN if you connect your bank, Bluesky, Mastodon or Reddit if you connect them for posting, and an AI model if you turn on the assistant (one on your own computer unless you allow a cloud one; it only gets totals, never names or notes).</p>

<h2>How it's locked</h2>
<ul>
  <li>The database file is <strong>encrypted</strong> (AES-256). A copy of the file on its own can't be read.</li>
  <li>The key is kept apart from it. In the Windows app, it's in Windows Credential Manager, so it opens only for the person signed in to the computer. In Docker, it's in its own volume, <code>sworkr_sworkr_keys</code>.</li>
  <li>Saved passwords (email, calendar, content folder, ntfy token) are sealed with a second key.</li>
  <li>Sign-in: passkeys (face or fingerprint), two-step with an authenticator app, recovery codes, and a rule that can refuse passwords away from home.</li>
</ul>
<p><strong>What this does not do:</strong> protect against someone who can use your computer while you're signed in. Disk encryption, a locked computer account and discreet mode matter too.</p>

<h2>Discreet mode</h2>
<p><em>Settings → Security &amp; privacy → Discreet mode</em> gives the browser tab a plain name like "Notes" and adds a panic switch: press <kbd>Esc</kbd> three times, or tap <em>Hide</em> at the top on a phone, to hide Sworkr and sign out.</p>

<h2>Backups</h2>
<p>Backups are encrypted with <strong>your passphrase</strong>, not with the computer's key, so they open on <em>any</em> computer. That is how you get your records back if this computer dies.</p>
<ul>
  <li>Turn them on under <em>Settings → Data &amp; users → Backups</em>. Automatic daily backups land in your backups folder.</li>
  <li><strong>Keep a copy off this computer</strong>: on a USB stick, or under <em>Copies off this computer</em> if you have a Nextcloud, a Synology NAS or any other WebDAV storage. Your own storage at home is the most private place for it.</li>
  <li>Sworkr checks a backup opens about once a month and tells you if one doesn't.</li>
  <li>To restore, use <em>Restore a backup</em> on the same page and enter the passphrase.</li>
</ul>

<h2>If the key is lost</h2>
<p>Without the key, the database can't be opened. Never delete <code>sworkr_sworkr_keys</code> (Docker) or the Sworkr entries in Credential Manager. If it happens anyway, install Sworkr fresh and restore your latest backup with its passphrase.</p>

<h2>Your data, your call</h2>
<p><em>Settings → Data &amp; users</em> can download everything Sworkr holds about you, or erase everything. Erasing asks for your password, for you to type ERASE, then gives you 10 seconds to stop it. It can't reach backup files you've already saved elsewhere: delete those yourself.</p>
"""),

("install", "Install with Docker", "Install with Docker", """
<p class="lead">Pick your options, copy one file, start it. This page writes the setup file for you.</p>

<h2 id="first-time">First time with Docker</h2>
<p>Docker runs Sworkr in a sealed box on your computer, the same way on Windows, Mac and Linux. You install it once.</p>
<ul>
  <li><strong>Windows 10 or 11:</strong> install <a href="https://www.docker.com/products/docker-desktop/">Docker Desktop</a>. It may ask to install or update "WSL" (a part of Windows it needs): say yes, and restart if it asks. Open Docker Desktop and wait for <em>Engine running</em> at the bottom left. You can skip signing in to Docker.</li>
  <li><strong>Mac:</strong> download the Docker Desktop that matches your Mac: <em>Apple chip</em> for M1 and newer, <em>Intel chip</em> for older ones (Apple menu, About This Mac shows which). Drag it to Applications, open it, and wait for <em>Engine running</em>.</li>
  <li><strong>Linux or a home server:</strong> Docker Engine is enough; your distribution's instructions are at <a href="https://docs.docker.com/engine/install/">docs.docker.com/engine/install</a>.</li>
  <li><strong>A NAS:</strong> Synology's Container Manager, Unraid and TrueNAS all run it (see below).</li>
</ul>
<p>Then the easy way: download <a href="/downloads/sworkr-start.zip" download>sworkr-start.zip</a>, unzip it, and double-click <em>Start sworkr</em>. Or carry on below to make a setup file with your own choices.</p>
<p><strong>If it doesn't start:</strong> "Docker isn't running" means Docker Desktop isn't open yet, or is still starting. "Port is already allocated" means something else uses 8008: change the port below. On a Mac, "can't be opened because it is from an unidentified developer": right-click the file and choose <em>Open</em> instead of double-clicking.</p>
<p>Sworkr's Docker setup is one file, <code>docker-compose.yml</code>: where your records live, which folders it can see, and who can open it. Fill in what you want below; the file updates as you type. <strong>Nothing you type here leaves your browser.</strong></p>
<p id="no-script">This builder needs JavaScript. Without it, use the ready-made <a href="/downloads/docker-compose.yml" download>docker-compose.yml</a> as it is: it works without changes.</p>

<div id="builder" hidden>
<form id="setup" class="builder" onsubmit="return false">
  <fieldset>
    <legend>Where your records live</legend>
    <label>Data folder <input name="data_folder" placeholder="Leave empty: Docker keeps it (recommended)"></label>
    <label>Key folder <input name="keys_folder" placeholder="Leave empty: Docker keeps it (recommended)"></label>
    <p class="hint">Your records are encrypted with a key. Keep the key apart from your backups: someone with both could read everything.</p>
    <label>Backups folder <input name="backups" value="./backups" placeholder="./backups"></label>
    <label>Backups to keep <input name="keep" type="number" min="1" max="365" value="14"></label>
  </fieldset>
  <fieldset>
    <legend>Content library (optional)</legend>
    <label>A folder or drive with your photos and videos <input name="content" placeholder="e.g. E:/Content or /Volumes/Content"></label>
    <p class="hint">Sworkr only reads it, never changes it. Then choose <em>Mounted folder</em> in Settings → Content library.</p>
  </fieldset>
  <fieldset>
    <legend>Who can open it</legend>
    <label>Port <input name="port" type="number" min="1" max="65535" value="8008"></label>
    <label class="radio"><input type="radio" name="network" value="computer" checked> Only this computer (safest; use <a href="/docs/phone.html">Tailscale</a> for your phone)</label>
    <label class="radio"><input type="radio" name="network" value="network"> Other devices on my home network too</label>
    <label>Your own web address (optional) <input name="web_address" placeholder="e.g. you.duckdns.org"></label>
    <p class="hint">Adds Caddy for HTTPS on that address. Read the <a href="/docs/web-address.html">web address guide</a> first: it puts your login page on the internet.</p>
    <label>Web address for passkeys (optional) <input name="passkey_address" placeholder="Filled in from your web address"></label>
    <label>Log me out after (minutes, 0 = never) <input name="idle" type="number" min="0" max="1440" value="15"></label>
  </fieldset>
  <fieldset>
    <legend>Email (optional)</legend>
    <label class="radio"><input type="checkbox" name="email"> Send safety check-in alerts and sign-in codes from an email account</label>
    <div id="email-fields">
      <label>Outgoing mail server <input name="smtp_host" placeholder="e.g. smtp.gmail.com"></label>
      <label>Port <input name="smtp_port" value="587"></label>
      <label>Security <select name="smtp_security"><option>starttls</option><option>ssl</option><option>none</option></select></label>
      <label>Username <input name="smtp_user" placeholder="you@example.com"></label>
      <label>Send as (optional) <input name="smtp_from" placeholder="Same as the username"></label>
      <p class="hint">The password isn't typed here: you add it to the <code>.env</code> file yourself.</p>
    </div>
  </fieldset>
</form>

<h2>Your setup file</h2>
<div class="code-box">
  <textarea id="compose" readonly rows="24" spellcheck="false" aria-label="docker-compose.yml"></textarea>
  <p><button type="button" id="copy-compose">Copy</button> <button type="button" id="download-compose">Download docker-compose.yml</button></p>
</div>
<div id="env-wrap" class="code-box" hidden>
  <h3>And a <code>.env</code> file for email</h3>
  <textarea id="env" readonly rows="9" spellcheck="false" aria-label=".env"></textarea>
  <p><button type="button" id="copy-env">Copy</button> <button type="button" id="download-env">Download .env</button></p>
</div>

<h2>Install it</h2>
<ol id="steps"></ol>
</div>

<h2>Good to know</h2>
<ul>
  <li>You need <a href="https://www.docker.com/products/docker-desktop/">Docker Desktop</a> (Windows or Mac) or Docker on Linux. Don't want Docker? The <a href="/docs/getting-started.html">Windows app</a> needs nothing else.</li>
  <li>Already using Sworkr? Keep the name <code>sworkr</code> at the top of the file and your records stay where they are. Changing the data folder later starts an empty one: move your records with a backup first (<a href="/docs/privacy-and-backups.html">how</a>).</li>
  <li>To update, run <code>docker compose pull</code>, then <code>docker compose up -d</code>, in the same folder.</li>
  <li>On a Synology NAS: <em>Container Manager → Project → Create</em>, and paste this file. Other home servers (Unraid, TrueNAS, a Raspberry Pi 4 or 5) work the same way with Docker.</li>
  <li><strong>Never</strong> run <code>docker compose down -v</code>: the <code>-v</code> deletes your records.</li>
  <li>While you're at it: other services you can run at home keep even more of your life private. <a href="https://adguard.com/en/adguard-home/overview.html">AdGuard Home</a> blocks ads and trackers for every device on your network, <a href="https://nextcloud.com">Nextcloud</a> keeps your files and calendar, and <a href="https://ntfy.sh">ntfy</a> sends your phone notifications.</li>
</ul>
<script src="/setup.js" defer></script>
"""),
("phone", "On your phone", "On your phone", """
<p>Sworkr only answers on the computer it runs on, on purpose. To use it from your phone <strong>without opening anything to the internet</strong>, link your phone and your computer with <strong>Tailscale</strong>, a free app that makes a private network between your own devices. Only devices signed in to your Tailscale account can reach Sworkr, and the connection is encrypted end to end. The same steps are in Sworkr under <em>Settings → Connections → On your phone</em>.</p>

<h2>Set it up</h2>
<ol>
  <li>Install Tailscale on your computer and your phone (<a href="https://tailscale.com/download">tailscale.com/download</a>, or the App Store / Google Play). Sign in to the same account on both. Use an email you keep private.</li>
  <li>On your computer, open a terminal and run <code>tailscale serve --bg 8765</code> (Windows app) or <code>tailscale serve --bg 8008</code> (Docker). If it asks you to turn on HTTPS for your network, follow the link it gives.</li>
  <li>It prints a private address like <code>https://your-computer.tail1234.ts.net</code>. Open it on your phone and sign in.</li>
</ol>

<h2>Make it feel like an app</h2>
<p>Do this from the address you'll really use: the Tailscale address (or your own web address), not <code>localhost</code>.</p>
<ul>
  <li><strong>A plain name and icon:</strong> under <em>Settings → Look → Home screen name &amp; icon</em>, choose a name like "Notes" and any picture. Phones that add Sworkr from then on show that instead of Sworkr. (Already on your home screen? Remove it and add it again.)</li>
  <li><strong>iPhone:</strong> in Safari, tap Share, then <em>Add to Home Screen</em>. <strong>Android:</strong> in Chrome, open the menu and tap <em>Add to Home screen</em>.</li>
  <li>Add a <strong>passkey</strong> on the phone (<em>Settings → Security &amp; privacy → Passkeys</em>) so you sign in with your face or fingerprint.</li>
  <li>Consider <em>Away from home → passkeys only</em>, so a password alone can't sign in from anywhere but your computer.</li>
</ul>

<h2>Android</h2>
<ul>
  <li>Chrome offers <em>Install app</em> or <em>Add to Home screen</em> in its menu; Sworkr then opens in its own window, like on an iPhone.</li>
  <li>The <a href="https://ntfy.sh">ntfy</a> app works better on Android than on iPhone: it can show messages instantly even from your own ntfy server.</li>
  <li>Tailscale and a VPN app can't both be on at once on most phones. Tailscale can send your internet through a VPN (an "exit node", or its Mullvad add-on) if you want both.</li>
  <li>Passkeys are kept by your Google account (or your password manager); add one on the phone under <em>Settings → Security &amp; privacy → Passkeys</em>.</li>
</ul>

<h2>Good to know</h2>
<ul>
  <li>The computer or home server running Sworkr has to be on and awake. A NAS or small home server is always on, which is why it's a good home for Sworkr.</li>
  <li>To stop it, run <code>tailscale serve reset</code>.</li>
  <li>Don't forward a port on your router or point a web address at Sworkr by hand: it holds your most sensitive records. If you'd rather have your own address than Tailscale, follow <a href="/docs/web-address.html">Your own web address</a>, which sets it up safely.</li>
  <li>Tailscale's company coordinates the connection, but your data never goes through them. If you'd rather run that part yourself too, <a href="https://headscale.net">Headscale</a> is a free replacement you can host at home.</li>
  <li>For a message on your phone without opening Sworkr, see <a href="/docs/notifications.html">Notifications</a>.</li>
</ul>
"""),
("web-address", "Your own web address", "Your own web address", """
<p class="lead">The other way to use Sworkr away from home: a free web address of your own, with HTTPS. Tailscale is simpler and more private; this works on any phone or computer without an app.</p>

<h2>Before you start</h2>
<ul>
  <li><strong>This puts your login page on the internet.</strong> Anyone can find it, and bots will try passwords. Before you do it, add a <strong>passkey</strong> on each device and turn on <em>Away from home → passkeys only</em> in Settings → Security &amp; privacy, so a password alone can't get in.</li>
  <li>If you only need your phone, <a href="/docs/phone.html">Tailscale</a> keeps Sworkr off the internet entirely.</li>
  <li>Some internet providers don't allow it (they share one public address between many homes, called CGNAT). If step 3 never works, that's usually why: use Tailscale.</li>
</ul>

<h2>1. Get a free address with DuckDNS</h2>
<ol>
  <li>Go to <a href="https://www.duckdns.org">duckdns.org</a> and sign in, or use <a href="https://desec.io">deSEC</a> (a privacy-focused non-profit) or <a href="https://www.noip.com">No-IP</a> (its free plan asks you to confirm your name once a month). Use an account you keep private.</li>
  <li>Pick a name: you get <code>yourname.duckdns.org</code>. Pick something that doesn't say what it's for.</li>
  <li>Keep it pointing at your home: your home's address can change. Many routers have a <em>Dynamic DNS</em> setting with DuckDNS in the list (use your token from the DuckDNS page). If yours doesn't, the DuckDNS <em>install</em> page has a small updater for Windows, Mac and Linux.</li>
</ol>

<h2>Or use a domain you own</h2>
<p>If you already have a domain, or buy one, you don't need a free address: use the domain itself or a subdomain of it, like <code>planner.yourdomain.com</code>. Pick a name that doesn't say what it's for.</p>
<ul>
  <li>At your domain's DNS settings, add a <strong>CNAME</strong> record for the subdomain pointing to your free address (say <code>yourname.duckdns.org</code>), so it follows your home's address when it changes. Or an <strong>A</strong> record with your home's address, if it never changes.</li>
  <li>Then use your own name everywhere below instead of <code>yourname.duckdns.org</code>.</li>
  <li>Buy it with <strong>WHOIS privacy</strong> (most registrars include it now) so your name and address aren't shown on the public record. A registrar that accepts adult sites and doesn't ask why you want it is worth choosing.</li>
</ul>
<p>Some registrars with free WHOIS privacy (check each one's terms for your use before you buy):</p>
<ul class="registrars">
  <li><a href="https://porkbun.com" rel="sponsored">Porkbun</a>: low prices, privacy included.</li>
  <li><a href="https://www.namecheap.com" rel="sponsored">Namecheap</a>: privacy included, easy DNS settings.</li>
  <li><a href="https://njal.la" rel="sponsored">Njalla</a>: holds the domain for you, so your name isn't on it at all.</li>
  <li><a href="https://www.cloudflare.com/products/registrar/">Cloudflare Registrar</a>: sold at cost.</li>
</ul>
<p class="fine">Some of these links may be affiliate links: if you buy through them, Sworkr gets a small share at no cost to you. That helps keep Sworkr free for workers.</p>

<h2>2. Install Caddy</h2>
<p><a href="https://caddyserver.com/download">Caddy</a> sits in front of Sworkr and handles HTTPS by itself: it gets and renews the certificate for your address, for free.</p>
<ol>
  <li>Download Caddy for your computer and put it in a folder, for example <code>C:\\Caddy</code> on Windows or a <code>Caddy</code> folder in your home folder on a Mac.</li>
  <li>In that folder, make a file called <code>Caddyfile</code> (no extension) with:
<pre><code>yourname.duckdns.org {
    reverse_proxy 127.0.0.1:8008
}</code></pre>
  Use <code>8765</code> instead of <code>8008</code> for the Windows app.</li>
  <li>Start it from that folder with <code>caddy run</code>. To have it start with the computer, see Caddy's <em>Keep Caddy running</em> page.</li>
</ol>

<h2>3. Open the door on your router</h2>
<p>In your router's settings, find <em>Port forwarding</em>. Forward ports <strong>80</strong> and <strong>443</strong> (TCP) to the computer Sworkr runs on. Caddy needs both: 80 to get the certificate, 443 for everything else. Allow Caddy through your computer's firewall if it asks.</p>

<h2>4. Check it</h2>
<ol>
  <li>On your phone, turn off Wi-Fi and open <code>https://yourname.duckdns.org</code>. You should see the Sworkr login with a padlock.</li>
  <li>Sign in, then add a passkey on the phone (Settings → Security &amp; privacy → Passkeys).</li>
  <li>Turn on <em>Away from home → passkeys only</em>.</li>
</ol>

<h2>Good to know</h2>
<ul>
  <li>The computer or home server running Sworkr has to be on and awake.</li>
  <li>A passkey made on your DuckDNS address only works there; one made on <code>localhost</code> only works on the computer itself.</li>
  <li>To limit passkeys to your address, put it in the <strong>Web address for passkeys</strong> box in the <a href="/docs/install.html">setup builder</a>.</li>
  <li>To close it again: remove the port forwarding on the router and stop Caddy.</li>
</ul>
"""),

("people", "Clients & inquiries", "Clients &amp; inquiries", """
<h2>Contacts</h2>
<p><em>Contacts → Everyone</em> holds clients, <strong>collaborators</strong> (another worker, a photographer, a driver: anyone you work with) and others. A name is optional, so a handle alone is fine. Each contact can have handles, a persona (the name they know you by), preferences, a birthday, screening status and references.</p>
<ul>
  <li><strong>Screening</strong>: unscreened, pending, verified or declined, with notes on what you checked.</li>
  <li><strong>Do not see</strong>: tick it and Sworkr warns you if you try to book that person. A private bad-date list can be imported, or downloaded for your own backup, under <em>Settings → Safety</em>.</li>
  <li><strong>How they found you</strong>: an ad site, an account, a referral. This is what makes <em>Money → Compare → By how they found you</em> work: income against what you spent on each.</li>
  <li><strong>Tags</strong> group people, and can change their price (below).</li>
</ul>

<h2>Inquiries</h2>
<p><em>Contacts → Inquiries</em> tracks everyone who got in touch: new, replied, screening, deposit, booked, or lost (with why). Move each along as it happens. Below the list: how far inquiries get, where they drop out, and which sources send people who actually book. <em>Make a contact</em> turns an inquiry into a contact when they're worth keeping. Your saved text is one tap away for replies, and can fill in {name}, {day}, {time} and {wanted} from the inquiry.</p>

<h2>Ghosts</h2>
<p><em>Contacts → Ghosts</em> lists regulars you've seen at least twice who haven't booked for a while and have nothing booked ahead, biggest spenders first, with how often they used to book.</p>

<h2>Prices by tag</h2>
<p><em>Money → Rates → Prices by tag</em>: give a tag a percentage off, an amount off, or a <strong>locked-in rate</strong> (the client keeps paying what they last paid for that service). When you book someone with that tag for a service on your rate card, the price is worked out for you and says why. Locked-in clients don't show under "On an old rate".</p>

<h2>Getting to know them</h2>
<p>Each client's page has a card for what's worth remembering about the person: the languages they speak and whether a translator is needed, cultural practices to respect, what's good to talk about and what to avoid. A client can be marked as passed away: their history stays, and the reminders stop.</p>
<p>After a finished booking, <em>How did it go?</em> asks a few quick questions (how it went, would you see them again, what you talked about). The answers are kept on the client's page.</p>

<h2>Client base</h2>
<p><em>Contacts → Client base</em> shows who your clients are as simple bars: age, how they found you, line of work, languages, how often they've booked and what they've spent. It's built from what you've noted on their profiles, as counts only.</p>

<h2>Drivers and rides</h2>
<p>A driver is a contact you work with (not a client), and each keeps their own rates: per trip, hour, mile, km or day. <em>Ride</em> on a booking picks a driver and a rate and logs it as a travel expense that day, so it counts in the tour's budget.</p>

<h2>Cancellations and no-shows</h2>
<p><em>Settings → Deposits &amp; cancellations</em> sets your deposit percentage, what counts as a late cancellation, and the fees. Cancelling a booking asks who cancelled and suggests the fee from your policy.</p>
"""),

("money", "Money & houses", "Money &amp; houses", """
<h2>Workplaces &amp; platforms</h2>
<p>Everywhere you earn: a club, a house, an agency, a fan site, a phone line. Add them under <em>Money → Income &amp; expenses → Workplaces &amp; platforms</em>, or tick your kinds of work and Sworkr adds the usual ones. Each has its own rules:</p>
<ul>
  <li><strong>Their share</strong> of what you earn, a <strong>fee per shift</strong>, a <strong>share of gifts</strong>, a <strong>share of tips</strong>.</li>
  <li><strong>Deductions</strong>: any number, named however the workplace names them. Each is a percentage or an amount, taken <em>off the top</em> (before the house's share) or <em>out of your share</em>, and can be set to apply <em>always</em>.</li>
  <li><strong>Paid out later</strong>: income there starts as "not paid out yet" until the workplace pays you.</li>
  <li><strong>Charges you pay them</strong>: room and board, a house doctor, room hire. Tours at a workplace log these for you.</li>
</ul>
<p>When you add income, the form works out the fees from those rules and shows what you keep. Tick the deductions that applied; they come off in the order the workplace takes them.</p>

<h2>Pay you haven't received yet</h2>
<p>On <em>Income &amp; expenses</em>, <strong>Not paid out to you yet</strong> shows what each workplace owes you. When they pay, press <em>Paid out</em> and say how: it marks everything received.</p>

<h2>How it was paid</h2>
<p>Every income entry can say how it was paid: cash, bank transfer, check, a payment app. It shows in the list and in your records.</p>

<h2>Tips</h2>
<p>Add a tip on a booking (the <em>Tip</em> field) or from the <strong>+ $</strong> button on any page (<em>Money in / Tip / Money out</em>). If the workplace keeps a share of tips, it's worked out and taken off.</p>

<h2>Rates &amp; deposits</h2>
<p><em>Money → Rates</em> is your rate card. Pick a service when you book and its length and price fill in. <em>Copy as text</em> gives you something to send. <strong>Deposits to collect</strong> lists bookings ahead whose deposit hasn't come in; <strong>On an old rate</strong> lists clients whose last booking cost less than your card says now.</p>

<h2>Tours</h2>
<p>A tour (<em>Calendar → + New → Tour</em>) gets its own <strong>tour statement</strong>: income, fees, costs, health tests, and what you kept. Its <strong>tour plan</strong> holds a pack list (from your own templates), a budget against what you actually spend, and meals &amp; snacks whose groceries go onto the pack list. <em>Money → Compare → By tour</em> sets tours side by side, per working day.</p>

<h2>Comparing</h2>
<p><em>Money → Compare</em>: by tour, month, week, kind of work, workplace, persona, <strong>how they found you</strong> (income against ad spend) and <strong>busy times</strong> (a grid of when bookings happen, and what an hour of each kind brings in).</p>

<h2>What an hour really pays</h2>
<p><em>Money → Overview</em> shows what an hour brings in for each kind of work: bookings (their length plus the getting-ready and travel time you set) and your quick logs. The last line takes all your costs off too.</p>

<h2>Steady pay</h2>
<p>For uneven months. Put what comes in into a buffer envelope and pay yourself the same amount every week. Sworkr suggests a careful amount from your last six months and says how many weeks your buffer covers.</p>

<h2>Wallet</h2>
<p><em>Money → Wallet</em> holds savings goals and <strong>envelopes</strong>. A goal has a target; an envelope is just money in and out (your own wallet, spending money for a tour). An envelope can also show what a workplace is keeping for you until payout. Choose which ones show on the dashboard.</p>

<h2>Bank</h2>
<p><em>Money → Bank</em> brings in your bank's transactions through <a href="https://bridge.simplefin.org">SimpleFIN Bridge</a>, an independent service you sign up to yourself (your bank password goes to them, never to Sworkr). Paste its setup token once. Each transaction then waits for you: add it as an expense or income with a tap, or ignore it. Nothing is added by itself.</p>

<h2>Taxes</h2>
<p><em>Money → Taxes</em> adds up the year: income by kind, fees, expenses by category, your profit, mileage and estimated payments, with quarterly due dates and reminders. <strong>Download as CSV</strong> gives your accountant a spreadsheet; <em>Print or save as PDF</em> gives a page. Sworkr adds up your records. It isn't tax advice.</p>
<p>Keep a <strong>license or work card</strong> under <em>Settings → My work → Licenses &amp; documents</em>, tied to a workplace if it's for one, and when you renew it press <em>Renewed</em> to move the date and log what you paid under Fees &amp; licenses.</p>
"""),

("content", "Content & planning", "Content &amp; planning", """
<h2>The calendar plans everything</h2>
<p><em>Calendar</em> shows bookings, tours, time off and health tests, and also what you've planned: <strong>posts to put up</strong>, <strong>shoots</strong> and <strong>the day each ad runs out</strong>. Tick or untick <em>Planning</em> at the bottom to show only what you want. <em>+ New</em> adds a booking, a post or a shoot. Click a planned item to open it. <em>Posts</em> and <em>Shoots</em> at the top hold the full lists.</p>

<h2>Posts</h2>
<p>Write the caption, pick the platform and time. For <strong>Bluesky, Mastodon and Reddit</strong>, connect your account under <em>Content → Social</em> and Sworkr can post it now or by itself at its time, with a content label and a description of each picture (alt text). Elsewhere, copy the caption when it's due, post it yourself, then mark it posted with the link and how many inquiries it brought. <em>Content → Social</em> also shows likes, reposts and replies, fetched or imported from a platform's CSV export.</p>
<ul>
  <li><strong>One post, many platforms.</strong> <em>Also post it on</em> makes a row per platform, each with its own caption and time.</li>
  <li><strong>Your platforms</strong> (<em>Content → Promote → Platforms &amp; saved text</em>): each account or channel with its rules and how often you may post there. Planning a post too soon after the last one warns you.</li>
  <li><strong>Saved text</strong>: links, hashtags, your booking line: one tap to add to a caption.</li>
</ul>

<h2>Shoots</h2>
<p><em>Calendar → Shoots</em> plans a content shoot in one place: the date, the place and what to know about it, the people (photographer, co-star, makeup) and <strong>what you agreed about the content</strong>, goals, shot list, wardrobe, what to prepare, a budget and the marketing plan. It warns you about what's missing as the day gets close, and <strong>nobody on camera is "done" until their ID is checked and their release signed</strong>. Pay a budget line or a fee and it's logged as an expense against the shoot. <em>Start a campaign for it</em> carries the shoot into your promotion.</p>

<h2>Promote</h2>
<p><em>Content → Promote</em> holds <strong>campaigns</strong> (a push with a goal and dates, such as a tour announcement or a set launch, with its posts together) and <strong>ads</strong> (each listing's site, end date and cost; <em>Renewed</em> moves the date and logs the cost). For a tour campaign, <em>Suggest tour posts</em> adds the usual run of ideas: a week before, the day before, arrival, last day.</p>

<h2>Library</h2>
<p><em>Content → Library</em> shows the folder you already keep your photos and videos in, from Nextcloud, a Synology or other WebDAV server, or a folder on your computer. Each subfolder is a set. Sworkr only <em>reads</em> it, never copies or changes anything, and shows where each file has already been posted. Connect it under <em>Settings → Connections → Content library</em>.</p>

<h2>A persona's kit</h2>
<p>Under <em>Settings → My work → Personas</em>, <em>Kit</em> keeps what goes with each name you work under: a bio for each platform, your social links and wishlist links, each one tap to copy.</p>

<h2>Customs</h2>
<p><em>Content → Customs</em> follows made-to-order content from request to delivery: who asked, what they want, the price, what's paid, when it's due. <em>Got paid</em> adds the payment to your income as a sale (minus the platform's fee) and says how it was paid. Sworkr flags customs being made before they're fully paid for, and late ones. <em>Your menu</em> keeps your usual prices and copies as text.</p>
"""),

("health-and-safety", "Health & safety", "Health &amp; safety", """
<h2>Health tests on your own schedule</h2>
<p>Testing rules differ from place to place, so nothing is fixed. <em>Settings → Health → Health tests</em>: each test has a name, how many days apart it's due, and what it usually costs. Everyone starts with weekly, monthly and yearly, and you can rename them, change how often, add others (like "Quarterly bloodwork" every 90 days) or switch off what you don't use. Sworkr works out when the next one is due from the last, and shows it on the dashboard before then. A test's cost fills in when you add it to the calendar and is logged as an expense.</p>

<h2>Documents that expire</h2>
<p><em>Settings → My work → Licenses &amp; documents</em>: a license, work card, ID, passport, health card, a platform's ID check, insurance. Each gets a reminder before it runs out, and shows on the calendar. Sworkr keeps names and dates only: <strong>there's no field for ID or license numbers, on purpose.</strong></p>

<h2>Supplies</h2>
<p>The <em>Supplies</em> card on your dashboard is a short stock list. Tap minus when you use one; what's running low shows at the top.</p>

<h2>Safety check-in</h2>
<p><em>Settings → Safety → Safety check-in</em> sets up a trusted contact. Tick <em>Safety check-in</em> on a booking; if you haven't checked in afterwards (within the grace time you set), your contact is emailed what you chose to share. This needs email set up under <em>Connections</em>, or a <strong>push address</strong>: your contact installs the free ntfy app and subscribes to a long random name you agree on. A push arrives in seconds, where email can take minutes.</p>
<p>The <strong>safety timer</strong> on the dashboard uses the same contact for anything that isn't a booking. If the alert already went out when you tap <em>I'm safe</em>, your contact gets an all-clear.</p>

<h2>Incident log and privacy check-up</h2>
<p>The incident log is under <em>Settings → Safety</em>, the privacy check-up under <em>Settings → Security &amp; privacy</em>. The incident log is for writing down what happened the same day: when, what, who, and what you kept. It's never sent anywhere. The privacy check-up is a checklist for keeping work and private life apart.</p>

<h2>Period tracker, birth control and regular meds</h2>
<p>Optional, off until you turn them on. Injections can rotate sites and step up doses on a schedule. Dates show on the calendar, and medication marked discreet shows only as "Health".</p>

<h2>Daily check-in</h2>
<p>Also optional (<em>Settings → Health → Daily check-in</em>): a check-in on the dashboard for sleep, water, how well you ate and your energy. After a few weeks it shows how your earnings compare on better and worse days. Sleep and water can be filled in from an iPhone's Health app export.</p>

<h2>Holidays</h2>
<p><em>Settings → My work → Holidays</em> puts your country's public holidays on the calendar. They're worked out on your own computer: no calendar is downloaded from anyone.</p>
"""),

("notifications", "Notifications", "Notifications", """
<p>Sworkr can send a message to your phone when it isn't open, using <strong>ntfy</strong>, a free app for iPhone and Android. Nothing is sent unless you turn it on. Set it up under <em>Settings → Notifications → Phone notifications</em>.</p>

<h2>What you get</h2>
<ul>
  <li>A <strong>heads-up before a booking or health test</strong>: 15 minutes to 4 hours before, as you choose. "A booking starts at 7:00 PM".</li>
  <li>A <strong>daily summary</strong> at the hour you choose: counts such as "2 bookings today, 1 deposit to collect, 1 post to put up". It's only sent on days there's something to say.</li>
  <li>A note if a <strong>scheduled post couldn't go out</strong>.</li>
</ul>
<p>Each is sent once. The browser notifications under <em>Settings → Notifications</em> still work separately, but only while Sworkr is open.</p>

<h2>Set it up</h2>
<ol>
  <li>Install the <strong>ntfy</strong> app on your phone.</li>
  <li>In Sworkr, tap <em>Make one</em> next to Topic. It picks a long random name. Turn notifications on and save.</li>
  <li>In the ntfy app, tap <strong>+</strong> and subscribe to the same topic. Then press <em>Send a test</em> in Sworkr.</li>
</ol>

<h2>Keep it private</h2>
<ul>
  <li>The message passes through the ntfy server. On the public one (ntfy.sh), <strong>anyone who knows your topic can read it</strong>. That's why Sworkr insists on a long random topic there. Never share it.</li>
  <li>The wording is generic by default. Ticking <em>Name clients in the messages</em> puts names in them, so keep it off on the public server.</li>
  <li>For real privacy, <a href="https://docs.ntfy.sh/install/">run your own ntfy server</a>, or use one a friend runs, and put its address in. An access token for your server is stored sealed and is never sent to a different server.</li>
  <li>Sworkr only sends from your own computer, so it has to be on (and awake) at the time.</li>
</ul>
"""),

("own-your-data", "Own your data", "Own your data", """
<p class="lead">Sworkr runs on your computer so that your records are yours: no company holds them, reads them, sells them, or hands them over. The same idea works for much more of your life.</p>

<h2>Why it matters for this work</h2>
<ul>
  <li>Apps and payment services close accounts of people in this work without warning, and take the records with them.</li>
  <li>Anything a company holds can be lost in a breach, sold, or handed over when asked. What's only on your computer can't be.</li>
  <li>Your client list, your money and your health are the most private things you have. They're safest where only you hold the key.</li>
</ul>

<h2>Other things you can run yourself</h2>
<p>All free, and all fine to set up later, one at a time. Each replaces a company that would otherwise hold that part of your life.</p>
<ul>
  <li><strong><a href="https://nextcloud.com">Nextcloud</a></strong>: files, photos, calendar and contacts (instead of iCloud or Google). Sworkr syncs its calendar and reads your content from it.</li>
  <li><strong><a href="https://adguard.com/en/adguard-home/overview.html">AdGuard Home</a></strong>: blocks ads and trackers for every device on your home network.</li>
  <li><strong><a href="https://github.com/dani-garcia/vaultwarden">Vaultwarden</a></strong>: a password manager (works with the Bitwarden apps).</li>
  <li><strong><a href="https://immich.app">Immich</a></strong>: a photo library with phone backup, like Google Photos.</li>
  <li><strong><a href="https://ntfy.sh">ntfy</a></strong>: notifications to your phone, from your own server.</li>
  <li><strong>A local AI</strong> (LM Studio, Ollama): Sworkr's assistant can use it, so your questions never leave home.</li>
  <li><strong><a href="https://headscale.net">Headscale</a></strong>: run the part of Tailscale that connects your devices.</li>
</ul>
<p>A small always-on computer (a NAS, a mini PC, a Raspberry Pi 4 or 5) can run all of these together, and Sworkr with them.</p>

<h2>A VPN, and when it helps</h2>
<p>A VPN hides what you do online from the network you're on, and hides where you are from the sites you visit. It's worth turning on:</p>
<ul>
  <li>On hotel, Airbnb, café and airport Wi-Fi, especially on tour.</li>
  <li>When you look up a client, a venue or an address, so searches can't be tied back to your home.</li>
  <li>When you post or log in to work accounts from somewhere you don't want linked to them.</li>
</ul>
<p>Choose one that doesn't keep logs and lets you pay without your name (<a href="https://mullvad.net">Mullvad</a> and <a href="https://proton.me/vpn">Proton VPN</a> are widely trusted). On a phone, only one VPN-type app runs at a time, and Tailscale is one: use Tailscale's exit-node or Mullvad option to have both. A VPN can slow Docker's first download: pause it for that.</p>

<h2>Small habits that add up</h2>
<ul>
  <li>Go through <em>Settings → Security &amp; privacy → Privacy check-up</em> once, and again every few months.</li>
  <li>Keep a copy of your backups somewhere other than this computer (<a href="/docs/privacy-and-backups.html">how</a>).</li>
  <li>Update Sworkr when there's a new version: double-click <em>Update sworkr</em>.</li>
</ul>
"""),

("troubleshooting", "If something goes wrong", "If something goes wrong", """
<h2>Sworkr won't start</h2>
<ul>
  <li><strong>Windows app:</strong> if a message says Sworkr couldn't start, it gives the file with the details (<code>sworkr.log</code> in the Sworkr data folder). If another program is using port 8765, close it, or start Sworkr with the <code>SWORKR_PORT</code> setting set to another number.</li>
  <li><strong>Docker:</strong> "Docker isn't running": open Docker Desktop and wait for <em>Engine running</em>.</li>
  <li><strong>"Port is already allocated":</strong> something else uses port 8008. Make a setup file with another port in the <a href="/docs/install.html">setup builder</a>.</li>
  <li><strong>Windows, "WSL" messages:</strong> Docker Desktop needs Windows' Linux part. Let it install or update it, then restart the computer.</li>
  <li><strong>Mac, "unidentified developer":</strong> right-click <em>Start sworkr.command</em> and choose <em>Open</em>.</li>
  <li><strong>The download stalls:</strong> a VPN can get in Docker's way. Pause it while Sworkr downloads the first time, then turn it back on.</li>
</ul>

<h2>I forgot my password</h2>
<p>Docker: open a terminal in the Sworkr folder and run<br><code>docker compose exec sworkr python manage.py reset-password</code><br>Windows app: ask the other admin on your copy, or restore a backup from before. If you have a passkey set up on a device, you can sign in with that.</p>

<h2>I lost my phone and my recovery codes</h2>
<p>Docker: <code>docker compose exec sworkr python manage.py turn-off-two-step &lt;username&gt;</code>. Then set two-step sign-in up again and save new recovery codes on paper.</p>

<h2>"The database can't be opened"</h2>
<p>The key that locks it is missing: the Credential Manager entry was deleted, the <code>sworkr_sworkr_keys</code> volume was removed, or the data was copied to another computer without its key. Install fresh and restore your latest backup with its passphrase.</p>

<h2>My saved email or calendar password stopped working</h2>
<p>That happens after a restore on another computer: the saved passwords are sealed with a key that stays on the computer they were saved on. Type the password in again once.</p>

<h2>Never do these</h2>
<ul>
  <li>Run <code>docker compose down -v</code>, or delete the <code>sworkr_sworkr_data</code> or <code>sworkr_sworkr_keys</code> volumes. That is your data and the key that opens it.</li>
  <li>Open Sworkr's port on your router, or point a public address at it.</li>
</ul>
"""),
]


def page(slug, title, heading, body):
    menu = "\n".join(
        f'      <li><a href="/docs/{s}.html"{" aria-current=\"page\"" if s == slug else ""}>{html.escape(m)}</a></li>'
        for s, m, _, _ in PAGES)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{html.unescape(heading)} · Sworkr docs</title>
  <meta name="robots" content="index,follow" />
  <meta name="referrer" content="no-referrer" />
  <meta name="theme-color" content="#a73178" />
  <link rel="icon" type="image/png" href="/icon.png" />
  <link rel="stylesheet" href="/style.css" />
</head>
<body class="docs">
  <header class="top">
    <a class="brand" href="/"><span class="mark">SW</span> Sworkr</a>
    <nav>
      <a href="/">Home</a>
      <a href="/docs/">Docs</a>
      <a class="pill" href="https://demo.sworkr.com">Try the demo</a>
    </nav>
  </header>
  <div class="doc-layout">
    <aside>
      <p class="side-title">Documentation</p>
      <ul>
{menu}
      </ul>
    </aside>
    <main class="doc">
      <h1>{heading}</h1>
{body}
    </main>
  </div>
  <footer>
    <p><span class="mark small">SW</span> Sworkr. Software for s workers, kept on your own computer.</p>
    <p class="fine">Sworkr is a record-keeping tool. It doesn't advertise, arrange or take part in anyone's work, and it isn't tax or legal advice.</p>
  </footer>
</body>
</html>
"""


def main():
    os.makedirs(OUT, exist_ok=True)
    for slug, menu, heading, body in PAGES:
        with open(os.path.join(OUT, f"{slug}.html"), "w", encoding="utf-8", newline="\n") as f:
            f.write(page(slug, menu, heading, body))
    print(f"Wrote {len(PAGES)} pages to {OUT}")


if __name__ == "__main__":
    main()
