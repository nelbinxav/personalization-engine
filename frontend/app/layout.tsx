import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Personalization Engine',
  description: 'Research prospects and generate personalized outreach at scale.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  )
}
