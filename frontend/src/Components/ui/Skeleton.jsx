import React from 'react';

/** Shimmering placeholder block. Pass Tailwind sizing via className (e.g. "h-4 w-1/2"). */
export const Skeleton = ({ className = '' }) => <div className={`skeleton ${className}`} aria-hidden="true" />;

/** Placeholder shaped like a project/task card while data loads. */
export const CardSkeleton = ({ lines = 2 }) => (
  <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-card" role="status" aria-label="Loading">
    <div className="flex items-center justify-between">
      <Skeleton className="h-5 w-2/5" />
      <Skeleton className="h-6 w-20 rounded-full" />
    </div>
    <div className="mt-4 space-y-2.5">
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} className={`h-3.5 ${i === lines - 1 ? 'w-3/5' : 'w-full'}`} />
      ))}
    </div>
    <Skeleton className="mt-5 h-2 w-full rounded-full" />
  </div>
);

export default Skeleton;
