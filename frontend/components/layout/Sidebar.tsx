'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useState } from 'react'
import { LayoutList, Clock, BarChart2, Tag, Upload, CreditCard, AlertTriangle, Database, FolderOpen, WalletCards } from 'lucide-react'
import { useStore } from '@/store/app'
import { getLedgers } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { Ledger } from '@/types'

const nav = [
  { href: '/',           label: 'Lançamentos', icon: LayoutList, section: 'principal' },
  { href: '/pendentes',  label: 'Pendentes',   icon: Clock,      section: 'principal', badge: 'pending' },
  { href: '/relatorios', label: 'Relatórios',  icon: BarChart2,  section: 'principal' },
  { href: '/importar',   label: 'Importar',    icon: Upload,     section: 'importacao' },
  { href: '/arquivos',   label: 'Cofre Arquivos', icon: FolderOpen, section: 'importacao' },
  { href: '/importar-historico', label: 'Importar Base', icon: AlertTriangle, section: 'importacao' },
  { href: '/base-historica', label: 'Base Historica', icon: Database, section: 'importacao' },
  { href: '/contas-correntes', label: 'Contas Correntes', icon: WalletCards, section: 'principal' },
  { href: '/categorias', label: 'Categorias',  icon: Tag,        section: 'config' },
  { href: '/contas',     label: 'Contas',      icon: CreditCard, section: 'config' },
]

export default function Sidebar() {
  const pathname = usePathname()
  const { pendingCount } = useStore()
  const [ledgers, setLedgers] = useState<Ledger[]>([])

  useEffect(() => {
    function loadLedgers() {
      getLedgers().then(setLedgers).catch(() => undefined)
    }
    loadLedgers()
    window.addEventListener('ledgers:changed', loadLedgers)
    return () => window.removeEventListener('ledgers:changed', loadLedgers)
  }, [pathname])

  function NavItem({ item }: { item: typeof nav[0] }) {
    const active = pathname === item.href
    const Icon = item.icon
    return (
      <Link
        href={item.href}
        className={cn(
          'flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-all duration-150 relative',
          active
            ? 'text-[#e8c96e] font-medium'
            : 'text-[#8b90a4] hover:text-[#e8eaf0] hover:bg-[#1a1e28]'
        )}
        style={active ? { background: 'rgba(201,168,76,0.12)' } : {}}
      >
        {active && (
          <span className="absolute left-0 top-1 bottom-1 w-[2.5px] rounded-r bg-[#c9a84c]" />
        )}
        <Icon size={15} className="flex-shrink-0" />
        <span className="flex-1">{item.label}</span>
        {item.badge === 'pending' && pendingCount > 0 && (
          <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-red-500/15 text-red-400">
            {pendingCount}
          </span>
        )}
      </Link>
    )
  }

  return (
    <aside
      className="w-[220px] flex-shrink-0 flex flex-col border-r overflow-hidden"
      style={{ background: '#13161d', borderColor: 'rgba(255,255,255,0.07)' }}
    >
      {/* Logo */}
      <div className="px-5 py-6 border-b" style={{ borderColor: 'rgba(255,255,255,0.07)' }}>
        <h1 className="font-display text-[15px] font-extrabold text-[#e8c96e] leading-none tracking-tight">
          Conciliador
        </h1>
        <p className="text-[11px] text-[#5a5f73] mt-1 font-mono-custom">financeiro pessoal</p>
      </div>

      {/* Nav */}
      <nav className="flex-1 p-3 space-y-0.5 overflow-y-auto">
        <p className="text-[10px] font-semibold text-[#5a5f73] uppercase tracking-widest px-3 pb-2 pt-1">
          Principal
        </p>
        {nav.filter(n => n.section === 'principal').map(item => (
          <NavItem key={item.href} item={item} />
        ))}
        {ledgers.length > 0 && (
          <div className="space-y-0.5 pt-1">
            {ledgers.map(ledger => {
              const href = `/contas-correntes/${ledger.id}`
              const active = pathname === href
              return (
                <Link
                  key={ledger.id}
                  href={href}
                  className={cn(
                    'flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-all duration-150 relative',
                    active ? 'text-[#e8c96e] font-medium' : 'text-[#8b90a4] hover:text-[#e8eaf0] hover:bg-[#1a1e28]'
                  )}
                  style={active ? { background: 'rgba(201,168,76,0.12)' } : {}}
                >
                  {active && <span className="absolute left-0 top-1 bottom-1 w-[2.5px] rounded-r bg-[#c9a84c]" />}
                  <span className="h-2.5 w-2.5 rounded-full flex-shrink-0" style={{ background: ledger.color || '#c9a84c' }} />
                  <span className="flex-1 truncate">{ledger.name}</span>
                  {!!ledger.pending_count && (
                    <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-yellow-500/10 text-yellow-400">
                      {ledger.pending_count}
                    </span>
                  )}
                </Link>
              )
            })}
          </div>
        )}

        <p className="text-[10px] font-semibold text-[#5a5f73] uppercase tracking-widest px-3 pb-2 pt-4">
          Importação
        </p>
        {nav.filter(n => n.section === 'importacao').map(item => (
          <NavItem key={item.href} item={item} />
        ))}

        <p className="text-[10px] font-semibold text-[#5a5f73] uppercase tracking-widest px-3 pb-2 pt-4">
          Configurações
        </p>
        {nav.filter(n => n.section === 'config').map(item => (
          <NavItem key={item.href} item={item} />
        ))}
      </nav>
    </aside>
  )
}
