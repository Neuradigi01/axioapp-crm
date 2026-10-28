import { signal } from '@angular/core';
import { ICountdownTimer } from '@app/schemas/common';

export function createCountdownTimer(): ICountdownTimer {
  const remaining = signal(0);
  let intervalId: ReturnType<typeof setInterval> | null = null;

  function stop(): void {
    if (intervalId) {
      clearInterval(intervalId);
      intervalId = null;
    }
  }

  function start(seconds: number): void {
    stop();
    remaining.set(seconds);
    intervalId = setInterval(() => {
      const current = remaining();
      if (current <= 1) {
        remaining.set(0);
        stop();
      } else {
        remaining.set(current - 1);
      }
    }, 1000);
  }

  function destroy(): void {
    stop();
    remaining.set(0);
  }

  return { remaining, start, stop, destroy };
}
