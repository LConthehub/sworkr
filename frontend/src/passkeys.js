import axios from 'axios';

// Passkeys (WebAuthn). The server sends options as JSON with binary fields in base64url; the browser wants
// ArrayBuffers, and its answer has to go back as base64url JSON. Done by hand here, so it works in browsers
// that don't have PublicKeyCredential.parseCreationOptionsFromJSON / toJSON yet.

const toBuffer = (b64url) => {
  const b64 = b64url.replace(/-/g, '+').replace(/_/g, '/') + '==='.slice((b64url.length + 3) % 4);
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0)).buffer;
};
const toB64url = (buffer) => btoa(String.fromCharCode(...new Uint8Array(buffer))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

/** Can this browser, on this address, use passkeys? (They need https or localhost.) */
export const passkeysSupported = () => typeof window !== 'undefined' && !!window.PublicKeyCredential && window.isSecureContext;

function creationOptions(o) {
  return {
    ...o,
    challenge: toBuffer(o.challenge),
    user: { ...o.user, id: toBuffer(o.user.id) },
    excludeCredentials: (o.excludeCredentials || []).map((c) => ({ ...c, id: toBuffer(c.id) })),
  };
}

function requestOptions(o) {
  return { ...o, challenge: toBuffer(o.challenge), allowCredentials: (o.allowCredentials || []).map((c) => ({ ...c, id: toBuffer(c.id) })) };
}

function credentialJSON(cred) {
  const r = cred.response;
  const response = { clientDataJSON: toB64url(r.clientDataJSON) };
  if (r.attestationObject) {
    response.attestationObject = toB64url(r.attestationObject);
    if (r.getTransports) response.transports = r.getTransports();
  }
  if (r.authenticatorData) {
    response.authenticatorData = toB64url(r.authenticatorData);
    response.signature = toB64url(r.signature);
    if (r.userHandle) response.userHandle = toB64url(r.userHandle);
  }
  return {
    id: cred.id, rawId: toB64url(cred.rawId), type: cred.type, response,
    authenticatorAttachment: cred.authenticatorAttachment || undefined,
    clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {},
  };
}

/** A cancelled or timed-out browser prompt: nothing to report. */
export const passkeyCancelled = (err) => err?.name === 'NotAllowedError' || err?.name === 'AbortError';

/** Make a passkey for the signed-in account on this device. */
export async function addPasskey(name) {
  const { data: begin } = await axios.post('/api/account/passkeys/begin');
  const cred = await navigator.credentials.create({ publicKey: creationOptions(begin.options) });
  const { data } = await axios.post('/api/account/passkeys/finish', { challenge: begin.challenge, credential: credentialJSON(cred), name });
  return data;
}

/** Sign in with a passkey. Returns the user, as the password login does. */
export async function signInWithPasskey() {
  const { data: begin } = await axios.post('/api/auth/passkey/begin');
  const cred = await navigator.credentials.get({ publicKey: requestOptions(begin.options) });
  const { data } = await axios.post('/api/auth/passkey/finish', { challenge: begin.challenge, credential: credentialJSON(cred) });
  return data;
}
