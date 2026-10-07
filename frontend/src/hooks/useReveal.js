import { useEffect } from 'react';

/**
 * Fade/slide in every `[data-reveal]` element the first time it scrolls into view.
 *
 * Mount once near the root. Elements added later (route changes, data loading) are
 * picked up by a MutationObserver. `html.js-reveal` is only set while the observer is
 * running, so content is never hidden if JS or IntersectionObserver is unavailable.
 */
export default function useReveal() {
  useEffect(() => {
    if (typeof window === 'undefined' || !('IntersectionObserver' in window)) return undefined;

    const root = document.documentElement;
    root.classList.add('js-reveal');

    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible');
            io.unobserve(entry.target);
          }
        }
      },
      { rootMargin: '0px 0px -8% 0px', threshold: 0.08 }
    );

    const observeAll = () => {
      document.querySelectorAll('[data-reveal]:not(.is-visible)').forEach((el) => io.observe(el));
    };
    observeAll();

    const mo = new MutationObserver(observeAll);
    mo.observe(document.body, { childList: true, subtree: true });

    return () => {
      mo.disconnect();
      io.disconnect();
      root.classList.remove('js-reveal');
    };
  }, []);
}
