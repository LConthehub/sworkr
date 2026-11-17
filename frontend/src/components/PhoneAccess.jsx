import { useState } from 'react';
import { Link } from 'react-router-dom';

/**
 * Account → Connections → On your phone. sworkr only answers on this computer. The safe way to reach it from a
 * phone is a private network between your own devices (Tailscale): nothing is opened to the internet, and the
 * phone gets a real https address, so passkeys and Add to Home Screen work.
 */
export default function PhoneAccess() {
  const here = window.location;
  const onTailnet = here.hostname.endsWith('.ts.net');
  const port = here.port || (here.protocol === 'https:' ? '443' : '80');
  const command = `tailscale serve --bg ${onTailnet ? 'PORT' : port}`;
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* clipboard blocked: the command is on screen */ }
  };

  if (onTailnet) {
    return (
      <div className="space-y-2 text-sm text-gray-700">
        <p className="rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-900 px-3 py-2">
          You're using sworkr through your private address, <b>{here.host}</b>. It works on any of your devices signed in to the same Tailscale account.
        </p>
        <ol className="list-decimal pl-5 space-y-1">
          <li><b>Put it on your home screen:</b> in Safari tap Share, then <i>Add to Home Screen</i> (Android: Chrome's menu, <i>Add to Home screen</i>).</li>
          <li><b>Add a passkey on this phone:</b> <Link to="/account/privacy#passkeys" className="underline text-sworkr-600">Security & privacy → Passkeys</Link>, so you can sign in with your face or fingerprint.</li>
          <li>Consider <Link to="/account/privacy#away" className="underline text-sworkr-600">Away from home → passkeys only</Link>, so a password alone can't sign in from anywhere but this computer.</li>
        </ol>
      </div>
    );
  }

  return (
    <div className="space-y-3 text-sm text-gray-700">
      <p>
        sworkr only answers on this computer, on purpose. To use it from your phone without opening it to the internet,
        connect your phone and this computer with <b>Tailscale</b>: a free app that makes a private network between your own
        devices. Only devices signed in to your Tailscale account can reach sworkr, and the connection is encrypted end to end.
      </p>
      <ol className="list-decimal pl-5 space-y-2">
        <li>
          <b>Install Tailscale on this computer and on your phone</b> from <span className="whitespace-nowrap">tailscale.com/download</span> (or
          the App Store / Google Play), and sign in to the same account on both. Use an email you keep private.
        </li>
        <li>
          <b>On this computer, open a terminal and run this once:</b>
          <span className="flex flex-wrap items-center gap-2 mt-1">
            <code className="rounded bg-gray-100 px-2 py-1 text-gray-800">{command}</code>
            <button type="button" onClick={copy} className="text-xs px-2.5 py-1 rounded-full border border-gray-200 text-gray-600 hover:bg-gray-50">{copied ? 'Copied ✓' : 'Copy'}</button>
          </span>
          <span className="block text-xs text-gray-500 mt-1">
            Windows: right-click Start, choose <i>Terminal</i>. Mac: open <i>Terminal</i> from Applications → Utilities. If it asks you to turn on
            HTTPS for your network, follow the link it gives; that's what lets passkeys work.
          </span>
        </li>
        <li>
          <b>It prints your private address</b>, something like <i>https://your-computer.tail1234.ts.net</i>. Open that in your phone's browser
          and sign in. This page then shows the last steps: putting sworkr on your home screen and adding a passkey on the phone.
        </li>
      </ol>
      <p className="text-xs text-gray-500">
        This computer has to be on and awake for the phone to reach it. Tailscale knows which devices are on your network, but not what you do in
        sworkr: the connection to it is encrypted from your phone to this computer. To stop it, run <code>tailscale serve reset</code>.
      </p>
      <p className="text-xs text-gray-500">
        Don't forward a port on your router or point a public web address at sworkr unless you know how to secure it: it holds your most
        sensitive records.
      </p>
    </div>
  );
}
