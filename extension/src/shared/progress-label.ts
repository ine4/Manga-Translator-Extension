import type { TranslationProgress } from './progress.js';

export function progressLabel(progress: TranslationProgress, elapsedSeconds: number): string {
  const percentage = Math.floor(progress.completed * 100 / progress.total);
  return `${progress.stage} · ${percentage}% (${progress.completed}/${progress.total} steps) · ${elapsedSeconds.toFixed(1)}s`;
}
