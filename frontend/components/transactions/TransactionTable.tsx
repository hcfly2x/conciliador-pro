'use client'
import { useState, useEffect, useCallback } from 'react'
import { Search, RefreshCw, ChevronUp, ChevronDown, Link2, X } from 'lucide-react'
import { useStore } from '@/store/app'
import { getTransactions, bulkClassify, classifyTransaction, getTransactionSuggestionsBatch, getLedgers, includeTransactionsInLedger, excludeTransactionsFromLedger, unlockTransaction, isAdmin, reviewHistoricalMatch, prepareHistoricalLinks, type TransactionSuggestion } from '@/lib/api'
import { Lock, LockOpen } from 'lucide-react'
import { formatCurrencyAbs, formatDate } from '@/lib/utils'
import type { Ledger, Transaction, TransactionFilters } from '@/types'

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
  defaultReconciliationStatus?: 'matched' | 'unmatched'
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

function hasPendingDirectHistoryLink(tx: Transaction) {
  return Boolean(
    tx.history_match_id
    && !tx.history_match_confirmed
    && Number(tx.identity_score || 0) >= Number(tx.history_link_threshold || 96)
  )
}

export default function TransactionTable({
  defaultStatus,
  defaultSortBy = 'date',
  defaultSortOrder = 'desc',
  defaultLedgerId = 'none',
  moveTargetLedgerId = '',
  moveTargetLedgerName = '',
  defaultReconciliationStatus,
}: Props) {
  const { months, accounts, categories, subcategories, addToast, refreshKey } = useStore()
  const [txs, setTxs] = useState<Transaction[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [summary, setSummary] = useState({ total_income: 0, total_expense: 0, balance: 0, pending_count: 0, reconciled_count: 0 })
  const [loading, setLoading] = useState(false)
  const [linkReviewId, setLinkReviewId] = useState<string | null>(null)
  const [reviewingLink, setReviewingLink] = useState(false)

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
  const [bulkSubId, setBulkSubId] = useState('')
  const [bulkLedgerId, setBulkLedgerId] = useState('')
  const [linkingBatch, setLinkingBatch] = useState(false)
  const [linkBatchLogs, setLinkBatchLogs] = useState<Array<{ time: string; message: string }>>([])
  const [rowDraft, setRowDraft] = useState<Record<string, { category_id: string; subcategory_id: string; notes: string }>>({})
  const [savingRow, setSavingRow] = useState<Record<string, boolean>>({})
  const [rowSuggestions, setRowSuggestions] = useState<Record<string, TransactionSuggestion[]>>({})
  const [rowSuggestionStates, setRowSuggestionStates] = useState<Record<string, string>>({})
  const [suggestionsLoading, setSuggestionsLoading] = useState<Set<string>>(new Set())
  const [suggestionErrors, setSuggestionErrors] = useState<Set<string>>(new Set())

  useEffect(() => {
    setRowDraft(current => {
      const next: Record<string, { category_id: string; subcategory_id: string; notes: string }> = {}
      for (const tx of txs) {
        next[tx.id] = current[tx.id] || {
          category_id: tx.category_id || '',
          subcategory_id: tx.subcategory_id || '',
          notes: tx.notes || '',
        }
      }
      return next
    })
  }, [txs])

  async function saveRow(tx: Transaction) {
    const draft = rowDraft[tx.id]
    if (!draft?.category_id) { addToast('Selecione categoria para classificar', 'err'); return }
    setSavingRow(s => ({ ...s, [tx.id]: true }))
    try {
      const result = await classifyTransaction(tx.id, {
        category_id: draft.category_id,
        subcategory_id: draft.subcategory_id || null,
        notes: draft.notes || '',
        apply_to_installments: true,
      })
      const affected = new Set(result.affected_ids || [tx.id])
      addToast(result.affected_count && result.affected_count > 1
        ? `${result.affected_count} parcelas classificadas no plano`
        : 'Lançamento classificado')
      setTxs(prev => prev.map(item => {
        if (!affected.has(item.id)) return item
        const cat = categories.find(c => c.id === draft.category_id)
        const sub = subcategories.find(s => s.id === draft.subcategory_id)
        return {
          ...item,
          category_id: draft.category_id,
          category_name: cat?.name || item.category_name,
          category_color: cat?.color || item.category_color,
          subcategory_id: draft.subcategory_id || null,
          subcategory_name: sub?.name || null,
          notes: item.id === tx.id ? (draft.notes || '') : item.notes,
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

  function patchRowDraft(tx: Transaction, next: Partial<{ category_id: string; subcategory_id: string; notes: string }>) {
    setRowDraft(current => {
      const base = current[tx.id] || {
        category_id: tx.category_id || '',
        subcategory_id: tx.subcategory_id || '',
        notes: tx.notes || '',
      }
      return { ...current, [tx.id]: { ...base, ...next } }
    })
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

  async function handleHistoryLink(tx: Transaction, action: 'confirm' | 'reject') {
    setReviewingLink(true)
    try {
      const result = await reviewHistoricalMatch(tx.id, action)
      const affected = new Set(result.affected_ids || [tx.id])
      setTxs(prev => prev.map(item => {
        if (!affected.has(item.id)) return item
        const isConfirmedLink = action === 'confirm' && item.id === tx.id
        return {
          ...item,
          history_match_id: isConfirmedLink ? item.history_match_id : null,
          history_match_confirmed: isConfirmedLink,
          identity_score: isConfirmedLink ? item.identity_score : 0,
          match_probability: isConfirmedLink ? item.match_probability : 0,
          ...(action === 'confirm' ? {
          category_id: result.category_id || null,
          category_name: categories.find(category => category.id === result.category_id)?.name || item.match_history_category_name || null,
          subcategory_id: result.subcategory_id || null,
          subcategory_name: subcategories.find(subcategory => subcategory.id === result.subcategory_id)?.name || item.match_history_subcategory_name || null,
          status: result.status || 'reconciled',
          locked: result.locked ?? true,
          classified_by: result.classified_by || '',
          classified_at: result.classified_at || '',
          } : {}),
        }
      }))
      setLinkReviewId(null)
      setRowSuggestions(current => {
        const next = { ...current }
        affected.forEach(id => delete next[id])
        return next
      })
      setRowSuggestionStates(current => {
        const next = { ...current }
        affected.forEach(id => delete next[id])
        return next
      })
      addToast(action === 'confirm' ? 'Vinculo confirmado e classificacao historica aplicada' : 'Sugestao de vinculo rejeitada')
    } catch {
      addToast('Nao foi possivel revisar o vinculo', 'err')
    } finally {
      setReviewingLink(false)
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
        ...(defaultReconciliationStatus && { reconciliation_status: defaultReconciliationStatus }),
        ledger_id: defaultLedgerId,
        sort_by: sortBy, sort_order: sortOrder,
      }
      const data = await getTransactions(filters)
      setTxs(data.items)
      setTotal(data.total)
      setTotalPages(data.total_pages)
      if (data.summary) setSummary(data.summary)
      setPage(p)
    } catch {
      addToast('Nao foi possivel carregar os lancamentos', 'err')
    } finally {
      setLoading(false)
    }
  }, [search, statusFilter, typeFilter, monthFilter, dateFrom, dateTo, accountFilter, categoryFilter, subcategoryFilter, installmentFilter, tagFilters, tagMode, sortBy, sortOrder, pageSize, defaultLedgerId, defaultReconciliationStatus])

  useEffect(() => { load(1) }, [search, statusFilter, typeFilter, monthFilter, dateFrom, dateTo, accountFilter, categoryFilter, subcategoryFilter, installmentFilter, tagFilters, tagMode, sortBy, sortOrder, pageSize, refreshKey, defaultLedgerId, defaultReconciliationStatus])
  useEffect(() => {
    getLedgers().then(setLedgers).catch(() => undefined)
  }, [refreshKey])
  useEffect(() => {
    const needingSuggestions = txs.filter(tx => (
      !tx.locked && !tx.category_id && !tx.reconciliation_id && !hasPendingDirectHistoryLink(tx)
    ))
    if (!needingSuggestions.length) return

    let cancelled = false

    async function loadPendingSuggestions() {
      const ids = needingSuggestions.filter(tx => rowSuggestions[tx.id] === undefined).map(tx => tx.id)
      if (!ids.length) return
      setSuggestionsLoading(current => new Set([...current, ...ids]))
      try {
        const data = await getTransactionSuggestionsBatch(ids)
        if (!cancelled) {
          setRowSuggestions(current => ({ ...current, ...data.items }))
          setRowSuggestionStates(current => ({ ...current, ...data.states }))
          setSuggestionErrors(current => {
            const next = new Set(current)
            ids.forEach(id => next.delete(id))
            return next
          })
        }
      } catch {
        if (!cancelled) setSuggestionErrors(current => new Set([...current, ...ids]))
      } finally {
        if (!cancelled) {
          setSuggestionsLoading(current => {
            const next = new Set(current)
            ids.forEach(id => next.delete(id))
            return next
          })
        }
      }
    }

    loadPendingSuggestions()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [txs])
  useEffect(() => {
    setRowSuggestions({})
    setRowSuggestionStates({})
    setSuggestionsLoading(new Set())
    setSuggestionErrors(new Set())
  }, [refreshKey])
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
      const { updated, skipped_locked, skipped_history_links } = await bulkClassify([...selected], bulkCatId, bulkSubId || undefined)
      const skipped = [
        skipped_locked ? `${skipped_locked} protegidos` : '',
        skipped_history_links ? `${skipped_history_links} aguardando revisao de vinculo` : '',
      ].filter(Boolean).join(', ')
      addToast(`${updated} lancamentos classificados${skipped ? ` (${skipped} ignorados)` : ''}`)
      setSelected(new Set()); setBulkCatId(''); setBulkSubId('')
      load(page)
    } catch { addToast('Erro na classificacao em lote', 'err') }
  }

  async function handlePrepareHistoricalLinks() {
    if (!selected.size || linkingBatch) return
    setLinkingBatch(true)
    const selectedIds = [...selected]
    const startedAt = Date.now()
    const localTime = () => new Date().toLocaleTimeString('pt-BR', { hour12: false })
    setLinkBatchLogs([
      { time: localTime(), message: `Iniciando vinculo em lote para ${selectedIds.length} lancamento(s)` },
      { time: localTime(), message: 'Enviando para analise e confirmacao no servidor' },
    ])
    const waitingLog = window.setInterval(() => {
      const elapsed = Math.round((Date.now() - startedAt) / 1000)
      setLinkBatchLogs(current => [
        ...current.slice(-11),
        { time: localTime(), message: `Processamento em andamento ha ${elapsed}s` },
      ])
    }, 10000)
    try {
      const result = await prepareHistoricalLinks(selectedIds)
      window.clearInterval(waitingLog)
      const serverLogs = result.logs || []
      setLinkBatchLogs([
        { time: localTime(), message: `Operacao ${result.operation_id || 'concluida'} recebida do servidor` },
        ...serverLogs,
      ])
      if (!result.matched) {
        const failure = result.failed ? `; ${result.failed} falharam na confirmacao` : ''
        const skipped = result.skipped ? `; ${result.skipped} ja vinculados, protegidos ou indisponiveis` : ''
        addToast(`Nenhum vinculo atende ao lote: descricao >95%, mesma data e valor exato (${result.without_match} sem correspondencia${skipped}${failure})`, 'err')
        return
      }
      addToast(`${result.matched} vinculo(s) confirmado(s) em lote; ${result.affected_ids.length} lancamento(s) atualizado(s)${result.without_match ? `; ${result.without_match} fora da regra` : ''}${result.skipped ? `; ${result.skipped} ignorado(s)` : ''}`)
      setSelected(new Set())
      await load(page)
      if (result.failed) addToast(`${result.failed} vinculo(s) nao puderam ser confirmados`, 'err')
    } catch (error: unknown) {
      const detail = (error as { detail?: string })?.detail
      setLinkBatchLogs(current => [
        ...current,
        { time: localTime(), message: `Falha: ${detail || 'erro de comunicacao com o servidor'}` },
      ])
      addToast(detail || 'Nao foi possivel buscar vinculos para os selecionados', 'err')
    } finally {
      window.clearInterval(waitingLog)
      setLinkingBatch(false)
    }
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
          <select className="h-8 px-2 rounded-md text-sm text-[#e8eaf0] outline-none flex-1 max-w-xs" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.12)' }} value={bulkSubId} onChange={e => setBulkSubId(e.target.value)}>
            <option value="">Sem subcategoria</option>
            {subcategories.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <button onClick={handleBulkClassify} disabled={!bulkCatId} className="px-3 py-1.5 rounded-md text-xs font-semibold disabled:opacity-40" style={{ background: '#c9a84c', color: '#0d0f14' }}>Aplicar</button>
          <button onClick={handlePrepareHistoricalLinks} disabled={linkingBatch} className="px-3 py-1.5 rounded-md text-xs font-semibold disabled:opacity-40" style={{ background: 'rgba(96,165,250,0.18)', border: '1px solid rgba(96,165,250,0.35)', color: '#93c5fd' }}>{linkingBatch ? 'Processando lote...' : 'Vincular selecionados'}</button>
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

      {linkBatchLogs.length > 0 && (
        <div className="mb-3 rounded-lg px-4 py-3" style={{ background: '#0d0f14', border: '1px solid rgba(96,165,250,0.22)' }}>
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-semibold text-[#93c5fd]">Progresso do vinculo em lote</span>
            {!linkingBatch && <button type="button" onClick={() => setLinkBatchLogs([])} className="text-[#5a5f73] hover:text-[#e8eaf0]" title="Fechar logs"><X size={14} /></button>}
          </div>
          <div className="max-h-32 overflow-auto font-mono text-[11px] text-[#8b90a4]">
            {linkBatchLogs.map((entry, index) => <div key={`${entry.time}-${index}`}><span className="text-[#5a5f73]">{entry.time}</span> · {entry.message}</div>)}
          </div>
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
                const pendingDirectLink = hasPendingDirectHistoryLink(tx)
                const chosenCategorySuggestion = (rowSuggestions[tx.id] || []).find(
                  suggestion => suggestion.category_id === rowDraft[tx.id]?.category_id
                )
                const subcategorySuggestions = chosenCategorySuggestion?.subcategories || []
                const st = tx.reconciliation_id
                  ? { label: 'Conciliado', bg: 'rgba(167,139,250,0.14)', color: '#c4b5fd' }
                  : tx.history_match_confirmed
                    ? { label: 'Vinculado', bg: 'rgba(96,165,250,0.12)', color: '#60a5fa' }
                    : (STATUS_STYLES[tx.status] || STATUS_STYLES.pending)
                return (
                  <tr key={tx.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }} className="hover:brightness-110 transition-all">
                    <td className="px-3 py-2.5"><input type="checkbox" checked={selected.has(tx.id)} onChange={() => toggleOne(tx.id)} className="cursor-pointer" /></td>
                    <td className="px-3 py-2.5 text-xs text-[#8b90a4] whitespace-nowrap">{formatDate(tx.date)}</td>
                    <td className="px-3 py-2.5 max-w-[260px]">
                      <span className="block truncate text-[#e8eaf0]" title={tx.description}>{tx.description}</span>
                      {!!tx.merchant_norm && (
                        <span className="mt-0.5 block truncate text-[10px] text-[#5a5f73]" title="Metadado em modo sombra">
                          {tx.transaction_method || 'other'} · {tx.merchant_norm}
                        </span>
                      )}
                      {!!tx.reconciliation_id && (
                        <span className="mt-1 block truncate text-[10px] text-violet-300" title={tx.reconciliation_counterpart_description}>
                          Conciliado com {tx.reconciliation_counterpart_account_name}: {tx.reconciliation_counterpart_description}
                        </span>
                      )}
                    </td>
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
                        <span
                          className="mt-1 inline-flex rounded px-1.5 py-0.5 text-[10px] font-semibold"
                          style={{ background: 'rgba(201,168,76,0.12)', color: '#e8c96e', border: '1px solid rgba(201,168,76,0.25)' }}
                          title="Categoria e subcategoria serao reaproveitadas nas demais parcelas deste plano"
                        >
                          {tx.installment_current && tx.installment_total
                            ? `${tx.installment_current}/${tx.installment_total}`
                            : (tx.installment_label || 'Parcelado')}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2.5">
                      {pendingDirectLink ? (
                        <p className="mb-1 max-w-[190px] text-[10px] leading-4 text-blue-300">
                          A classificacao sera espelhada apos confirmar o vinculo.
                        </p>
                      ) : !tx.locked && !tx.reconciliation_id && !rowDraft[tx.id]?.category_id && (() => {
                        const suggestions = rowSuggestions[tx.id]
                        if (suggestions && suggestions.length > 0) {
                          return (
                            <div className="mb-1 flex flex-wrap gap-1">
                              {suggestions.slice(0, 3).map((sg, i) => (
                                <button
                                  key={`chip-cat-${tx.id}-${i}`}
                                  type="button"
                                  onClick={() => patchRowDraft(tx, {
                                    category_id: sg.category_id,
                                    subcategory_id: '',
                                  })}
                                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold transition-all hover:opacity-80"
                                  style={{
                                    background: i === 0 ? 'rgba(201,168,76,0.18)' : 'rgba(255,255,255,0.06)',
                                    border: i === 0 ? '1px solid rgba(201,168,76,0.4)' : '1px solid rgba(255,255,255,0.1)',
                                    color: i === 0 ? '#e8c96e' : '#8b90a4',
                                    cursor: 'pointer',
                                  }}
                                  title={`${sg.justification} Clique para selecionar a categoria; a subcategoria sera escolhida separadamente.`}
                                >
                                  {sg.category_name}
                                  <span style={{ opacity: 0.65 }}>confianca {(sg.confidence ?? sg.category_probability ?? 0).toFixed(0)}%</span>
                                </button>
                              ))}
                            </div>
                          )
                        }
                        return (
                          <p className="mb-1 text-[10px] text-[#5a5f73]">
                            {suggestionErrors.has(tx.id)
                              ? 'Falha ao calcular sugestoes. Atualize para tentar novamente.'
                              : suggestionsLoading.has(tx.id)
                                ? 'Buscando resultados...'
                                : rowSuggestionStates[tx.id] === 'pending'
                                  ? 'Aguardando calculo na Central de Classificacao'
                                  : rowSuggestionStates[tx.id] === 'failed'
                                    ? 'Calculo falhou; tente novamente na Central'
                                    : 'Sem evidencia suficiente'}
                          </p>
                        )
                      })()}
                      <select
                        className="h-8 w-[190px] rounded-md px-2 text-xs text-[#e8eaf0] outline-none disabled:opacity-45 disabled:cursor-not-allowed"
                        style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.12)' }}
                        value={rowDraft[tx.id]?.category_id || ''}
                        disabled={!!tx.locked || !!tx.reconciliation_id || pendingDirectLink}
                        onChange={(e) => patchRowDraft(tx, { category_id: e.target.value, subcategory_id: '' })}
                      >
                        <option value="">Selecionar...</option>
                        {(rowSuggestions[tx.id] || []).length > 0 && <option value="" disabled>-- Sugeridas --</option>}
                        {(rowSuggestions[tx.id] || []).map((sg, i) => (
                          <option key={`sg-cat-${tx.id}-${i}-${sg.category_id}`} value={sg.category_id}>
                            {sg.category_name} (confianca {(sg.confidence ?? sg.category_probability).toFixed(0)}%)
                          </option>
                        ))}
                        {(rowSuggestions[tx.id] || []).length > 0 && <option value="" disabled>-- Todas --</option>}
                        {categories.filter(c => c.type === tx.type).map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                      </select>
                    </td>
                    <td className="px-3 py-2.5">
                      {!pendingDirectLink && !tx.locked && !tx.reconciliation_id && !rowDraft[tx.id]?.subcategory_id && (() => {
                        if (!subcategorySuggestions.length) return null
                        return (
                          <div className="mb-1 flex flex-wrap gap-1">
                            {subcategorySuggestions.slice(0, 3).map(sg => (
                              <button
                                key={`chip-sub-${tx.id}-${sg.subcategory_id}`}
                                type="button"
                                onClick={() => patchRowDraft(tx, { subcategory_id: sg.subcategory_id })}
                                className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold transition-all hover:opacity-80"
                                style={{
                                  background: 'rgba(96,165,250,0.10)',
                                  border: '1px solid rgba(96,165,250,0.22)',
                                  color: '#93c5fd',
                                  cursor: 'pointer',
                                }}
                              >
                                {sg.subcategory_name} <span className="opacity-65">{sg.confidence.toFixed(0)}%</span>
                              </button>
                            ))}
                          </div>
                        )
                      })()}
                      <select
                        className="h-8 w-[170px] rounded-md px-2 text-xs text-[#e8eaf0] outline-none disabled:opacity-45 disabled:cursor-not-allowed"
                        style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.12)' }}
                        value={rowDraft[tx.id]?.subcategory_id || ''}
                        disabled={!!tx.locked || !!tx.reconciliation_id || pendingDirectLink}
                        onChange={(e) => patchRowDraft(tx, { subcategory_id: e.target.value })}
                      >
                        <option value="">Sem subcategoria</option>
                        {subcategorySuggestions.map(sg => (
                            <option key={`sg-sub-${tx.id}-${sg.subcategory_id}`} value={sg.subcategory_id}>
                              {sg.subcategory_name} (confianca {sg.confidence.toFixed(0)}%)
                            </option>
                          ))}
                        {subcategories
                          .filter(subcategory => !subcategorySuggestions.some(candidate => candidate.subcategory_id === subcategory.id))
                          .map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                      </select>
                    </td>
                    <td className="px-3 py-2.5">
                      <input
                        className="h-8 w-[180px] rounded-md px-2 text-xs text-[#e8eaf0] outline-none disabled:opacity-45 disabled:cursor-not-allowed"
                        style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.12)' }}
                        value={rowDraft[tx.id]?.notes || ''}
                        disabled={!!tx.locked || !!tx.reconciliation_id || pendingDirectLink}
                        onChange={(e) => {
                          const val = e.target.value
                          setRowDraft(s => ({ ...s, [tx.id]: { ...(s[tx.id] || { category_id: '', subcategory_id: '', notes: '' }), notes: val } }))
                        }}
                        onKeyDown={(e) => { if (e.key === 'Enter' && rowDraft[tx.id]?.category_id) saveRow(tx) }}
                        placeholder="Observacao..."
                      />
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-1.5">
                        <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full" style={{ background: st.bg, color: st.color }}>{st.label}</span>
                        {pendingDirectLink && (
                          <button
                            type="button"
                            onClick={() => setLinkReviewId(tx.id)}
                            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold transition-all hover:opacity-80"
                            style={{ background: 'rgba(96,165,250,0.10)', border: '1px solid rgba(96,165,250,0.30)', color: '#93c5fd' }}
                            title="Comparar o lancamento real com o registro da base historica"
                          >
                            <Link2 size={11} />
                            Possivel vinculo {Number(tx.identity_score || 0).toFixed(0)}%
                          </button>
                        )}
                        {!tx.locked && !tx.reconciliation_id && !pendingDirectLink && (
                          <button
                            type="button"
                            onClick={() => saveRow(tx)}
                            disabled={!rowDraft[tx.id]?.category_id || !!savingRow[tx.id]}
                            className="inline-flex items-center px-2 py-1 rounded text-[10px] font-semibold disabled:opacity-40"
                            style={{ background: '#c9a84c', color: '#0d0f14' }}
                          >
                            {savingRow[tx.id] ? 'Salvando...' : 'Salvar e bloquear'}
                          </button>
                        )}
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
      {linkReviewId && (() => {
        const tx = txs.find(item => item.id === linkReviewId)
        if (!tx) return null
        const field = (label: string, value: string) => (
          <div><p className="text-[10px] uppercase tracking-wider text-[#5a5f73]">{label}</p><p className="mt-1 text-sm text-[#e8eaf0] break-words">{value || '-'}</p></div>
        )
        return (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: 'rgba(3,5,10,0.78)' }}>
            <div className="w-full max-w-4xl rounded-xl p-5 shadow-2xl" style={{ background: '#13161d', border: '1px solid rgba(96,165,250,0.3)' }}>
              <div className="flex items-start justify-between gap-4 mb-5">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-widest text-[#93c5fd]">Possivel vinculo historico</p>
                  <h3 className="mt-1 text-lg font-semibold text-[#e8eaf0]">Confira se os dois registros representam o mesmo lancamento</h3>
                  <p className="mt-1 text-sm text-[#8b90a4]">Compatibilidade calculada: <span className="font-semibold text-[#e8c96e]">{Number(tx.identity_score || 0).toFixed(1)}%</span></p>
                </div>
                <button type="button" onClick={() => setLinkReviewId(null)} className="p-1 text-[#8b90a4] hover:text-white"><X size={18} /></button>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <section className="rounded-lg p-4" style={{ background: '#0f1320', border: '1px solid rgba(255,255,255,0.08)' }}>
                  <h4 className="mb-4 text-sm font-semibold text-[#3ecf8e]">Lancamento real importado</h4>
                  <div className="grid gap-4 sm:grid-cols-2">
                    {field('Data', formatDate(tx.date))}
                    {field('Valor', `${tx.type === 'income' ? '+' : '-'}${formatCurrencyAbs(tx.amount)}`)}
                    <div className="sm:col-span-2">{field('Descricao', tx.description)}</div>
                    {field('Conta', tx.account_name)}
                    {field('Tipo', tx.type === 'income' ? 'Receita' : 'Despesa')}
                  </div>
                </section>
                <section className="rounded-lg p-4" style={{ background: '#0f1320', border: '1px solid rgba(255,255,255,0.08)' }}>
                  <h4 className="mb-4 text-sm font-semibold text-[#93c5fd]">Registro da base historica</h4>
                  <div className="grid gap-4 sm:grid-cols-2">
                    {field('Data', tx.match_history_date ? formatDate(tx.match_history_date) : '-')}
                    {field('Valor', formatCurrencyAbs(tx.match_history_amount || 0))}
                    <div className="sm:col-span-2">{field('Descricao', tx.match_history_description || '')}</div>
                    {field('Conta conhecida', tx.match_history_account_name || 'Origem sem conta definida')}
                    {field('Origem', tx.match_history_source || '')}
                    {field('Categoria', tx.match_history_category_name || '')}
                    {field('Subcategoria', tx.match_history_subcategory_name || '')}
                  </div>
                </section>
              </div>
              {tx.match_basis === 'installment_total' && (
                <p className="mt-4 rounded-lg p-3 text-xs text-amber-200" style={{ background: 'rgba(245,158,11,0.07)', border: '1px solid rgba(245,158,11,0.22)' }}>
                  Vinculo por parcelamento: esta parcela de {formatCurrencyAbs(tx.amount)} foi comparada ao total estimado de {formatCurrencyAbs(tx.match_comparison_amount || 0)}, na data reconstruida da primeira parcela ({formatDate(tx.match_comparison_date || '')}). Confirmar replica apenas a classificacao; os valores dos arquivos permanecem intactos.
                </p>
              )}
              <div className="mt-4 grid gap-3 sm:grid-cols-3">
                <div className="rounded-lg p-3" style={{ background: '#0f1320', border: '1px solid rgba(255,255,255,0.08)' }}>
                  <p className="text-[10px] uppercase tracking-wider text-[#5a5f73]">Diferenca de data</p>
                  <p className="mt-1 text-sm font-semibold text-[#e8eaf0]">{tx.match_date_difference_days == null ? 'Nao calculada' : `${tx.match_date_difference_days} dia(s)`}</p>
                </div>
                <div className="rounded-lg p-3" style={{ background: '#0f1320', border: '1px solid rgba(255,255,255,0.08)' }}>
                  <p className="text-[10px] uppercase tracking-wider text-[#5a5f73]">Diferenca de valor</p>
                  <p className="mt-1 text-sm font-semibold text-[#e8eaf0]">{formatCurrencyAbs(tx.match_amount_difference || 0)}</p>
                </div>
                <div className="rounded-lg p-3" style={{ background: '#0f1320', border: '1px solid rgba(255,255,255,0.08)' }}>
                  <p className="text-[10px] uppercase tracking-wider text-[#5a5f73]">Similaridade da descricao</p>
                  <p className="mt-1 text-sm font-semibold text-[#e8eaf0]">{Number(tx.match_description_similarity || 0).toFixed(1)}%</p>
                </div>
              </div>
              <p className="mt-4 text-xs text-[#8b90a4]">Confirmar vincula os registros, replica categoria e subcategoria da base historica e protege o lancamento contra alteracoes acidentais.</p>
              <div className="mt-5 flex justify-end gap-2">
                <button type="button" disabled={reviewingLink} onClick={() => handleHistoryLink(tx, 'reject')} className="h-9 rounded-md px-4 text-sm font-semibold disabled:opacity-50" style={{ background: 'rgba(248,113,113,0.10)', border: '1px solid rgba(248,113,113,0.3)', color: '#fca5a5' }}>Nao sao o mesmo</button>
                <button type="button" disabled={reviewingLink} onClick={() => handleHistoryLink(tx, 'confirm')} className="h-9 rounded-md px-4 text-sm font-semibold disabled:opacity-50" style={{ background: 'rgba(62,207,142,0.16)', border: '1px solid rgba(62,207,142,0.4)', color: '#6ee7b7' }}>{reviewingLink ? 'Salvando...' : 'Confirmar vinculo'}</button>
              </div>
            </div>
          </div>
        )
      })()}
    </div>
  )
}
