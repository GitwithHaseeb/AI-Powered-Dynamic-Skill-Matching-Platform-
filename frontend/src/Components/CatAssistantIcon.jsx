// Small tabby-style cat face for the Skill Assistant (SVG, works in light/dark UI)
import React from 'react';

export function CatAssistantIcon({ className = 'w-9 h-9' }) {
  return (
    <svg
      className={className}
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden
    >
      <ellipse cx="24" cy="28" rx="14" ry="12" fill="#3B82F6" />
      <path d="M10 18 L14 6 L22 14 Z" fill="#1D4ED8" />
      <path d="M38 18 L34 6 L26 14 Z" fill="#1D4ED8" />
      <ellipse cx="24" cy="30" rx="11" ry="9" fill="#60A5FA" />
      <circle cx="18" cy="27" r="3" fill="#1F2937" />
      <circle cx="30" cy="27" r="3" fill="#1F2937" />
      <circle cx="19" cy="26" r="1" fill="#F9FAFB" />
      <circle cx="31" cy="26" r="1" fill="#F9FAFB" />
      <path
        d="M22 31 Q24 33 26 31"
        stroke="#1F2937"
        strokeWidth="1.2"
        strokeLinecap="round"
        fill="none"
      />
      <ellipse cx="24" cy="33" rx="2" ry="1.5" fill="#2563EB" opacity="0.45" />
    </svg>
  );
}

export default CatAssistantIcon;
