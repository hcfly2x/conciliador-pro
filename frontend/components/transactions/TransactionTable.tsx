'use client'
import { useState, useEffect, useCallback } from 'react'
import { Search, RefreshCw, ChevronUp, ChevronDown } from 'lucide-react'
import { useStore } from '@/store/app'
import { getTransactions, bulkClassify, classifyTransaction, getTransactionSuggestions, getLedgers, includeTransactionsInLedger, excludeTransactionsFromLedger, unlockTransaction, isAdmin } from '@/lib/api'
import { Lock, LockOpen } from 'lucide-react'
import { formatCurrencyAbs, formatDate } from '@/lib/utils'
import type { Ledger, Transaction, TransactionFilters, TransactionStatus } from '@/types'

const STATUS_STYLES: Record<string, { label: string; bg: string; color: string }> = {
  pending: { label: 'Pendente', bg: 'rgba(251,191,36,0.12)', color: '#fbbf24' },
  reconciled: { label: 'Manual', bg: 'rgba(62,207,142,0.12)', color: '#3ecf8e' },
  auto_classified: { label: 'Auto', bg: 'rgba(96,165,250,0.12)', color: '#60a5fa' },
  duplicate: { label: 'Duplicata', bg: 'rgba(248,113,113,0.12)', color: '#f87171' },
  ignored: { label: 'Ignorado', bg: 'rgba(90,95,115,0.15)', color: '#5a5f73' },
}

interface Props {
  defaultStatus?: string
  defaultSortBy?: string
  defaultSortOrder?: 'asc' | 'desc'
  defaultLedgerId?: string
  moveTargetLedgerId?: string
  moveTargetLedgerName?: string
}

const TAG_OPTIONS = [
  { value: 'investimento', label: 'Investimento' },
  { value: 'tax', label: 'Tax' },
  { value: 'rendimento', label: 'Rendimento' },
  { value: 'fatura', label: 'Fatura' },
  { value: 'cartao_debito', label: 'Cartao debito' },
  { value: 'non_count', label: 'Non count' },
  { value: '__empty__', label: 'Sem tag' },
]

function flagLabels(flags?: string) {
  const labels: Record<string, string> = {
    CARD_PAYMENT: 'fatura',
    card_payment: 'fatura',
    TAX: 'tax',
    INTER_ACCOUNT: 'movimentacao interna',
    inter_account: 'movimentacao interna',
    CASHBACK: 'cashback',
    cashback: 'cashback',
    non_count: 'non_count',
  }
  return (flags || '')
    .split(',')
    .map(flag => flag.trim())
    .filter(flag => flag && flag !== 'INSTALLMENT')
    .map(flag => labels[flag] || flag)
}

