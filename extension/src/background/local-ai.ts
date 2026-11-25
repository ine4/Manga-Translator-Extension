/** Ephemeral browser-session leases; URLs/hostnames never sent to Rust or stored on disk. */
import type { AppSettings, TranslateRequest } from '../shared/types.js';

const ROOT = 'http://127.0.0.1:7678';
const SESSION = 'manga_local_session';
const ALARM = 'manga-local-reconcile';
const SETTINGS = 'manga_translator_settings';
export type Pins = { id: string; hosts: string[]; windows: number[] };

export function localControlSender(sender: {id?: string; url?: string}, extensionId: string): boolean {
  return sender.id === extensionId && sender.url === `chrome-extension://${extensionId}/popup/index.html`;
}

export function effectiveBackend(settings: AppSettings): string {
  return settings.localAiEnabled ? 'http://127.0.0.1:7677' : settings.backendUrl;
}
export function effectiveRequest(body: TranslateRequest, settings: AppSettings): TranslateRequest {
  if (!settings.localAiEnabled) return { ...body, input_language: body.input_language === 'Auto' ? 'Japanese' : body.input_language };
  return {
    ...body, provider: 'Local', model_name: settings.localModel,
    base_url: undefined, api_key: undefined, translation_mode: 'one-step', ocr_method: 'LLM',
  };
}
export function hostname(url?: string): string | null {
  try {
    const u = new URL(url ?? '');
    return u.protocol === 'https:' || u.protocol === 'http:' ? u.hostname.toLowerCase() : null;
  } catch { return null; }
}
async function getPins(): Promise<Pins> {
  const old = (await chrome.storage.session.get(SESSION))[SESSION] as Pins | undefined;
  return old ?? { id: 'browser:' + crypto.randomUUID(), hosts: [], windows: [] };
}
async function savePins(pins: Pins): Promise<void> {
  // session storage is cleared when the extension/browser session ends.
  await chrome.storage.session.set({ [SESSION]: pins });
}
async function localFetch(path: string, body?: unknown): Promise<Record<string, unknown>> {
  const res = await fetch(ROOT + path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'X-Manga-Local': '1', 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(150_000),
  });
  const result = await res.json() as Record<string, unknown>;
  if (!res.ok) {
    const error = result.error as { message?: string } | undefined;
    throw new Error(error?.message ?? 'Local controller request failed');
  }
  return result;
}

// Serialize mutations and recomputations across tab, alarm and popup events.
let tail: Promise<unknown> = Promise.resolve();
function ordered<T>(op: () => Promise<T>): Promise<T> {
  const next = tail.catch(() => undefined).then(op);
  tail = next.catch(() => undefined);
  return next;
}
export function prunePins(pins: Pins, tabs: Array<{url?: string; windowId: number}>, enabled: boolean): Pins {
  const hosts = new Set(tabs.map(tab => hostname(tab.url)).filter(Boolean));
  const windows = new Set(tabs.map(tab => tab.windowId));
  return {
    id: pins.id,
    hosts: enabled ? pins.hosts.filter(host => hosts.has(host)) : [],
    windows: enabled ? pins.windows.filter(windowId => windows.has(windowId)) : [],
  };
}

async function reconcile(settings: AppSettings, pins: Pins, tabs?: chrome.tabs.Tab[]): Promise<Record<string, unknown>> {
  pins = prunePins(pins, tabs ?? await chrome.tabs.query({}), settings.localAiEnabled);
  const keep = pins.hosts.length > 0 || pins.windows.length > 0;
  await savePins(pins);
  if (keep) {
    await chrome.alarms.create(ALARM, { periodInMinutes: 0.5 });
  } else {
    await chrome.alarms.clear(ALARM);
  }
  return localFetch('/local/lease', { id: pins.id, model: settings.localModel, keep });
}

export async function purgeLegacyImages(): Promise<void> {
  const data = await chrome.storage.local.get(null);
  const keys = Object.keys(data).filter(k => k === 'mt_translated_cache' || k.startsWith('mt_translated_cache:'));
  if (keys.length) await chrome.storage.local.remove(keys);
}

export function installLocalLifecycle(getSettings: () => Promise<AppSettings>): void {
  const refresh = () => {
    void ordered(async () => {
      const pins = await getPins();
      if (pins.hosts.length || pins.windows.length) {
        await reconcile(await getSettings(), pins);
      }
    }).catch(() => { /* Expiring Rust leases recover from a closed/crashed browser. */ });
  };
  chrome.tabs.onRemoved.addListener(refresh);
  chrome.tabs.onUpdated.addListener((_id, info) => { if (info.url || info.status === 'complete') refresh(); });
  chrome.windows.onRemoved.addListener(refresh);
  chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === ALARM) refresh(); });
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local' || !changes[SETTINGS]) return;
    const before = changes[SETTINGS].oldValue as AppSettings | undefined;
    const after = changes[SETTINGS].newValue as AppSettings | undefined;
    if (before?.localAiEnabled !== after?.localAiEnabled || before?.localModel !== after?.localModel) refresh();
  });
  chrome.runtime.onStartup.addListener(() => { void purgeLegacyImages(); refresh(); });
}

export async function handleLocalMessage(message: { type: string }, settings: AppSettings): Promise<Record<string, unknown>> {
  if (message.type === 'LOCAL_STATUS') return localFetch('/local/models');
  return ordered(async () => {
    const pins = await getPins();
    if (message.type === 'LOCAL_RELEASE') {
      pins.hosts = []; pins.windows = [];
      return reconcile(settings, pins);
    }
    if (!settings.localAiEnabled) throw new Error('Enable Local AI first');
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) throw new Error('No active browser tab');
    if (message.type === 'LOCAL_PIN_SITE') {
      const host = hostname(tab.url);
      if (!host) throw new Error('Open a normal HTTP or HTTPS site first');
      if (!pins.hosts.includes(host)) pins.hosts.push(host);
    } else if (message.type === 'LOCAL_PIN_WINDOW') {
      if (!pins.windows.includes(tab.windowId)) pins.windows.push(tab.windowId);
    } else throw new Error('Unknown local control');
    return reconcile(settings, pins);
  });
}
