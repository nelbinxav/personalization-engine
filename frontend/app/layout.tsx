import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Personalization Engine',
  description: 'Research prospects and generate personalized outreach at scale.',
}

// Runs before first paint so a light-theme user never sees a dark flash.
// Dark stays the default; the toggle in the sidebar writes the override.
const THEME_SCRIPT = `try{var t=localStorage.getItem('theme');if(t==='light')document.documentElement.classList.remove('dark')}catch(e){}`

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  )
}
