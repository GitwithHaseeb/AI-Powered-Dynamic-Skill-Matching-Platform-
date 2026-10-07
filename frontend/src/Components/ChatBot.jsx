// src/components/ChatBot.jsx — Skill Assistant with cat mascot + dark mode
import React, { useState, useRef, useEffect } from 'react';
import { chatbotService, getApiErrorMessage } from '../services/api.js';
import CatAssistantIcon from './CatAssistantIcon.jsx';

const ChatBot = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState([
    {
      text:
        "Hello! I’m your Skill Mapping Assistant — English or Roman Urdu (informal spellings are fine). Ask about projects, teams, tasks, deadlines, or who owns a module.",
      sender: 'bot',
    },
  ]);
  const [inputMessage, setInputMessage] = useState('');
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const canonicalizeTestingOwnerQuery = (question) => {
    const q = String(question || '').trim().toLowerCase();
    if (
      q === 'who is working on testing?' ||
      q === 'who is working on testing task?' ||
      q === 'who is handling testing?' ||
      q === 'who is handling testing task?'
    ) {
      return 'Testing ka task kon kar raha hai?';
    }
    return question;
  };

  const normalizeTestingOwnerReply = (question, answer) => {
    const q = String(question || '').toLowerCase();
    const a = String(answer || '');
    const oldPattern = /Nahi,\s*Testing ke paas Testing assign nahi hai\.\s*Abhi\s+(.+?)\s+ke paas hai\.\s*Baaki:\s*(.+?)\.?$/i;
    const urduPattern = /^(.+?)\s+developer\s+is\s+py\s+working\s+kr\s+ra\.?$/i;
    const m = a.match(oldPattern);
    const mUr = a.match(urduPattern);
    const asksUrdu = q.includes('testing ka task kon kar raha') || q.includes('testing ka task kaun kar raha');
    const asksEnglish = q.includes('who is working on testing task') || q.includes('who is handling testing');
    if (asksUrdu) {
      if (m) return `${m[1]} developer is py working kr ra.`;
      return a;
    }
    if (asksEnglish) {
      if (m) return `Yes ${m[1]} developer is working on it.`;
      if (mUr) return `Yes ${mUr[1]} developer is working on it.`;
      if (a.toLowerCase().includes("project title isn’t in your live project list") || a.toLowerCase().includes("project title isn't in your live project list")) {
        return 'No testing task owner found right now.';
      }
      return a;
    }
    return a;
  };

  const sendWithText = async (raw) => {
    const text = String(raw || '').trim();
    if (!text) return;
    const apiText = canonicalizeTestingOwnerQuery(text);

    const userMessage = { text, sender: 'user' };
    const pendingId = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const pendingBot = { id: pendingId, text: 'Thinking...', sender: 'bot', pending: true };
    setMessages((prev) => [...prev, userMessage, pendingBot]);
    setInputMessage('');

    try {
      const data = await chatbotService.query(apiText);
      const replyRaw = data?.answer || 'No response.';
      const reply = normalizeTestingOwnerReply(text, replyRaw);
      setMessages((prev) =>
        prev.map((m) => (m.id === pendingId ? { ...m, text: reply, pending: false } : m))
      );
    } catch (err) {
      const friendly = getApiErrorMessage(
        err,
        'Could not reach the assistant. Check that you are logged in and the API is running.',
      );
      setMessages((prev) =>
        prev.map((m) =>
          m.id === pendingId
            ? {
                ...m,
                text: friendly,
                pending: false,
              }
            : m
        )
      );
    }
  };

  const handleSendMessage = () => sendWithText(inputMessage);

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const quickQuestions = [
    'Who is responsible for authentication?',
    'Who is handling API integration?',
    'UI design kis ke paas hai?',
    'Testing ka task kon kar raha hai?',
  ];

  return (
    <>
      {!isOpen && (
        <button
          type="button"
          className="fixed bottom-6 right-6 bg-gradient-to-r from-blue-600 to-indigo-600 text-white font-medium py-3 px-5 rounded-full shadow-lg shadow-blue-600/30 flex items-center gap-3 z-40 hover:shadow-xl hover:shadow-blue-600/40 hover:-translate-y-0.5 border border-blue-500/30 animate-scale-in"
          onClick={() => setIsOpen(true)}
          aria-label="Open Skill Assistant chat"
        >
          <div className="relative shrink-0">
            <CatAssistantIcon className="w-10 h-10 drop-shadow" />
            <span className="absolute -top-0.5 -right-0.5 w-3 h-3 bg-sky-300 rounded-full ring-2 ring-white dark:ring-gray-900 animate-pulse" />
          </div>
          <div className="text-left">
            <div className="font-semibold leading-tight">Skill Assistant</div>
            <div className="text-xs opacity-90">Tap to chat</div>
          </div>
        </button>
      )}

      {isOpen && (
        <div className="animate-scale-in origin-bottom-right fixed bottom-6 right-6 w-[min(100vw-2rem,24rem)] h-[min(100dvh-5rem,32rem)] bg-white dark:bg-gray-900 rounded-2xl shadow-2xl border border-gray-200 dark:border-gray-700 flex flex-col z-50 overflow-hidden">
          <div className="bg-gradient-to-r from-blue-600 to-blue-800 text-white p-4 flex justify-between items-center shrink-0">
            <div className="flex items-center gap-3 min-w-0">
              <div className="w-11 h-11 bg-white/15 rounded-full flex items-center justify-center shrink-0 ring-2 ring-white/25">
                <CatAssistantIcon className="w-9 h-9" />
              </div>
              <div className="min-w-0">
                <h3 className="font-semibold truncate">Skill Mapping Assistant</h3>
                <p className="text-xs opacity-90">Ask about projects, tasks &amp; skills</p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setIsOpen(false)}
              className="text-white hover:text-sky-100 text-2xl leading-none px-1 transition-colors shrink-0"
              aria-label="Close chat"
            >
              ×
            </button>
          </div>

          <div className="flex-1 p-4 overflow-y-auto space-y-3 bg-gray-50 dark:bg-gray-950/80">
            {messages.map((message, index) => (
              <div
                key={index}
                className={`flex gap-2 ${message.sender === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                {message.sender === 'bot' && (
                  <div className="w-8 h-8 shrink-0 rounded-full bg-blue-100 dark:bg-blue-900/40 flex items-center justify-center border border-blue-200/60 dark:border-blue-700/50">
                    <CatAssistantIcon className="w-6 h-6" />
                  </div>
                )}
                <div
                  className={`max-w-[85%] p-3 rounded-2xl text-sm leading-relaxed ${
                    message.sender === 'user'
                      ? 'bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-br-md shadow-sm'
                      : 'bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 rounded-bl-md border border-gray-200 dark:border-gray-600 shadow-sm'
                  }`}
                >
                  <p className="whitespace-pre-wrap break-words">{message.text}</p>
                </div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>

          <div className="p-3 border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shrink-0">
            <div className="flex flex-wrap gap-1.5 mb-2">
              {quickQuestions.map((question, index) => (
                <button
                  key={index}
                  type="button"
                  onClick={() => sendWithText(question)}
                  className="px-2.5 py-1.5 bg-blue-50 dark:bg-blue-950/50 hover:bg-blue-100 dark:hover:bg-blue-900/40 text-blue-900 dark:text-blue-100 text-xs rounded-lg transition-colors border border-blue-200/70 dark:border-blue-700/50"
                >
                  {question}
                </button>
              ))}
            </div>

            <div className="flex gap-2">
              <input
                type="text"
                value={inputMessage}
                onChange={(e) => setInputMessage(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask about projects, team, tasks…"
                className="flex-1 min-w-0 px-3 py-2.5 border border-gray-300 dark:border-gray-600 rounded-xl bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder-gray-500 dark:placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
              />
              <button
                type="button"
                onClick={handleSendMessage}
                disabled={!inputMessage.trim()}
                className="bg-blue-600 hover:bg-blue-700 dark:bg-blue-600 dark:hover:bg-blue-500 text-white font-medium py-2.5 px-4 rounded-xl transition-colors disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap text-sm"
              >
                Send
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default ChatBot;
