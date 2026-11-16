import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { clearPersonaCache } from './components/Personas';
import { clearTestKindCache } from './components/TestKinds';
import { CATEGORY_COLORS, CATEGORY_LABELS } from './colors';

/** For requests the page makes on a timer. The server doesn't count these as "the user is active". */
export const BACKGROUND = { headers: { 'X-Background': '1' } };

/** Every record from a list endpoint, fetching page after page. */
export async function fetchAll(url, params = {}, pageSize = 500) {
  const all = [];
  for (let page = 1; page <= 200; page++) {
    const { data } = await axios.get(url, { params: { ...params, limit: pageSize, page } });
    all.push(...data);
    if (data.length < pageSize) break;
  }
  return all;
}

/**
 * Save an appointment, asking the server for warnings first (a do-not-see client, overlapping bookings).
 * Returns { data } when saved, or { warnings } when the user should confirm; call again with confirmed=true.
 */
export async function saveAppointment(method, url, body, confirmed = false) {
  try {
    const { data } = await axios({ method, url, data: body, params: { ...(confirmed ? {} : { warn: true }), tz_offset: body?.scheduled_date ? new Date(body.scheduled_date).getTimezoneOffset() : 0 } });
    return { data };
  } catch (err) {
    const detail = err?.response?.data?.detail;
    if (err?.response?.status === 409 && detail?.code === 'needs_confirmation') {
      return { warnings: detail.warnings };
    }
    throw err;
  }
}

/** Hand the browser a file to save. */
export function downloadBlob(content, filename, type = 'text/csv;charset=utf-8') {
  const blob = content instanceof Blob ? content : new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Rows of values as CSV text that Excel, Numbers and Google Sheets open correctly. */
export function toCsv(header, rows) {
  const cell = (value) => {
    let text = value == null ? '' : String(value);
    // Text that starts like a formula is neutralised; plain numbers (including negative ones) are left alone.
    if (/^[=+\-@\t\r]/.test(text) && !/^-?\d+(\.\d+)?$/.test(text)) text = `'${text}`;
    return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  return '﻿' + [header, ...rows].map((r) => r.map(cell).join(',')).join('\r\n') + '\r\n';
}

// ----- the user's own expense categories -----
let categoryCache = null;
const categoryListeners = new Set();

/** Load (or reload) the category list and tell every page using it. */
export async function reloadCategories() {
  const { data } = await axios.get('/api/expense-categories');
  categoryCache = data;
  categoryListeners.forEach((fn) => fn(data));
  return data;
}

/**
 * The user's expense categories: { list, label(key), color(key), reload }.
 * `list` has every category (hidden ones too, with hidden: true), in order.
 */
export function useCategories() {
  const [list, setList] = useState(categoryCache || []);
  useEffect(() => {
    categoryListeners.add(setList);
    if (!categoryCache) reloadCategories().catch(() => {});
    return () => categoryListeners.delete(setList);
  }, []);
  const find = useCallback((key) => list.find((c) => c.key === key), [list]);
  const label = (key) => find(key)?.label || CATEGORY_LABELS[key] || key;
  const topOf = (key) => find(key)?.parent_key || key;
  return {
    list,
    label,
    color: (key) => find(key)?.color || CATEGORY_COLORS[key] || '#9ca3af',
    /** Main categories, in order. */
    tops: list.filter((c) => !c.parent_key),
    /** A main category's subcategories, in order. */
    subsOf: (key) => list.filter((c) => c.parent_key === key),
    /** The main category a category belongs to (itself, if it's a main one). */
    topOf,
    /** "Workspace › Room & board", or just the name for a main category. */
    fullLabel: (key) => (find(key)?.parent_key ? `${label(find(key).parent_key)} › ${label(key)}` : label(key)),
    reload: reloadCategories,
  };
}

/** Forget cached data when someone logs out, so the next person never sees it. */
export function clearCaches() {
  categoryCache = null;
  clearPersonaCache();
  clearTestKindCache();
}
