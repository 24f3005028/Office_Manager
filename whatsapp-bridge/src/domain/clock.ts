export interface Clock {
  now(): number;
  setTimeout(callback: () => void, ms: number): unknown;
  clearTimeout(timer: unknown): void;
}

export const systemClock: Clock = {
  now: () => Date.now(),
  setTimeout: (callback, ms) => setTimeout(callback, ms),
  clearTimeout: (timer) => clearTimeout(timer as ReturnType<typeof setTimeout>),
};

export function bounded<T>(promise: Promise<T>, ms: number, clock: Clock): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = clock.setTimeout(() => reject(new Error("Deadline exceeded")), ms);
    promise.then(resolve, reject).finally(() => clock.clearTimeout(timer)).catch(() => undefined);
  });
}
