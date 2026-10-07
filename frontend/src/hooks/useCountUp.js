import { useEffect, useRef, useState } from 'react';

const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

/**
 * Animate a number from its previous value to `target` (ease-out), e.g. for stat cards.
 * Non-numeric targets are returned unchanged.
 */
export default function useCountUp(target, duration = 900) {
  const end = Number(target);
  const isNumber = Number.isFinite(end);
  const [value, setValue] = useState(isNumber ? 0 : target);
  const fromRef = useRef(0);

  useEffect(() => {
    if (!isNumber) {
      setValue(target);
      return undefined;
    }
    if (prefersReducedMotion() || duration <= 0) {
      setValue(end);
      fromRef.current = end;
      return undefined;
    }
    const start = performance.now();
    const from = fromRef.current;
    let frame;
    const tick = (now) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 4);
      setValue(Math.round(from + (end - from) * eased));
      if (t < 1) frame = requestAnimationFrame(tick);
      else fromRef.current = end;
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [end, isNumber, target, duration]);

  return value;
}
