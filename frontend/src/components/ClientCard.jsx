import { colorFor } from '../colors';

export default function ClientCard({ client, onClick }) {
  const tags = client.tags || [];

  return (
    <div
      onClick={onClick}
      className={`bg-white rounded-xl shadow-sm hover:shadow-md transition-all hover:-translate-y-1 p-4 border border-gray-100 ${onClick ? 'cursor-pointer' : ''}`}
    >
      <div className="flex items-center gap-3 mb-3">
        <div
          className="w-10 h-10 rounded-lg flex items-center justify-center font-bold text-white text-lg"
          style={{ background: colorFor(client.name) }}
        >
          {client.name.charAt(0).toUpperCase()}
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-base font-semibold text-gray-800 truncate">{client.name}</h3>
          {client.bio && <p className="text-xs text-gray-500 truncate">{client.bio}</p>}
        </div>
      </div>

      {client.email && <p className="text-sm text-gray-500">{client.email}</p>}
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

      <div className="mt-2">
        {client.is_active ? (
          <span className="px-2 py-0.5 bg-green-100 text-green-700 rounded-full text-xs font-medium">Active</span>
        ) : (
          <span className="px-2 py-0.5 bg-red-100 text-red-700 rounded-full text-xs font-medium">Inactive</span>
        )}
      </div>
    </div>
  );
}
