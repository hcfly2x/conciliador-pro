'use client'

import { useCallback, useEffect, useState } from 'react'
import { ArrowRightLeft, CheckCircle2, Loader2, RefreshCw, Search, Undo2 } from 'lucide-react'
import {
  createReconciliation,
  getReconciliations,
  undoReconciliation,
  type ReconciliationCandidate,
  type ReconciliationRecord,
  type ReconciliationTransaction,
} from '@/lib/api'
import { useStore } from '@/store/app'
import { formatCurrencyAbs, formatDate } from '@/lib/utils'

type View = 'candidates' | 'completed'

function TransactionSide({ transaction, tone }: { transaction: ReconciliationTransaction; tone: 'expense' | 'income' }) {
  const color = tone === 'expense' ? '#f87171' : '#3ecf8e'
  return (
    <div className="min-w-0 flex-1 rounded-lg p-3" style={{ background: `${color}0d`, border: `1px solid ${color}2e` }}>
      <p className="text-[10px] font-semibold uppercase tracking-wider" style={{ color }}>{tone === 'expense' ? 'Saida' : 'Entrada'}</p>
      <p className="mt-2 truncate text-sm font-semibold text-[#e8eaf0]" title={transaction.description}>{transaction.description}</p>
      <p className="mt-1 text-xs text-[#8b90a4]">{transaction.account_name}</p>
      <div className="mt-3 flex items-center justify-between gap-2">
        <span className="text-xs text-[#8b90a4]">{formatDate(transaction.date)}</span>
        <strong className="text-sm" style={{ color }}>{tone === 'expense' ? '-' : '+'}{formatCurrencyAbs(transaction.amount)}</strong>
      </div>
    </div>
  )
}

