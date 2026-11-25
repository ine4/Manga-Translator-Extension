import type { TranslateResponse } from './types.js';

export interface TranslationProgress { completed: number; total: number; stage: string }

/** Backend events contain only step counters/status until the final in-memory image. */
export async function readTranslationStream(response: Response, update: (progress: TranslationProgress) => void): Promise<TranslateResponse> {
  if (!response.body) throw new Error('Backend returned no progress stream');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = '';
  let result: TranslateResponse | undefined;
  const consume = (line: string) => {
    if (!line.trim()) return;
    const event = JSON.parse(line);
    if (event.type === 'error') throw new Error(event.error);
    if (event.type === 'result') result = event.result;
    if (event.type === 'progress' && Number.isInteger(event.completed) && Number.isInteger(event.total)
      && event.completed >= 0 && event.total > 0 && event.completed <= event.total && typeof event.stage === 'string') {
      update({ completed: event.completed, total: event.total, stage: event.stage });
    }
  };
  try {
    while (true) {
      const { value, done } = await reader.read();
      pending += decoder.decode(value, { stream: !done });
      let newline: number;
      while ((newline = pending.indexOf('\n')) >= 0) {
        consume(pending.slice(0, newline));
        pending = pending.slice(newline + 1);
      }
      if (done) break;
    }
    consume(pending);
    if (!result) throw new Error('Backend progress stream ended without a result');
    return result;
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

