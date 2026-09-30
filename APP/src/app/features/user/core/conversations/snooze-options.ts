/** One "Snooze until…" choice. `until` is null for "until the customer
 *  replies" (no timed wake-up). */
export interface SnoozePreset {
  label: string;
  /** Short hint shown next to the label ("Tue 9:00"). */
  hint: string;
  until: Date | null;
}

const WAKE_HOUR = 9;

/** Standard inbox snooze presets, computed in the operator's local time. */
export function snoozePresets(now: Date = new Date()): SnoozePreset[] {
  const inOneHour = new Date(now.getTime() + 60 * 60 * 1000);

  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);
  tomorrow.setHours(WAKE_HOUR, 0, 0, 0);

  const nextMonday = new Date(now);
  const daysUntilMonday = (8 - now.getDay()) % 7 || 7;
  nextMonday.setDate(now.getDate() + daysUntilMonday);
  nextMonday.setHours(WAKE_HOUR, 0, 0, 0);

  return [
    { label: '1 hour', hint: formatHint(inOneHour), until: inOneHour },
    { label: 'Tomorrow', hint: formatHint(tomorrow), until: tomorrow },
    { label: 'Next week', hint: formatHint(nextMonday), until: nextMonday },
    { label: 'Until customer replies', hint: '', until: null },
  ];
}

/** "Tue 9:00" style label for a wake-up time. */
export function formatHint(d: Date): string {
  return d.toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' });
}
