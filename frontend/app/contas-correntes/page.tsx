'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { createLedger, deleteLedger, getLedgers } from '@/lib/api'
import { formatCurrencyAbs } from '@/lib/utils'
import type { Ledger } from '@/types'

export default function CheckingLedgersPage() {
  const [ledgers, setLedgers] = useState<Ledger[]>([])
  const [name, setName] = useState('')
  const [loading, setLoading] = useState(false)

  async function load() {
    setLedgers(await getLedgers())
  }

  useEffect(() => {
    load().catch(() => undefined)
  }, [])

  async function handleCreate() {
    const trimmed = name.trim()
    if (!trimmed) return
    setLoading(true)
    try {
      await createLedger({ name: trimmed })
      setName('')
      await load()
      window.dispatchEvent(new Event('ledgers:changed'))
    } finally {
      setLoading(false)
    }
  }

  async function handleDelete(id: string) {
    if (!confirm('Desativar esta conta corrente e devolver seus lancamentos para Lancamentos?')) return
    await deleteLedger(id)
    await load()
    window.dispatchEvent(new Event('ledgers:changed'))
  }

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-bold text-[#e8eaf0]">Contas Correntes</h1>
          <p className="mt-1 text-sm text-[#8b90a4]">
            Contas internas para separar lancamentos da visao principal sem criar conta bancaria e sem duplicar registros.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            className="h-9 w-64 rounded-md px-3 text-sm text-[#e8eaf0] outline-none"
            style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.12)' }}
            placeholder="Nome da conta corrente..."
            value={name}
            onChange={e => setName(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') handleCreate() }}
          />
          <button
            type="button"
            disabled={loading || !name.trim()}
            onClick={handleCreate}
            className="inline-flex h-9 items-center gap-2 rounded-md px-3 text-sm font-semibold disabled:opacity-40"
            style={{ background: '#c9a84c', color: '#0d0f14' }}
          >
            <Plus size={15} />
            Criar
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        {ledgers.map(item => (
          <div
            key={item.id}
            className="rounded-lg p-4"
            style={{ background: '#13161d', border: '1px solid rgba(255,255,255,0.07)' }}
          >
            <Link href={`/contas-correntes/${item.id}`} className="block">
              <p className="text-[11px] font-semibold uppercase tracking-widest text-[#5a5f73]">Conta corrente</p>
              <p className="mt-1 font-display text-lg font-bold text-[#e8eaf0]">{item.name}</p>
              <p className="mt-2 text-xs text-[#8b90a4]">
                {item.transaction_count || 0} lanc. · pendentes {item.pending_count || 0}
              </p>
              <p className="mt-1 text-xs" style={{ color: (item.balance || 0) >= 0 ? '#3ecf8e' : '#f87171' }}>
                Saldo {formatCurrencyAbs(item.balance || 0)}
              </p>
            </Link>
            <button
              type="button"
              onClick={() => handleDelete(item.id)}
              className="mt-3 inline-flex h-7 items-center gap-1 rounded px-2 text-xs font-semibold text-[#fca5a5]"
              style={{ background: 'rgba(248,113,113,0.10)', border: '1px solid rgba(248,113,113,0.18)' }}
            >
              <Trash2 size={12} />
              Desativar
            </button>
          </div>
        ))}
        {ledgers.length === 0 && (
          <div className="rounded-lg p-6 text-sm text-[#8b90a4]" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,0.07)' }}>
            Crie a primeira conta corrente para ela aparecer no menu lateral.
          </div>
        )}
      </div>
    </div>
  )
}
