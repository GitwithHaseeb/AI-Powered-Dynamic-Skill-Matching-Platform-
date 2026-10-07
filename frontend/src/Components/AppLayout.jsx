import React, { Suspense, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';
import useReveal from '../hooks/useReveal.js';
import Header from './Header.jsx';
import ChatBot from './ChatBot.jsx';
import { CardSkeleton, Skeleton } from './ui/Skeleton.jsx';

/** Shown while a lazily loaded page chunk downloads; the header stays in place. */
const PageFallback = () => (
  <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8" aria-busy="true">
    <Skeleton className="h-9 w-72" />
    <Skeleton className="mt-3 h-4 w-96 max-w-full" />
    <div className="mt-8 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
      {[0, 1, 2, 3].map((i) => (
        <Skeleton key={i} className="h-28 rounded-2xl" />
      ))}
    </div>
    <div className="mt-8 grid grid-cols-1 lg:grid-cols-2 gap-6">
      <CardSkeleton />
      <CardSkeleton />
    </div>
  </div>
);

/** Shared chrome: header + optional chat (hidden for CEO admin). */
const AppLayout = ({ children }) => {
  const { user } = useAuth();
  const location = useLocation();
  const isCeoAdmin = user?.role === 'admin';
  useReveal();

  // Each page starts at the top (otherwise the previous page's scroll position carries over).
  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
  }, [location.pathname]);

  return (
    <>
      <Header />
      {/* Keyed by path so each page fades in on navigation. */}
      <main key={location.pathname} className="page-enter">
        <Suspense fallback={<PageFallback />}>{children}</Suspense>
      </main>
      {!isCeoAdmin && <ChatBot />}
    </>
  );
};

export default AppLayout;
