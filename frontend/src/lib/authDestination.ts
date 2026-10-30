export function authDestination(next: string | null): string {
  return next?.startsWith('/') && !next.startsWith('//') ? next : '/'
}
