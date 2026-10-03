/** Small local helper for "2 hours ago"-style relative timestamps -- no new
 * npm dependency for this. Input is a Unix timestamp in seconds (as returned
 * by the backend's job store, see backend/app/jobs/models.py). */
export function formatRelativeTime(unixSeconds: number, now: number = Date.now()): string {
  const diffMs = now - unixSeconds * 1000;
  const diffSec = Math.round(diffMs / 1000);

  if (diffSec < 5) return "just now";

  const units: Array<[string, number]> = [
    ["year", 31536000],
    ["month", 2592000],
    ["week", 604800],
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
    ["second", 1],
  ];

  for (const [label, secondsInUnit] of units) {
    const value = Math.floor(diffSec / secondsInUnit);
    if (value >= 1) {
      return `${value} ${label}${value === 1 ? "" : "s"} ago`;
    }
  }

  return "just now";
}