export default function TransactionTable({
  defaultStatus,
  defaultSortBy = 'date',
  defaultSortOrder = 'desc',
  defaultLedgerId = 'none',
  moveTargetLedgerId = '',
  moveTargetLedgerName = '',
}: Props) {
  const { months, accounts, categories, subcategories, addToast, refreshKey } = useStore()
  const [txs, setTxs] = useState<Transaction[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [summary, setSummary] = useState({ total_income: 0, total_expense: 0, balance: 0, pending_count: 0, reconciled_count: 0 })
  const [loading, setLoading] = useState(false)

  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState(defaultStatus || '')
  const [typeFilter, setTypeFilter] = useState('')
  const [monthFilter, setMonthFilter] = useState('')
  const [accountFilter, setAccountFilter] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const [subcategoryFilter, setSubcategoryFilter] = useState('')
  const [installmentFilter, setInstallmentFilter] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [tagMode, setTagMode] = useState<'include' | 'exclude'>('include')
  const [tagFilters, setTagFilters] = useState<string[]>([])
  const [sortBy, setSortBy] = useState(defaultSortBy)
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>(defaultSortOrder)
  const [pageSize, setPageSize] = useState(50)
  const [ledgers, setLedgers] = useState<Ledger[]>([])

  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkCatId, setBulkCatId] = useState('')
  const [bulkLedgerId, setBulkLedgerId] = useState('')
  const [rowDraft, setRowDraft] = useState<Record<string, { category_id: string; subcategory_id: string; notes: string }>>({})
  const [savingRow, setSavingRow] = useState<Record<string, boolean>>({})
  const [rowSuggestions, setRowSuggestions] = useState<Record<string, Array<{
    category_id: string
    category_name: string
    subcategory_id: string | null
    subcategory_name: string
    best_notes?: string
    probability: number
    category_probability: number
    subcategory_probability: number
    frequency: number
  }>>>({})

  useEffect(() => {
    const next: Record<string, { category_id: string; subcategory_id: string; notes: string }> = {}
    for (const tx of txs) {
      next[tx.id] = {
        category_id: tx.category_id || '',
        subcategory_id: tx.subcategory_id || '',
        notes: tx.notes || '',
      }
    }
    setRowDraft(next)
  }, [txs])

  async function saveRow(tx: Transaction) {
    const draft = rowDraft[tx.id]
    if (!draft?.category_id) { addToast('Selecione categoria para classificar', 'err'); return }
    setSavingRow(s => ({ ...s, [tx.id]: true }))
    try {
      await classifyTransaction(tx.id, {
        category_id: draft.category_id,
        subcategory_id: draft.subcategory_id || null,
        notes: draft.notes || '',
      })
      addToast('Lançamento classificado')
      setTxs(prev => prev.map(item => {
        if (item.id !== tx.id) return item
        const cat = categories.find(c => c.id === draft.category_id)
        const sub = subcategories.find(s => s.id === draft.subcategory_id)
        return {
          ...item,
          category_id: draft.category_id,
          category_name: cat?.name || item.category_name,
          category_color: cat?.color || item.category_color,
          subcategory_id: draft.subcategory_id || null,
          subcategory_name: sub?.name || null,
          notes: draft.notes || '',
          status: 'reconciled',
          locked: true,
        }
      }))
    } catch (err: unknown) {
      if ((err as { code?: string })?.code === 'TX_LOCKED') {
        addToast('Lancamento protegido. Use Desbloquear para alterar.', 'err')
      } else {
        addToast('Erro ao classificar', 'err')
      }
    } finally {
      setSavingRow(s => ({ ...s, [tx.id]: false }))
    }
  }

  async function autoSaveRow(tx: Transaction, next: { category_id?: string; subcategory_id?: string; notes?: string; classification_source?: 'manual' | 'auto' | 'identity' }) {
    const current = rowDraft[tx.id] || { category_id: tx.category_id || '', subcategory_id: tx.subcategory_id || '', notes: tx.notes || '' }
    const merged = {
      category_id: next.category_id ?? current.category_id,
      subcategory_id: next.subcategory_id ?? current.subcategory_id,
      notes: next.notes ?? current.notes,
    }
    setRowDraft(s => ({ ...s, [tx.id]: merged }))
    if (!merged.category_id) return
    setSavingRow(s => ({ ...s, [tx.id]: true }))
    try {
      await classifyTransaction(tx.id, {
        category_id: merged.category_id,
        subcategory_id: merged.subcategory_id || null,
        notes: merged.notes || '',
        classification_source: next.classification_source || 'manual',
      })
      setTxs(prev => prev.map(item => {
        if (item.id !== tx.id) return item
        const cat = categories.find(c => c.id === merged.category_id)
        const sub = subcategories.find(s => s.id === merged.subcategory_id)
        return {
          ...item,
          category_id: merged.category_id,
          category_name: cat?.name || item.category_name,
          category_color: cat?.color || item.category_color,
          subcategory_id: merged.subcategory_id || null,
          subcategory_name: sub?.name || null,
          notes: merged.notes || '',
          status: (next.classification_source === 'auto' ? 'auto_classified' : 'reconciled') as TransactionStatus,
          locked: true,
        }
      }))
    } catch (err: unknown) {
      if ((err as { code?: string })?.code === 'TX_LOCKED') {
        addToast('Lancamento protegido. Use Desbloquear para alterar.', 'err')
      } else {
        addToast('Erro ao salvar edição', 'err')
      }
    } finally {
      setSavingRow(s => ({ ...s, [tx.id]: false }))
    }
  }

  async function handleUnlock(tx: Transaction) {
    if (!window.confirm('Desbloquear este lancamento para edicao? A acao fica registrada na auditoria.')) return
    try {
      await unlockTransaction(tx.id, 'desbloqueio manual pela tabela')
      setTxs(prev => prev.map(item => item.id === tx.id ? { ...item, locked: false } : item))
      addToast('Lancamento desbloqueado para edicao')
    } catch (err: unknown) {
      if ((err as { status?: number })?.status === 403) {
        addToast('Apenas administrador pode desbloquear', 'err')
      } else {
        addToast('Erro ao desbloquear', 'err')
      }
    }
  }

  const load = useCallback(async (p = 1) => {
    setLoading(true)
    try {
      const filters: TransactionFilters = {
        page: p, page_size: pageSize,
        ...(search && { search }),
        ...(statusFilter && { status: statusFilter }),
        ...(typeFilter && { type: typeFilter }),
        ...(monthFilter && { competence_month: monthFilter }),
        ...(dateFrom && { date_from: dateFrom }),
        ...(dateTo && { date_to: dateTo }),
        ...(accountFilter && { account_id: accountFilter }),
        ...(categoryFilter && { category_id: categoryFilter }),
        ...(subcategoryFilter && { subcategory_id: subcategoryFilter }),
        ...(installmentFilter && { is_installment: installmentFilter }),
        ...(tagFilters.length && { tags: tagFilters.join(','), tag_mode: tagMode }),
        ledger_id: defaultLedgerId,
        sort_by: sortBy, sort_order: sortOrder,
      }
      const data = await getTransactions(filters)
      setTxs(data.items)
      setTotal(data.total)
      setTotalPages(data.total_pages)
      if (data.summary) setSummary(data.summary)
      setPage(p)
    } finally {
      setLoading(false)
    }
  }, [search, statusFilter, typeFilter, monthFilter, dateFrom, dateTo, accountFilter, categoryFilter, subcategoryFilter, installmentFilter, tagFilters, tagMode, sortBy, sortOrder, pageSize, defaultLedgerId])

  useEffect(() => { load(1) }, [search, statusFilter, typeFilter, monthFilter, dateFrom, dateTo, accountFilter, categoryFilter, subcategoryFilter, installmentFilter, tagFilters, tagMode, sortBy, sortOrder, pageSize, refreshKey, defaultLedgerId])
  useEffect(() => {
    getLedgers().then(setLedgers).catch(() => undefined)
  }, [refreshKey])
  useEffect(() => {
    const pending = txs.filter(tx => tx.status === 'pending')
    if (!pending.length) return

    const batchSize = 10
    let cancelled = false

    async function loadPendingSuggestions() {
      for (let i = 0; i < pending.length && !cancelled; i += batchSize) {
        await Promise.allSettled(
          pending.slice(i, i + batchSize).map(async tx => {
            if (rowSuggestions[tx.id] !== undefined) return
            try {
              const data = await getTransactionSuggestions(tx.id)
              if (!cancelled) setRowSuggestions(s => ({ ...s, [tx.id]: data }))
            } catch {
              if (!cancelled) setRowSuggestions(s => ({ ...s, [tx.id]: [] }))
            }
          })
        )
      }
    }

    loadPendingSuggestions()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [txs])
  useEffect(() => { setStatusFilter(defaultStatus || '') }, [defaultStatus])
  useEffect(() => {
    setSortBy(defaultSortBy)
    setSortOrder(defaultSortOrder)
  }, [defaultSortBy, defaultSortOrder])

  function toggleSort(col: string) {
    if (sortBy === col) setSortOrder(o => o === 'asc' ? 'desc' : 'asc')
    else { setSortBy(col); setSortOrder('desc') }
  }

  function SortIcon({ col }: { col: string }) {
    if (sortBy !== col) return <span className="opacity-20 text-[10px]">↕</span>
    return sortOrder === 'asc' ? <ChevronUp size={12} className="text-[#c9a84c]" /> : <ChevronDown size={12} className="text-[#c9a84c]" />
  }

  function toggleAll() {
    if (selected.size === txs.length) setSelected(new Set())
    else setSelected(new Set(txs.map(t => t.id)))
  }
  function toggleOne(id: string) {
    setSelected(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  }

  function toggleTagFilter(tag: string) {
    setTagFilters(current => current.includes(tag) ? current.filter(item => item !== tag) : [...current, tag])
  }

  async function handleBulkClassify() {
    if (!bulkCatId || !selected.size) return
    try {
      const { updated, skipped_locked } = await bulkClassify([...selected], bulkCatId)
      addToast(`${updated} lancamentos classificados${skipped_locked ? ` (${skipped_locked} protegidos ignorados)` : ''}`)
      setSelected(new Set()); setBulkCatId('')
      load(page)
    } catch { addToast('Erro na classificacao em lote', 'err') }
  }

  async function handleMoveToLedger() {
    const targetLedgerId = moveTargetLedgerId || bulkLedgerId
    if (!targetLedgerId || !selected.size) return
    try {
      const ids = [...selected]
      const result = targetLedgerId === '__none__'
        ? await excludeTransactionsFromLedger(defaultLedgerId, ids)
        : await includeTransactionsInLedger(targetLedgerId, ids)
      addToast(`${result.updated} lancamentos atualizados`)
      setSelected(new Set())
      setBulkLedgerId('')
      load(page)
      getLedgers().then(setLedgers).catch(() => undefined)
      window.dispatchEvent(new Event('ledgers:changed'))
    } catch {
      addToast('Erro ao mover para razao', 'err')
    }
  }

  const thCls = 'px-3 py-2.5 text-left text-[11px] font-semibold text-[#5a5f73] uppercase tracking-widest select-none cursor-pointer hover:text-[#8b90a4] transition-colors'

  return (
    <div>
      <div className="grid grid-cols-4 gap-3 mb-5">
        {[
          { label: 'Total', value: total.toLocaleString('pt-BR'), color: '#e8c96e' },
          { label: 'Pendentes', value: summary.pending_count, color: '#fbbf24' },
          { label: 'Saidas', value: `R$ ${Math.abs(summary.total_expense).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}`, color: '#f87171' },
          { label: 'Entradas', value: `R$ ${summary.total_income.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}`, color: '#3ecf8e' },
        ].map(s => (
          <div key={s.label} className="rounded-lg p-4" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,0.07)' }}>
            <p className="text-[11px] text-[#5a5f73] uppercase tracking-widest font-semibold mb-1.5">{s.label}</p>
            <p className="font-display font-bold text-xl leading-none" style={{ color: s.color }}>{s.value}</p>
          </div>
        ))}
      </div>

      <div className="flex gap-2 mb-4 flex-wrap items-center">
        <div className="relative">
          <Search size={12} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#5a5f73]" />
          <input className="h-8 pl-8 pr-3 rounded-md text-sm text-[#e8eaf0] placeholder-[#5a5f73] outline-none w-56" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.07)' }} placeholder="Buscar descricao..." value={search} onChange={e => setSearch(e.target.value)} />
        </div>
        <select className="h-8 px-2 rounded-md text-sm text-[#8b90a4] outline-none" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.07)' }} value={monthFilter} onChange={e => setMonthFilter(e.target.value)}>
          <option value="">Todos os meses</option>
          {months.map(m => <option key={m} value={m}>{m}</option>)}
        </select>
        <select className="h-8 px-2 rounded-md text-sm text-[#8b90a4] outline-none" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.07)' }} value={typeFilter} onChange={e => setTypeFilter(e.target.value)}>
          <option value="">Tipo</option>
          <option value="expense">Despesa</option>
          <option value="income">Receita</option>
        </select>
        <select className="h-8 px-2 rounded-md text-sm text-[#8b90a4] outline-none max-w-[190px]" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.07)' }} value={accountFilter} onChange={e => setAccountFilter(e.target.value)}>
          <option value="">Todas as contas</option>
          {accounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
        <select className="h-8 px-2 rounded-md text-sm text-[#8b90a4] outline-none max-w-[190px]" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.07)' }} value={categoryFilter} onChange={e => setCategoryFilter(e.target.value)}>
          <option value="">Todas categorias</option>
          {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select className="h-8 px-2 rounded-md text-sm text-[#8b90a4] outline-none max-w-[190px]" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.07)' }} value={subcategoryFilter} onChange={e => setSubcategoryFilter(e.target.value)}>
          <option value="">Todas subcategorias</option>
          {subcategories.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <select className="h-8 px-2 rounded-md text-sm text-[#8b90a4] outline-none" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.07)' }} value={installmentFilter} onChange={e => setInstallmentFilter(e.target.value)}>
          <option value="">Parcelamento</option>
          <option value="true">Parceladas</option>
          <option value="false">Nao parceladas</option>
        </select>
        <div className="flex items-center gap-1.5 ml-auto">
          <span className="text-[11px] text-[#5a5f73]">Linhas:</span>
          {[25, 50, 100, 200].map(n => (
            <button
              key={n}
              type="button"
              onClick={() => {
                setPageSize(n)
              }}
              className="h-7 px-2.5 rounded text-[11px] transition-all"
              style={{
                background: pageSize === n ? 'rgba(201,168,76,0.18)' : '#1a1e28',
                border: `1px solid ${pageSize === n ? 'rgba(201,168,76,0.4)' : 'rgba(255,255,255,0.07)'}`,
                color: pageSize === n ? '#e8c96e' : '#5a5f73',
                fontWeight: pageSize === n ? 600 : 400,
              }}
            >
              {n}
            </button>
          ))}
        </div>
        <button onClick={() => load(page)} className="h-8 w-8 flex items-center justify-center rounded-md text-[#5a5f73] hover:text-[#e8eaf0] transition-colors" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.07)' }}><RefreshCw size={13} /></button>
      </div>

      <div className="flex gap-2 mb-4 flex-wrap items-center">
        <label className="flex items-center gap-2 text-xs text-[#5a5f73]">
          De
          <input
            type="date"
            className="h-8 px-2 rounded-md text-sm text-[#8b90a4] outline-none"
            style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.07)' }}
            value={dateFrom}
            onChange={e => setDateFrom(e.target.value)}
          />
        </label>
        <label className="flex items-center gap-2 text-xs text-[#5a5f73]">
          Ate
          <input
            type="date"
            className="h-8 px-2 rounded-md text-sm text-[#8b90a4] outline-none"
            style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.07)' }}
            value={dateTo}
            onChange={e => setDateTo(e.target.value)}
          />
        </label>
        <select className="h-8 px-2 rounded-md text-sm text-[#8b90a4] outline-none" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.07)' }} value={tagMode} onChange={e => setTagMode(e.target.value as 'include' | 'exclude')}>
          <option value="include">Incluir tags</option>
          <option value="exclude">Excluir tags</option>
        </select>
        {TAG_OPTIONS.map(tag => {
          const active = tagFilters.includes(tag.value)
          return (
            <button
              key={tag.value}
              type="button"
              onClick={() => toggleTagFilter(tag.value)}
              className="h-8 px-2.5 rounded-md text-xs font-semibold transition-all"
              style={{
                background: active ? 'rgba(96,165,250,0.16)' : '#1a1e28',
                border: `1px solid ${active ? 'rgba(96,165,250,0.45)' : 'rgba(255,255,255,0.07)'}`,
                color: active ? '#93c5fd' : '#8b90a4',
              }}
            >
              {tag.label}
            </button>
          )
        })}
        {(dateFrom || dateTo || tagFilters.length > 0) && (
          <button
            type="button"
            onClick={() => { setDateFrom(''); setDateTo(''); setTagFilters([]); setTagMode('include') }}
            className="h-8 px-2.5 rounded-md text-xs text-[#5a5f73] hover:text-[#e8eaf0]"
            style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.07)' }}
          >
            Limpar periodo/tags
          </button>
        )}
      </div>

      {selected.size > 0 && (
        <div className="flex items-center gap-3 mb-3 px-4 py-2.5 rounded-lg" style={{ background: 'rgba(201,168,76,0.08)', border: '1px solid rgba(201,168,76,0.25)' }}>
          <span className="text-sm text-[#e8c96e] font-medium">{selected.size} selecionados</span>
          <select className="h-8 px-2 rounded-md text-sm text-[#e8eaf0] outline-none flex-1 max-w-xs" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.12)' }} value={bulkCatId} onChange={e => setBulkCatId(e.target.value)}>
            <option value="">Aplicar categoria...</option>
            {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <button onClick={handleBulkClassify} disabled={!bulkCatId} className="px-3 py-1.5 rounded-md text-xs font-semibold disabled:opacity-40" style={{ background: '#c9a84c', color: '#0d0f14' }}>Aplicar</button>
          {moveTargetLedgerId ? (
            <button onClick={handleMoveToLedger} className="px-3 py-1.5 rounded-md text-xs font-semibold" style={{ background: '#3ecf8e', color: '#08111f' }}>
              Vincular em {moveTargetLedgerName || 'conta corrente'}
            </button>
          ) : (
            <>
              <select className="h-8 px-2 rounded-md text-sm text-[#e8eaf0] outline-none flex-1 max-w-xs" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.12)' }} value={bulkLedgerId} onChange={e => setBulkLedgerId(e.target.value)}>
                <option value="">Mover para conta corrente...</option>
                {defaultLedgerId !== 'none' && <option value="__none__">Voltar para principal</option>}
                {ledgers.map(l => <option key={l.id} value={l.id}>{l.name}</option>)}
              </select>
              <button onClick={handleMoveToLedger} disabled={!bulkLedgerId} className="px-3 py-1.5 rounded-md text-xs font-semibold disabled:opacity-40" style={{ background: '#3ecf8e', color: '#08111f' }}>Mover</button>
            </>
          )}
        </div>
      )}

      <div className="rounded-xl overflow-hidden" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,0.07)' }}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr style={{ background: '#1a1e28', borderBottom: '1px solid rgba(255,255,255,0.07)' }}>
                <th className="px-3 py-2.5 w-9"><input type="checkbox" checked={selected.size === txs.length && txs.length > 0} onChange={toggleAll} className="cursor-pointer" /></th>
                <th className={thCls} onClick={() => toggleSort('date')}><span className="flex items-center gap-1">Data <SortIcon col="date" /></span></th>
                <th className={thCls} onClick={() => toggleSort('description')}><span className="flex items-center gap-1">Descricao <SortIcon col="description" /></span></th>
                <th className={`${thCls} text-right`} onClick={() => toggleSort('amount')}><span className="flex items-center justify-end gap-1">Valor <SortIcon col="amount" /></span></th>
                <th className={thCls} onClick={() => toggleSort('account')}><span className="flex items-center gap-1">Conta <SortIcon col="account" /></span></th>
                <th className={thCls} onClick={() => toggleSort('category')}><span className="flex items-center gap-1">Categoria <SortIcon col="category" /></span></th>
                <th className={thCls} onClick={() => toggleSort('subcategory')}><span className="flex items-center gap-1">Subcategoria <SortIcon col="subcategory" /></span></th>
                <th className={thCls} onClick={() => toggleSort('notes')}><span className="flex items-center gap-1">Obs <SortIcon col="notes" /></span></th>
                <th className={thCls} onClick={() => toggleSort('status')}><span className="flex items-center gap-1">Status <SortIcon col="status" /></span></th>
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan={9} className="text-center py-12 text-[#5a5f73]"><div className="inline-block w-5 h-5 border-2 border-[#22273a] border-t-[#c9a84c] rounded-full animate-spin" /></td></tr>}
              {!loading && txs.length === 0 && <tr><td colSpan={9} className="text-center py-12 text-[#5a5f73]">Nenhum lancamento encontrado</td></tr>}
              {!loading && txs.map(tx => {
                const st = STATUS_STYLES[tx.status] || STATUS_STYLES.pending
                return (
                  <tr key={tx.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }} className="hover:brightness-110 transition-all">
                    <td className="px-3 py-2.5"><input type="checkbox" checked={selected.has(tx.id)} onChange={() => toggleOne(tx.id)} className="cursor-pointer" /></td>
                    <td className="px-3 py-2.5 text-xs text-[#8b90a4] whitespace-nowrap">{formatDate(tx.date)}</td>
                    <td className="px-3 py-2.5 max-w-[260px]"><span className="block truncate text-[#e8eaf0]" title={tx.description}>{tx.description}</span></td>
                    <td className="px-3 py-2.5 text-right whitespace-nowrap"><span style={{ color: tx.type === 'income' ? '#3ecf8e' : '#f87171' }}>{tx.type === 'income' ? '+' : '-'}{formatCurrencyAbs(tx.amount)}</span></td>
                    <td className="px-3 py-2.5 text-[#8b90a4] text-xs">
                      <div>{tx.account_name}</div>
                      {flagLabels(tx.flags).length > 0 && (
                        <div className="mt-1 flex flex-wrap gap-1">
                          {flagLabels(tx.flags).map(flag => (
                            <span key={`${tx.id}-${flag}`} className="inline-flex rounded px-1.5 py-0.5 text-[10px] font-semibold" style={{ background: 'rgba(96,165,250,0.10)', color: '#93c5fd', border: '1px solid rgba(96,165,250,0.22)' }}>
                              {flag}
                            </span>
                          ))}
                        </div>
                      )}
                      {tx.is_installment && (
                        <span className="mt-1 inline-flex rounded px-1.5 py-0.5 text-[10px] font-semibold" style={{ background: 'rgba(201,168,76,0.12)', color: '#e8c96e', border: '1px solid rgba(201,168,76,0.25)' }}>
                          {tx.installment_total ? `${tx.installment_total}x` : (tx.installment_label || 'Parcelado')}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2.5">
                      {tx.status === 'pending' && !rowDraft[tx.id]?.category_id && (() => {
                        const suggestions = rowSuggestions[tx.id]
                        if (suggestions && suggestions.length > 0) {
                          return (
                            <div className="mb-1 flex flex-wrap gap-1">
                              {suggestions.slice(0, 2).map((sg, i) => (
                                <button
                                  key={`chip-cat-${tx.id}-${i}`}
                                  type="button"
                                  onClick={() => autoSaveRow(tx, {
                                    category_id: sg.category_id,
                                    subcategory_id: sg.subcategory_id || '',
                                    notes: sg.best_notes || '',
                                  })}
                                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold transition-all hover:opacity-80"
                                  style={{
                                    background: i === 0 ? 'rgba(201,168,76,0.18)' : 'rgba(255,255,255,0.06)',
                                    border: i === 0 ? '1px solid rgba(201,168,76,0.4)' : '1px solid rgba(255,255,255,0.1)',
                                    color: i === 0 ? '#e8c96e' : '#8b90a4',
                                    cursor: 'pointer',
                                  }}
                                  title={`Aplicar: ${sg.category_name} (${(sg.category_probability ?? sg.probability ?? 0).toFixed(0)}%)`}
                                >
                                  {sg.category_name}
                                  <span style={{ opacity: 0.65 }}>{(sg.category_probability ?? sg.probability ?? 0).toFixed(0)}%</span>
                                </button>
                              ))}
                            </div>
                          )
                        }
                        if (tx.match_category_name && !suggestions) {
                          return (
                            <div className="mb-1">
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold" style={{ background: 'rgba(201,168,76,0.08)', color: '#c9a84c', border: '1px solid rgba(201,168,76,0.15)' }}>
                                {tx.match_category_name}
                                {Number(tx.match_probability) > 0 && <span style={{ opacity: 0.5 }}>{Number(tx.match_probability).toFixed(0)}%</span>}
                              </span>
                            </div>
                          )
                        }
                        return null
                      })()}
                      <select
                        className="h-8 w-[190px] rounded-md px-2 text-xs text-[#e8eaf0] outline-none disabled:opacity-45 disabled:cursor-not-allowed"
                        style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.12)' }}
                        value={rowDraft[tx.id]?.category_id || ''}
                        disabled={!!tx.locked}
                        onChange={async (e) => {
                          const val = e.target.value
                          await autoSaveRow(tx, { category_id: val })
                        }}
                      >
                        <option value="">Selecionar...</option>
                        {(rowSuggestions[tx.id] || []).length > 0 && <option value="" disabled>-- Sugeridas --</option>}
                        {(rowSuggestions[tx.id] || []).map((sg, i) => (
                          <option key={`sg-cat-${tx.id}-${i}-${sg.category_id}`} value={sg.category_id}>
                            {sg.category_name} ({(sg.category_probability ?? sg.probability).toFixed(0)}%)
                          </option>
                        ))}
                        {(rowSuggestions[tx.id] || []).length > 0 && <option value="" disabled>-- Todas --</option>}
                        {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                      </select>
                    </td>
                    <td className="px-3 py-2.5">
                      {tx.status === 'pending' && !rowDraft[tx.id]?.subcategory_id && (() => {
                        const subSuggestions = (rowSuggestions[tx.id] || [])
                          .filter(sg => !!sg.subcategory_id && !!sg.subcategory_name)
                          .filter((sg, i, arr) => arr.findIndex(x => x.subcategory_id === sg.subcategory_id) === i)
                          .slice(0, 2)
                        if (!subSuggestions.length) return null
                        return (
                          <div className="mb-1 flex flex-wrap gap-1">
                            {subSuggestions.map((sg, i) => (
                              <button
                                key={`chip-sub-${tx.id}-${i}`}
                                type="button"
                                onClick={() => autoSaveRow(tx, { subcategory_id: sg.subcategory_id || '' })}
                                className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold transition-all hover:opacity-80"
                                style={{
                                  background: 'rgba(96,165,250,0.10)',
                                  border: '1px solid rgba(96,165,250,0.22)',
                                  color: '#93c5fd',
                                  cursor: 'pointer',
                                }}
                              >
                                {sg.subcategory_name}
                              </button>
                            ))}
                          </div>
                        )
                      })()}
                      <select
                        className="h-8 w-[170px] rounded-md px-2 text-xs text-[#e8eaf0] outline-none disabled:opacity-45 disabled:cursor-not-allowed"
                        style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.12)' }}
                        value={rowDraft[tx.id]?.subcategory_id || ''}
                        disabled={!!tx.locked}
                        onChange={async (e) => {
                          const val = e.target.value
                          await autoSaveRow(tx, { subcategory_id: val })
                        }}
                      >
                        <option value="">Sem subcategoria</option>
                        {(rowSuggestions[tx.id] || [])
                          .filter(sg => !!sg.subcategory_id)
                          .map((sg, i) => (
                            <option key={`sg-sub-${tx.id}-${i}-${sg.subcategory_id}`} value={sg.subcategory_id || ''}>
                              {sg.subcategory_name} ({(sg.subcategory_probability ?? sg.probability).toFixed(1)}%)
                            </option>
                          ))}
                        {subcategories.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                      </select>
                    </td>
                    <td className="px-3 py-2.5">
                      <input
                        className="h-8 w-[180px] rounded-md px-2 text-xs text-[#e8eaf0] outline-none disabled:opacity-45 disabled:cursor-not-allowed"
                        style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.12)' }}
                        value={rowDraft[tx.id]?.notes || ''}
                        disabled={!!tx.locked}
                        onChange={(e) => {
                          const val = e.target.value
                          setRowDraft(s => ({ ...s, [tx.id]: { ...(s[tx.id] || { category_id: '', subcategory_id: '', notes: '' }), notes: val } }))
                        }}
                        onKeyDown={async (e) => {
                          if (e.key === 'Enter') {
                            await autoSaveRow(tx, { notes: rowDraft[tx.id]?.notes || '' })
                          }
                        }}
                        onBlur={async () => {
                          await autoSaveRow(tx, { notes: rowDraft[tx.id]?.notes || '' })
                        }}
                        placeholder="Observacao..."
                      />
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-1.5">
                        <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full" style={{ background: st.bg, color: st.color }}>{st.label}</span>
                        {tx.locked && (
                          <span
                            className="inline-flex items-center"
                            title={'Protegido' + (tx.classified_by ? ' - classificado por ' + tx.classified_by : '') + (tx.classified_at ? ' em ' + tx.classified_at.slice(0, 10) : '')}
                          >
                            <Lock size={12} color="#c9a84c" />
                          </span>
                        )}
                        {tx.locked && isAdmin() && (
                          <button
                            type="button"
                            onClick={() => handleUnlock(tx)}
                            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold transition-all hover:opacity-80"
                            style={{ background: 'rgba(201,168,76,0.10)', border: '1px solid rgba(201,168,76,0.30)', color: '#c9a84c', cursor: 'pointer' }}
                            title="Desbloquear para editar (registra auditoria)"
                          >
                            <LockOpen size={11} />
                            Desbloquear
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        {totalPages > 1 && (
          <div
            className="flex items-center justify-between px-4 py-3"
            style={{ borderTop: '1px solid rgba(255,255,255,0.06)', background: '#13161d' }}
          >
            <span className="text-[11px] text-[#5a5f73] font-mono">
              Pagina {page} de {totalPages} - {total.toLocaleString('pt-BR')} lancamentos
            </span>
            <div className="flex items-center gap-1">
              <button
                disabled={page <= 1}
                onClick={() => load(1)}
                className="h-7 w-7 rounded text-[11px] disabled:opacity-30 transition-all"
                style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.07)', color: '#8b90a4' }}
                title="Primeira pagina"
              >
                {'<<'}
              </button>
              <button
                disabled={page <= 1}
                onClick={() => load(page - 1)}
                className="h-7 px-2.5 rounded text-[11px] disabled:opacity-30 transition-all"
                style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.07)', color: '#8b90a4' }}
              >
                Ant
              </button>
              {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                const start = Math.max(1, Math.min(page - 2, totalPages - 4))
                return start + i
              }).map(n => (
                <button
                  key={n}
                  onClick={() => load(n)}
                  className="h-7 w-7 rounded text-[11px] transition-all"
                  style={{
                    background: n === page ? 'rgba(201,168,76,0.18)' : '#1a1e28',
                    border: `1px solid ${n === page ? 'rgba(201,168,76,0.4)' : 'rgba(255,255,255,0.07)'}`,
                    color: n === page ? '#e8c96e' : '#8b90a4',
                    fontWeight: n === page ? 600 : 400,
                  }}
                >
                  {n}
                </button>
              ))}
              <button
                disabled={page >= totalPages}
                onClick={() => load(page + 1)}
                className="h-7 px-2.5 rounded text-[11px] disabled:opacity-30 transition-all"
                style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.07)', color: '#8b90a4' }}
              >
                Prox
              </button>
              <button
                disabled={page >= totalPages}
                onClick={() => load(totalPages)}
                className="h-7 w-7 rounded text-[11px] disabled:opacity-30 transition-all"
                style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.07)', color: '#8b90a4' }}
                title="Ultima pagina"
              >
                {'>>'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
