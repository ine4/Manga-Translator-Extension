/** A direct image document legitimately displays its own URL. */
export function usableImageUrl(url: string | null | undefined, pageUrl: string, contentType: string): url is string {
  return !!url && !url.startsWith('blob:') && !url.startsWith('data:')
    && (url !== pageUrl || contentType.startsWith('image/'));
}
