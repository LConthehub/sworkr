import { useEffect, useState } from 'react';
import axios from 'axios';
import { inputClass, errorMessage, buttonClass, quietButtonClass } from './Modal';

/** Settings > Look > Home screen: your own plain name and picture, for a phone that adds sworkr to its home screen. */
export default function HomeScreenSettings() {
  const [data, setData] = useState(null);
  const [name, setName] = useState('');
  const [message, setMessage] = useState('');
  const [stamp, setStamp] = useState(Date.now());   // makes the preview fetch the new picture
  useEffect(() => {
    axios.get('/api/branding').then(({ data: d }) => { setData(d); setName(d.name === 'Sworkr' || (!d.own && !d.shared) ? '' : d.name); }).catch(() => {});
  }, []);
  if (!data) return null;
  const save = async (body) => {
    setMessage('');
    try {
      const { data: d } = await axios.put('/api/branding', body);
      setData(d);
      setStamp(Date.now());
      window.dispatchEvent(new Event('sworkr-branding'));
      setMessage('Saved. Phones that add sworkr from now on get this. One already on a home screen: remove it and add it again.');
    } catch (err) {
      setMessage(errorMessage(err, "Couldn't save"));
    }
  };
  const pick = (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => save({ name, icon: reader.result });
    reader.readAsDataURL(file);
  };
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-4">
        <img src={`/api/branding/icon-180.png?k=${encodeURIComponent(data.key)}&v=${stamp}`} alt="" className="w-16 h-16 rounded-2xl shadow" />
        <div className="text-sm text-gray-700">
          On a home screen it shows as <b>{data.name}</b>{data.custom_icon ? ', with your picture' : ''}.
        </div>
      </div>
      <>
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-xs text-gray-500">Name on the home screen
              <input value={name} onChange={(e) => setName(e.target.value)} maxLength={30} placeholder="e.g. Notes, Planner" className={`${inputClass} block`} />
            </label>
            <button type="button" onClick={() => save({ name })} className={quietButtonClass}>Save name</button>
          </div>
          <div className="flex flex-wrap gap-2">
            <label className={`${buttonClass} cursor-pointer`}>Choose a picture<input type="file" accept="image/*" onChange={pick} className="hidden" /></label>
            {(data.shared ? data.custom_icon : data.own) && <button type="button" onClick={() => save({ name: data.shared ? name : '', reset_icon: true })} className={quietButtonClass}>{data.shared ? 'Back to the sworkr icon' : 'Back to the shared one'}</button>}
          </div>
          <p className="text-xs text-gray-500">
            Any photo works: it's cut to a square. A plain one (a flower, a notebook) draws less attention than a logo.
            {data.shared ? ' Yours is also what everyone else on this sworkr gets until they choose their own.' : ' This is yours alone: others on this sworkr have their own.'}
            {' '}Then, on the phone, open sworkr at its Tailscale or own web address and add it to the
            home screen (iPhone: Share, Add to Home Screen; Android: the menu, Add to Home screen).
          </p>
      </>
      {message && <p className="text-sm text-gray-700">{message}</p>}
    </div>
  );
}
