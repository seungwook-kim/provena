import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import './styles.css'
import './auth-illustration.css'
import './auth-theme.css'
import './header.css'

createRoot(document.getElementById('root')).render(<StrictMode><App /></StrictMode>)
