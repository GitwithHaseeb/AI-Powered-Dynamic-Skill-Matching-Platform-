import React from 'react';
import logoIcon from '../../assets/skill-mapping-logo.svg';

const FEATURES = [
  ['AI team recommendations', 'Match developers to projects by real skills, availability and workload.'],
  ['SRS to tasks in seconds', 'Upload a requirements document and get skills and tasks extracted.'],
  ['Bilingual assistant', 'Ask about projects and teams in English or Roman Urdu.'],
];

/** Dark, animated brand panel shown beside the login / signup forms. */
const AuthHero = ({ title, subtitle }) => (
  <div className="relative w-full lg:w-1/2 overflow-hidden bg-slate-950 p-8 lg:p-12 flex flex-col justify-center text-white">
    {/* Soft moving colour blobs */}
    <div aria-hidden="true" className="pointer-events-none absolute inset-0">
      <div className="absolute -top-24 -left-20 h-80 w-80 rounded-full bg-blue-600/40 blur-3xl animate-float" />
      <div className="absolute top-1/3 -right-24 h-96 w-96 rounded-full bg-violet-600/35 blur-3xl animate-float-slow" />
      <div className="absolute -bottom-28 left-1/4 h-72 w-72 rounded-full bg-sky-500/25 blur-3xl animate-float" style={{ animationDelay: '-4s' }} />
      <div
        className="absolute inset-0 opacity-[0.07]"
        style={{
          backgroundImage:
            'linear-gradient(to right, #fff 1px, transparent 1px), linear-gradient(to bottom, #fff 1px, transparent 1px)',
          backgroundSize: '44px 44px',
          maskImage: 'radial-gradient(ellipse at center, black 30%, transparent 75%)',
          WebkitMaskImage: 'radial-gradient(ellipse at center, black 30%, transparent 75%)',
        }}
      />
    </div>

    <div className="relative max-w-md mx-auto lg:mx-0 stagger">
      <img
        src={logoIcon}
        alt="Skill Mapping logo"
        className="h-16 w-16 rounded-2xl ring-1 ring-white/15 shadow-2xl shadow-blue-900/50"
      />
      <p className="mt-8 text-xs font-semibold uppercase tracking-[0.25em] text-blue-200/80">Skill Mapping</p>
      <h2 className="mt-3 text-3xl lg:text-4xl font-bold leading-tight">{title}</h2>
      {subtitle && <p className="mt-3 text-slate-300 leading-relaxed">{subtitle}</p>}

      <ul className="mt-10 space-y-5">
        {FEATURES.map(([name, text]) => (
          <li key={name} className="flex gap-3.5">
            <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-white/10 ring-1 ring-white/15">
              <svg className="h-4 w-4 text-sky-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M5 13l4 4L19 7" />
              </svg>
            </span>
            <span>
              <span className="block font-semibold">{name}</span>
              <span className="block text-sm text-slate-400">{text}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  </div>
);

export default AuthHero;
