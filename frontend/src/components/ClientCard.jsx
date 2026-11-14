import { colorFor, nextBirthday, SCREENING_STYLES } from '../colors';
import { PersonaBadge } from './Personas';

export function ScreeningBadge({ client }) {
  if (client.do_not_see) {
    return <span className="px-2 py-0.5 bg-red-600 text-white rounded-full text-xs font-semibold">Do not see</span>;
  }
  const s = SCREENING_STYLES[client.screening_status] || SCREENING_STYLES.unscreened;
  return <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${s.badge}`}>{s.label}</span>;
}

export default function ClientCard({ client, onClick }) {
  const tags = client.tags || [];
  const birthday = nextBirthday(client.birthday);

  return (
    <div
      onClick={onClick}
      onKeyDown={(e) => onClick && (e.key === 'Enter' || e.key === ' ') && onClick()}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      className={`bg-white rounded-xl shadow-sm hover:shadow-md transition-all p-4 border ${
        client.do_not_see ? 'border-red-300' : 'border-gray-100'
      } ${onClick ? 'cursor-pointer hover:-translate-y-0.5' : ''}`}
    >
      <div className="flex items-center gap-3 mb-3">
        <div
          className="w-10 h-10 shrink-0 rounded-lg flex items-center justify-center font-bold text-white text-lg"
          style={{ background: colorFor(client.display_name || '') }}
        >
          {(client.display_name || '?').replace(/^@/, '').charAt(0).toUpperCase()}
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-base font-semibold text-gray-800 truncate">{client.display_name}</h3>
          {client.name && client.name !== client.display_name && <p className="text-xs text-gray-500 truncate">{client.name}</p>}
          {client.persona_id && <p className="mt-0.5"><PersonaBadge id={client.persona_id} /></p>}
          {client.industry && <p className="text-xs text-gray-500 truncate">{client.industry}</p>}
          {client.couple_name && <p className="text-xs text-sworkr-600 truncate">💞 Couple with {client.couple_name}</p>}
          {!client.industry && client.bio && <p className="text-xs text-gray-500 truncate">{client.bio}</p>}
        </div>
      </div>

      {client.email && <p className="text-sm text-gray-500 truncate">{client.email}</p>}
      {client.contact_phone && <p className="text-sm text-gray-500">{client.contact_phone}</p>}

      {tags.length > 0 && (
        <div className="flex flex-wrap gap-2 mt-2">
          {tags.map((tag) => (
            <span
              key={tag}
              className="px-3 py-1 rounded-full text-xs font-medium text-white"
              style={{ background: colorFor(tag) }}
            >
              #{tag}
            </span>
          ))}
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        {client.role === 'partner' && <span className="px-2 py-0.5 bg-violet-100 text-violet-700 rounded-full text-xs font-medium">Co-worker</span>}
        {client.role === 'crew' && <span className="px-2 py-0.5 bg-sky-100 text-sky-700 rounded-full text-xs font-medium">Crew</span>}
        {(!client.role || client.role === 'client') && <ScreeningBadge client={client} />}
        {!client.is_active && (
          <span className="px-2 py-0.5 bg-gray-100 text-gray-500 rounded-full text-xs font-medium">Inactive</span>
        )}
        {birthday && birthday.days <= 7 && (
          <span className="px-2 py-0.5 bg-sworkr-50 text-sworkr-600 rounded-full text-xs font-medium">
            🎂 {birthday.days === 0 ? 'Birthday today' : birthday.days === 1 ? 'Birthday tomorrow' : `Birthday in ${birthday.days} days`}
          </span>
        )}
      </div>
    </div>
  );
}
