'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import TransactionTable from '@/components/transactions/TransactionTable'
import { getLedgers } from '@/lib/api'
import { formatCurrencyAbs } from '@/lib/utils'
import type { Ledger } from '@/types'

export default function CheckingLedgerDetailPage() {
  const params = useParams<{ id: string }>()
  const ledgerId = params.id
  const [ledger, setLedger] = useState<Ledger | null>(null)
  const [mode, setMode] = useState<'items' | 'link'>('items')

  useEffect(() => {
    getLedgers()
      .then(items => setLedger(items.find(item => item.id === ledgerId) || null))
      .catch(() => setLedger(null))
  }, [ledgerId])

  if (!ledger) {
    return (
      <div className="space-y-3">
        <h1 className="font-display text-2xl font-bold text-[#e8eaf0]">Conta Corrente</h1>
        <p className="text-sm text-[#8b90a4]">Carregando ou conta nao encontrada.</p>
        <Link href="/contas-correntes" className="text-sm font-semibold text-[#e8c96e]">Voltar</Link>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-widest text-[#5a5f73]">Conta corrente</p>
          <h1 className="font-display text-2xl font-bold text-[#e8eaf0]">{ledger.name}</h1>
          <p className="mt-1 text-sm text-[#8b90a4]">
            Lancamentos vinculados aqui deixam de aparecer em Lancamentos e ficam separados nesta conta corrente.
          </p>
        </div>
        <div className="grid grid-cols-3 gap-2 text-right">
          <div className="rounded-lg p-3" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,0.07)' }}>
            <p className="text-[10px] uppercase tracking-widest text-[#5a5f73]">Lanc.</p>
            <p className="font-display text-lg font-bold text-[#e8eaf0]">{ledger.transaction_count || 0}</p>
          </div>
          <div className="rounded-lg p-3" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,0.07)' }}>
            <p className="text-[10px] uppercase tracking-widest text-[#5a5f73]">Pend.</p>
            <p className="font-display text-lg font-bold text-[#fbbf24]">{ledger.pending_count || 0}</p>
          </div>
          <div className="rounded-lg p-3" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,0.07)' }}>
            <p className="text-[10px] uppercase tracking-widest text-[#5a5f73]">Saldo</p>
            <p className="font-display text-lg font-bold" style={{ color: (ledger.balance || 0) >= 0 ? '#3ecf8e' : '#f87171' }}>{formatCurrencyAbs(ledger.balance || 0)}</p>
          </div>
        </div>
      </div>

      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => setMode('items')}
          className="h-9 rounded-md px-3 text-sm font-semibold"
          style={{ background: mode === 'items' ? 'rgba(201,168,76,0.18)' : '#1a1e28', color: mode === 'items' ? '#e8c96e' : '#8b90a4', border: '1px solid rgba(255,255,255,0.09)' }}
        >
          Lancamentos da conta
        </button>
        <button
          type="button"
          onClick={() => setMode('link')}
          className="h-9 rounded-md px-3 text-sm font-semibold"
          style={{ background: mode === 'link' ? 'rgba(201,168,76,0.18)' : '#1a1e28', color: mode === 'link' ? '#e8c96e' : '#8b90a4', border: '1px solid rgba(255,255,255,0.09)' }}
        >
          Vincular lancamentos
        </button>
      </div>

      {mode === 'items' ? (
        <TransactionTable defaultLedgerId={ledger.id} />
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-[#8b90a4]">
            Selecione lancamentos da aba principal e clique em <span className="font-semibold text-[#3ecf8e]">Vincular em {ledger.name}</span>.
          </p>
          <TransactionTable defaultLedgerId="none" moveTargetLedgerId={ledger.id} moveTargetLedgerName={ledger.name} />
        </div>
      )}
    </div>
  )
}