export default function ReconciliationCenter() {
  const { addToast, bumpRefresh } = useStore()
  const [view, setView] = useState<View>('candidates')
  const [search, setSearch] = useState('')
  const [items, setItems] = useState<Array<ReconciliationCandidate | ReconciliationRecord>>([])
  const [loading, setLoading] = useState(false)
  const [busyId, setBusyId] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const response = await getReconciliations(view, search)
      setItems(response.items)
    } catch {
      addToast('Nao foi possivel carregar as conciliacoes', 'err')
    } finally {
      setLoading(false)
    }
  }, [addToast, search, view])

  useEffect(() => { load() }, [load])

  async function reconcile(item: ReconciliationCandidate) {
    const key = `${item.expense.id}:${item.income.id}`
    if (!window.confirm(`Conciliar a saida e a entrada de ${formatCurrencyAbs(item.amount)}? Elas deixarao de compor os totais e relatorios.`)) return
    setBusyId(key)
    try {
      await createReconciliation(item.expense.id, item.income.id)
      setItems(current => current.filter(candidate => {
        const pair = candidate as ReconciliationCandidate
        return ![pair.expense.id, pair.income.id].some(id => id === item.expense.id || id === item.income.id)
      }))
      addToast('Entrada e saida conciliadas; valores removidos dos totais')
      bumpRefresh()
    } catch (error: unknown) {
      addToast((error as { detail?: string })?.detail || 'Nao foi possivel conciliar', 'err')
      load()
    } finally {
      setBusyId('')
    }
  }

  async function undo(item: ReconciliationRecord) {
    if (!window.confirm('Desfazer esta conciliacao? Os dois valores voltarao aos totais e relatorios.')) return
    setBusyId(item.id)
    try {
      await undoReconciliation(item.id)
      setItems(current => current.filter(candidate => (candidate as ReconciliationRecord).id !== item.id))
      addToast('Conciliacao desfeita')
      bumpRefresh()
    } catch {
      addToast('Nao foi possivel desfazer a conciliacao', 'err')
    } finally {
      setBusyId('')
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-bold text-[#e8eaf0]">Conciliacao de transferencias</h1>
          <p className="mt-1 max-w-2xl text-sm text-[#8b90a4]">Vincule uma saida a uma entrada do mesmo valor. Os lancamentos continuam guardados, mas deixam de afetar saldos e relatorios.</p>
        </div>
        <button onClick={load} disabled={loading} className="flex h-10 items-center gap-2 rounded-lg px-4 text-sm font-semibold text-[#8b90a4] disabled:opacity-50" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,.09)' }}><RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Atualizar</button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button onClick={() => setView('candidates')} className="rounded-lg px-4 py-2 text-sm font-semibold" style={{ background: view === 'candidates' ? 'rgba(201,168,76,.17)' : '#1a1e28', color: view === 'candidates' ? '#e8c96e' : '#8b90a4', border: `1px solid ${view === 'candidates' ? 'rgba(201,168,76,.4)' : 'rgba(255,255,255,.07)'}` }}>Para conciliar</button>
        <button onClick={() => setView('completed')} className="rounded-lg px-4 py-2 text-sm font-semibold" style={{ background: view === 'completed' ? 'rgba(62,207,142,.12)' : '#1a1e28', color: view === 'completed' ? '#6ee7b7' : '#8b90a4', border: `1px solid ${view === 'completed' ? 'rgba(62,207,142,.3)' : 'rgba(255,255,255,.07)'}` }}>Ja conciliados</button>
        <div className="relative ml-auto w-full sm:w-72"><Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#5a5f73]" /><input value={search} onChange={event => setSearch(event.target.value)} placeholder="Buscar descricao ou conta..." className="h-10 w-full rounded-lg pl-9 pr-3 text-sm text-[#e8eaf0] outline-none" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,.09)' }} /></div>
      </div>

      {view === 'candidates' && <div className="rounded-lg border border-blue-400/15 bg-blue-400/[.05] px-4 py-3 text-xs text-blue-200">Mostramos somente pares com uma entrada e uma saida de valor exatamente igual. A ordem prioriza as datas mais proximas; nada e vinculado automaticamente.</div>}

      {loading ? <div className="py-20 text-center"><Loader2 className="mx-auto animate-spin text-[#c9a84c]" /></div> : items.length === 0 ? (
        <div className="rounded-xl py-20 text-center text-sm text-[#8b90a4]" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,.07)' }}>{view === 'candidates' ? 'Nenhum par de mesmo valor disponivel para conciliar.' : 'Nenhuma conciliacao registrada.'}</div>
      ) : <div className="space-y-3">{items.map((raw, index) => {
        const item = raw as ReconciliationCandidate & Partial<ReconciliationRecord>
        const key = item.id || `${item.expense.id}:${item.income.id}`
        return <article key={key} className="rounded-xl p-4" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,.07)' }}>
          <div className="flex flex-col items-stretch gap-3 md:flex-row md:items-center">
            <TransactionSide transaction={item.expense} tone="expense" />
            <div className="flex shrink-0 flex-col items-center gap-1 text-[#8b90a4]"><ArrowRightLeft size={18} /><span className="text-[10px]">{view === 'completed' ? 'vinculado' : `${item.date_difference_days} dia(s)`}</span></div>
            <TransactionSide transaction={item.income} tone="income" />
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {view === 'completed' ? <><span className="flex items-center gap-1 text-xs text-emerald-300"><CheckCircle2 size={14} /> Conciliado por {item.created_by || 'usuario'} em {formatDate((item.created_at || '').slice(0, 10))}</span><button onClick={() => undo(item as ReconciliationRecord)} disabled={busyId === item.id} className="ml-auto flex items-center gap-2 rounded-md bg-red-500/10 px-3 py-2 text-sm font-semibold text-red-300 disabled:opacity-50"><Undo2 size={14} /> Desfazer</button></> : <><span className="text-xs text-[#8b90a4]">Diferenca entre as datas: {item.date_difference_days} dia(s)</span><button onClick={() => reconcile(item)} disabled={busyId === key} className="ml-auto flex items-center gap-2 rounded-md bg-emerald-500/15 px-4 py-2 text-sm font-semibold text-emerald-300 disabled:opacity-50">{busyId === key ? <Loader2 size={14} className="animate-spin" /> : <ArrowRightLeft size={14} />} Conciliar este par</button></>}
          </div>
        </article>
      })}</div>}
    </div>
  )
}
