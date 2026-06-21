import React from 'react';
import { useAuth } from '../context/AuthContext.jsx';
import Header from './Header.jsx';
import ChatBot from './ChatBot.jsx';

/** Shared chrome: header + optional chat (hidden for CEO admin). */
const AppLayout = ({ children }) => {
  const { user } = useAuth();
  const isCeoAdmin = user?.role === 'admin';

  return (
    <>
      <Header />
      {children}
      {!isCeoAdmin && <ChatBot />}
    </>
  );
};

export default AppLayout;
