'use client'
import { useEffect, useState } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { Eraser, LogOut, RefreshCw, Upload } from 'lucide-react'
import { clearTransactionClassifications, recalculateProbabilities, logout, getStoredUser } from '@/lib/api'
import type { AuthUser } from '@/types'
import { useStore } from '@/store/app'

const titles: Record<string, string> = {
  '/':           'Todos os lançamentos',
  '/pendentes':  'Pendentes de classificação',
  '/relatorios': 'Relatórios',
  '/importar':   'Importar extrato ou fatura',
  '/categorias': 'Categorias',
  '/contas':     'Contas bancárias',
}

export default function Topbar() {
  const pathname = usePathname()
  const router = useRouter()
  const { addToast, bumpRefresh } = useStore()
  const [recalcLoading, setRecalcLoading] = useState(false)
  const [clearClassLoading, setClearClassLoading] = useState(false)
  const [user, setUser] = useState<AuthUser | null>(null)
  useEffect(() => { setUser(getStoredUser()) }, [])
  const isAdminUser = user?.role === 'admin'
  const title = titles[pathname] || 'Conciliador'

  async function handleLogout() {
    await logout()
    router.replace('/login')
  }

  async function handleRecalc() {
    setRecalcLoading(true)
    try {
      const result = await recalculateProbabilities()
      addToast(`${result.updated} lançamentos com sugestão calculada`)
      bumpRefresh()
    } catch {
      addToast('Erro ao recalcular sugestões', 'err')
    } finally {
      setRecalcLoading(false)
    }
  }

  async function handleClearClassifications() {
    if (!window.confirm('Limpar todas as classificacoes e voltar lancamentos para pendente? Os lancamentos e a base historica original serao mantidos.')) return
    setClearClassLoading(true)
    try {
      const result = await clearTransactionClassifications()
      addToast(`${result.updated} classificacoes limpas`)
      bumpRefresh()
    } catch {
      addToast('Erro ao limpar classificacoes', 'err')
    } finally {
      setClearClassLoading(false)
    }
  }

  return (
    <header
      className="h-[52px] flex-shrink-0 flex items-center px-6 border-b"
      style={{ background: '#13161d', borderColor: 'rgba(255,255,255,0.07)' }}
    >
      <h2 className="flex-1 font-display font-bold text-[15px] text-[#e8eaf0]">{title}</h2>
      {isAdminUser && (<>
      <button
        onClick={handleClearClassifications}
        disabled={clearClassLoading}
        className="mr-2 flex items-center gap-2 px-3.5 py-1.5 rounded-md text-[12px] font-semibold transition-all disabled:opacity-50"
        style={{ background: 'rgba(248,113,113,0.10)', color: '#fca5a5', border: '1px solid rgba(248,113,113,0.28)' }}
        title="Remove categoria, subcategoria, observacao e vinculos"
      >
        <Eraser size={13} />
        {clearClassLoading ? 'Limpando...' : 'Limpar classificacoes'}
      </button>
      </>)}
      {isAdminUser && (<>
      <button
        onClick={handleRecalc}
        disabled={recalcLoading}
        className="mr-2 flex items-center gap-2 px-3.5 py-1.5 rounded-md text-[12px] font-semibold transition-all disabled:opacity-50"
        style={{ background: 'rgba(96,165,250,0.12)', color: '#93c5fd', border: '1px solid rgba(96,165,250,0.3)' }}
      >
        <RefreshCw size={13} />
        {recalcLoading ? 'Calculando...' : 'Recalcular sugestões'}
      </button>
      <button
        onClick={() => router.push('/importar')}
        className="flex items-center gap-2 px-3.5 py-1.5 rounded-md text-[12px] font-semibold transition-all"
        style={{ background: '#c9a84c', color: '#0d0f14' }}
        onMouseOver={e => (e.currentTarget.style.background = '#e8c96e')}
        onMouseOut={e => (e.currentTarget.style.background = '#c9a84c')}
      >
        <Upload size={13} />
        Importar extrato
      </button>
      </>)}
      {user && (
        <div className="ml-3 flex items-center gap-2">
          <span
            className="text-[11px] font-semibold px-2.5 py-1 rounded-full"
            style={{ background: 'rgba(96,165,250,0.10)', color: '#93c5fd', border: '1px solid rgba(96,165,250,0.25)' }}
            title={user.role === 'admin' ? 'Administrador' : 'Colaborador'}
          >
            {user.username} · {user.role === 'admin' ? 'admin' : 'colab'}
          </span>
          <button
            onClick={handleLogout}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-[12px] font-semibold transition-all"
            style={{ background: 'rgba(255,255,255,0.05)', color: '#8b90a4', border: '1px solid rgba(255,255,255,0.10)' }}
            title="Sair"
          >
            <LogOut size={13} />
          </button>
        </div>
      )}
    </header>
  )
}
