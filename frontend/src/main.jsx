import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import PublicForm from './PublicForm.jsx';
import './index.css';
// /iesniegt/<kanāls> is the public web form — no login, no admin shell.
const parts = window.location.pathname.split('/').filter(Boolean);
const root = parts[0] === 'iesniegt' ? <PublicForm channel={parts[1] || 'forma'} /> : <App />;
ReactDOM.createRoot(document.getElementById('root')).render(<React.StrictMode>{root}</React.StrictMode>);
