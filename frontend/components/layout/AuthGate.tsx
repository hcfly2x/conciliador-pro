'use client'
import { useEffect, useState } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import Sidebar from '@/components/layout/Sidebar'
import Topbar from '@/components/layout/Topbar'
import DataLoader from '@/components/layout/DataLoader'
import { getToken } from '@/lib/api'

const AUTH_DISABLED = (process.env.NEXT_PUBLIC_AUTH_DISABLED ?? 'false').toLowerCase() === 'true'

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const router = useRouter()
  const [ready, setReady] = useState(false)

  const isLogin = pathname === '/login'

  useEffect(() => {
    if (AUTH_DISABLED || isLogin) { setReady(true); return }
    if (!getToken()) {
      router.replace('/login')
      return
    }
    setReady(true)
  }, [pathname, isLogin, router])

  if (isLogin) return <>{children}</>

  if (!ready) {
    return (
      <div className="flex h-screen items-center justify-center" style={{ background: '#0d0f14' }}>
        <span className="text-sm text-[#8b90a4]">Carregando...</span>
      </div>
    )
  }

  return (
    <>
      <DataLoader />
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <div className="flex flex-col flex-1 overflow-hidden">
          <Topbar />
          <main className="flex-1 overflow-y-auto p-6" style={{ background: '#0d0f14' }}>
            {children}
          </main>
        </div>
      </div>
    </>
  )
}
