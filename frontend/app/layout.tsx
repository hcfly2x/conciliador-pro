import type { Metadata } from 'next'
import './globals.css'
import Toasts from '@/components/ui/Toasts'
import AuthGate from '@/components/layout/AuthGate'

export const metadata: Metadata = {
  title: 'Conciliador Financeiro',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>
        <AuthGate>{children}</AuthGate>
        <Toasts />
      </body>
    </html>
  )
}
