import React from 'react';

/**
 * Renders Jira-style task descriptions: paragraphs + "Key considerations" + bullets (• **Label:** text) + closing.
 */
export default function TaskDescriptionBody({ text, className = '' }) {
  const raw = String(text || '').trim();
  if (!raw) return null;

  const marker = '\n\nOverall, finishing';
  const mi = raw.lastIndexOf(marker);
  let top = raw;
  let footer = null;
  if (mi !== -1) {
    top = raw.slice(0, mi).trimEnd();
    footer = raw.slice(mi + 2).trim();
  }

  const keyBlock = '\n\nKey considerations\n\n';
  const ki = top.indexOf(keyBlock);
  if (ki === -1) {
    return (
      <div className={`space-y-2 text-sm leading-relaxed ${className}`}>
        {top.split(/\n\n+/).map((p, i) => (
          <p key={i} className="whitespace-pre-wrap text-slate-700 dark:text-slate-300">
            {p}
          </p>
        ))}
        {footer ? (
          <p className="whitespace-pre-wrap text-slate-700 dark:text-slate-300 pt-2 border-t border-slate-200/80 dark:border-slate-600/50">
            {footer}
          </p>
        ) : null}
      </div>
    );
  }

  const intro = top.slice(0, ki).trimEnd();
  const afterKey = top.slice(ki + keyBlock.length);

  return (
    <div className={`space-y-3 text-sm leading-relaxed ${className}`}>
      {intro
        ? intro.split(/\n\n+/).map((p, i) => (
            <p key={`intro-${i}`} className="text-slate-700 dark:text-slate-300">
              {p}
            </p>
          ))
        : null}

      <div>
        <p className="font-semibold text-slate-900 dark:text-slate-100 text-xs uppercase tracking-wide mb-2">
          Key considerations
        </p>
        <ul className="space-y-2.5 list-none pl-0">
          {afterKey
            .split('\n')
            .filter((line) => line.trim().startsWith('•'))
            .map((line, i) => {
              const t = line.trim();
              const m = t.match(/^•\s*\*\*(.+?)\*\*:\s*(.+)$/);
              if (m) {
                return (
                  <li key={i} className="flex gap-2.5 text-slate-700 dark:text-slate-300">
                    <span className="text-slate-400 dark:text-slate-500 shrink-0 select-none">•</span>
                    <span>
                      <strong className="font-semibold text-slate-800 dark:text-slate-200">{m[1]}:</strong> {m[2]}
                    </span>
                  </li>
                );
              }
              return (
                <li key={i} className="text-slate-700 dark:text-slate-300 pl-1">
                  {t.replace(/^•\s*/, '')}
                </li>
              );
            })}
        </ul>
      </div>

      {footer ? (
        <p className="text-slate-700 dark:text-slate-300 pt-3 border-t border-slate-200/80 dark:border-slate-600/50 whitespace-pre-wrap">
          {footer}
        </p>
      ) : null}
    </div>
  );
}
