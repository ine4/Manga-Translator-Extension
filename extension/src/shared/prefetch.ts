/** Bounded, abortable document-memory image preparation; never persistent storage. */
export class ImagePrefetch {
  private entries = new Map<string, { controller: AbortController; promise: Promise<void>; data?: string }>();
  private bytes = 0;
  readonly maxItems: number;
  readonly maxBytes: number;
  constructor(maxItems = 2, maxBytes = 16 * 1024 * 1024) { this.maxItems = maxItems; this.maxBytes = maxBytes; }

  warm(url: string, load: (signal: AbortSignal) => Promise<string | null>): void {
    if (this.entries.has(url) || this.entries.size >= this.maxItems) return;
    const entry = { controller: new AbortController(), promise: Promise.resolve(), data: undefined as string | undefined };
    this.entries.set(url, entry);
    entry.promise = load(entry.controller.signal).then(data => {
      if (entry.controller.signal.aborted || this.entries.get(url) !== entry) return;
      if (!data || this.bytes + data.length * 2 > this.maxBytes) { this.entries.delete(url); return; }
      entry.data = data;
      this.bytes += data.length * 2;
    }).catch(() => { if (this.entries.get(url) === entry) this.entries.delete(url); });
  }

  async take(url: string): Promise<string | null> {
    const entry = this.entries.get(url);
    if (!entry) return null;
    await entry.promise;
    if (this.entries.get(url) !== entry) return null;
    this.entries.delete(url);
    if (entry.data) this.bytes -= entry.data.length * 2;
    return entry.data ?? null;
  }

  clear(): void {
    for (const entry of this.entries.values()) entry.controller.abort();
    this.entries.clear(); this.bytes = 0;
  }

  get stats(): { items: number; bytes: number } { return { items: this.entries.size, bytes: this.bytes }; }
}
