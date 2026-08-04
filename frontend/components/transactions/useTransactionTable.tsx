'use client'
import { useState, useEffect, useCallback } from 'react'
import { ChevronUp, ChevronDown } from 'lucide-react'
import { useStore } from '@/store/app'
import { getTransactions, bulkClassify, classifyTransaction, getTransactionSuggestionsBatch, getLedgers, includeTransactionsInLedger, excludeTransactionsFromLedger, unlockTransaction, isAdmin, reviewHistoricalMatch, type TransactionSuggestion } from '@/lib/api'
import type { Ledger, Transaction } from '@/types'
import { buildTransactionFilters, hasPendingDirectHistoryLink, type TransactionTableProps } from './transactionTableUtils'
import { runHistoricalLinkBatch, type HistoryLinkBatchProgress } from './historyLinkBatch'

export type Props = TransactionTableProps

export function useTransactionTable({
  defaultStatus,
  defaultSortBy = 'date',
  defaultSortOrder = 'desc',
  defaultLedgerId = 'none',
  moveTargetLedgerId = '',
  moveTargetLedgerName = '',
  defaultReconciliationStatus,
}: Props) {
  const { months, accounts, categories, subcategories, addToast, refreshKey, setPendingCount } = useStore()
  const [txs, setTxs] = useState<Transaction[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [summary, setSummary] = useState({ total_income: 0, total_expense: 0, balance: 0, pending_count: 0, reconciled_count: 0 })
  const [loading, setLoading] = useState(false)
  const [linkReviewId, setLinkReviewId] = useState<string | null>(null)
  const [batchReviewIds, setBatchReviewIds] = useState<string[]>([])
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
  const [linkBatchProgress, setLinkBatchProgress] = useState<HistoryLinkBatchProgress | null>(null)
  const [rowDraft, setRowDraft] = useState<Record<string, { category_id: string; subcategory_id: string; notes: string }>>({})
  const [savingRow, setSavingRow] = useState<Record<string, boolean>>({})
  const [rowSuggestions, setRowSuggestions] = useState<Record<string, TransactionSuggestion[]>>({})
  const [rowSuggestionStates, setRowSuggestionStates] = useState<Record<string, string>>({})
  const [suggestionsLoading, setSuggestionsLoading] = useState<Set<string>>(new Set())
  const [suggestionErrors, setSuggestionErrors] = useState<Set<string>>(new Set())

  async function refreshPendingBadge() {
    try {
      const pending = await getTransactions({
        status: 'pending',
        reconciliation_status: 'unmatched',
        page_size: 1,
      })
      setPendingCount(pending.total)
    } catch {
      // A tabela continua utilizavel mesmo se apenas o contador global falhar.
    }
  }

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
        : 'LanÃ§amento classificado')
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
      await refreshPendingBadge()
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
    const isBatchReview = batchReviewIds.includes(tx.id)
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
      if (isBatchReview) {
        const remainingBatchIds = batchReviewIds.filter(id => !affected.has(id))
        setBatchReviewIds(remainingBatchIds)
        setLinkReviewId(remainingBatchIds[0] || null)
        setLinkBatchLogs(current => [
          ...current,
          {
            time: new Date().toLocaleTimeString('pt-BR', { hour12: false }),
            message: `${action === 'confirm' ? 'Vinculo aprovado' : 'Vinculo rejeitado'} manualmente; ${remainingBatchIds.length} restante(s)`,
          },
        ])
      } else {
        setLinkReviewId(null)
      }
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
      await refreshPendingBadge()
    } catch {
      if (isBatchReview) {
        setLinkBatchLogs(current => [
          ...current,
          { time: new Date().toLocaleTimeString('pt-BR', { hour12: false }), message: 'Falha ao salvar a revisao manual; o item permanece na fila' },
        ])
      }
      addToast('Nao foi possivel revisar o vinculo', 'err')
    } finally {
      setReviewingLink(false)
    }
  }

  const load = useCallback(async (p = 1) => {
    setLoading(true)
    try {
      const filters = buildTransactionFilters({
        page: p, pageSize, search, status: statusFilter, type: typeFilter,
        month: monthFilter, dateFrom, dateTo, account: accountFilter,
        category: categoryFilter, subcategory: subcategoryFilter,
        installment: installmentFilter, tagFilters, tagMode,
        reconciliationStatus: defaultReconciliationStatus,
        ledgerId: defaultLedgerId, sortBy, sortOrder,
      })
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
    if (sortBy !== col) return <span className="opacity-20 text-[10px]">â†•</span>
    return sortOrder === 'asc' ? <ChevronUp size={12} className="text-[#c9a84c]" /> : <ChevronDown size={12} className="text-[#c9a84c]" />
  }

  function toggleAll() {
    if (selected.size === txs.length) setSelected(new Set())
    else {
      const types = new Set(txs.map(tx => tx.type))
      if (types.size > 1) {
        addToast('Filtre por receita ou despesa antes de selecionar todos para classificar em lote', 'err')
        return
      }
      setSelected(new Set(txs.map(t => t.id)))
    }
  }
  function toggleOne(id: string) {
    const transaction = txs.find(tx => tx.id === id)
    if (!transaction) return
    setSelected(current => {
      const next = new Set(current)
      if (next.has(id)) {
        next.delete(id)
        return next
      }
      const selectedType = txs.find(tx => next.has(tx.id))?.type
      if (selectedType && selectedType !== transaction.type) {
        addToast('A classificacao em lote aceita somente receitas ou somente despesas', 'err')
        return current
      }
      next.add(id)
      return next
    })
  }

  function toggleTagFilter(tag: string) {
    setTagFilters(current => current.includes(tag) ? current.filter(item => item !== tag) : [...current, tag])
  }

  async function handleBulkClassify() {
    if (!bulkCatId || !selected.size) return
    const selectedTransactions = txs.filter(tx => selected.has(tx.id))
    const selectedTypes = new Set(selectedTransactions.map(tx => tx.type))
    if (selectedTypes.size !== 1) {
      addToast('A classificacao em lote aceita somente receitas ou somente despesas', 'err')
      return
    }
    const category = categories.find(item => item.id === bulkCatId)
    if (category?.type !== selectedTransactions[0].type) {
      addToast('Escolha uma categoria compativel com o tipo dos lancamentos selecionados', 'err')
      return
    }
    const classifiedCount = selectedTransactions.filter(tx => tx.locked && tx.category_id).length
    const includeClassified = classifiedCount > 0 && isAdmin()
      ? window.confirm(
        `${classifiedCount} lancamento(s) selecionado(s) ja possuem classificacao.\n\nOK: aplicar a nova categoria/subcategoria tambem neles.\nCancelar: aplicar somente nos lancamentos ainda nao classificados.`
      )
      : false
    if (classifiedCount > 0 && !isAdmin()) {
      addToast('Itens ja classificados serao mantidos: apenas administrador pode reclassifica-los', 'err')
    }
    try {
      const { updated, overwritten_classified, skipped_locked, skipped_history_links } = await bulkClassify(
        [...selected], bulkCatId, bulkSubId || undefined, includeClassified
      )
      const skipped = [
        skipped_locked ? `${skipped_locked} protegidos` : '',
        skipped_history_links ? `${skipped_history_links} aguardando revisao de vinculo` : '',
      ].filter(Boolean).join(', ')
      const overwritten = overwritten_classified ? `; ${overwritten_classified} classificacao(oes) existente(s) atualizada(s)` : ''
      addToast(`${updated} lancamentos classificados${overwritten}${skipped ? ` (${skipped} ignorados)` : ''}`)
      setSelected(new Set()); setBulkCatId(''); setBulkSubId('')
      await load(page)
      await refreshPendingBadge()
    } catch (error: unknown) {
      addToast((error as { detail?: string })?.detail || 'Erro na classificacao em lote', 'err')
    }
  }

  async function handlePrepareHistoricalLinks() {
    if (!selected.size || linkingBatch) return
    setLinkingBatch(true)
    const selectedIds = [...selected]
    const localTime = () => new Date().toLocaleTimeString('pt-BR', { hour12: false })
    setLinkBatchLogs([
      { time: localTime(), message: `Iniciando vinculo em lote para ${selectedIds.length} lancamento(s)` },
    ])
    setLinkBatchProgress(null)
    try {
      const result = await runHistoricalLinkBatch(selectedIds, entry => {
        setLinkBatchLogs(current => [...current.slice(-119), entry])
      }, setLinkBatchProgress)
      if (!result.matched && !result.manual_review) {
        const failure = result.failed ? `; ${result.failed} falharam na confirmacao` : ''
        const skipped = result.skipped ? `; ${result.skipped} ja vinculados, protegidos ou indisponiveis` : ''
        addToast(`Nenhum vinculo atende ao lote: descricao >=75%, mesma data e valor exato (${result.without_match} sem correspondencia${skipped}${failure})`, 'err')
        return
      }
      addToast(`${result.matched} vinculo(s) confirmado(s) em lote${result.manual_review ? `; ${result.manual_review} aguardando revisao manual` : ''}${result.without_match ? `; ${result.without_match} sem candidato` : ''}${result.skipped ? `; ${result.skipped} ignorado(s)` : ''}`)
      setSelected(new Set())
      await load(page)
      await refreshPendingBadge()
      setBatchReviewIds(result.manual_review_ids)
      setLinkReviewId(result.manual_review_ids[0] || null)
      if (result.failed) addToast(`${result.failed} vinculo(s) nao puderam ser confirmados`, 'err')
    } catch (error: unknown) {
      const detail = (error as { detail?: string })?.detail
      const timedOut = (error as { code?: string })?.code === 'REQUEST_TIMEOUT'
      setLinkBatchLogs(current => [
        ...current,
        { time: localTime(), message: timedOut
          ? 'O servidor pode continuar concluindo o ultimo bloco. Os blocos seguintes nao foram enviados para evitar processamento concorrente; atualize a tela em instantes.'
          : `Operacao interrompida: ${detail || 'erro de comunicacao com o servidor'}` },
      ])
      addToast(timedOut
        ? 'O ultimo bloco ainda pode estar sendo concluido pelo servidor; atualize em instantes'
        : (detail || 'Nao foi possivel buscar vinculos para os selecionados'), 'err')
    } finally {
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

  return { months, accounts, categories, subcategories, txs, total, page, totalPages, summary, loading, linkReviewId, batchReviewIds, reviewingLink, search, statusFilter, typeFilter, monthFilter, accountFilter, categoryFilter, subcategoryFilter, installmentFilter, dateFrom, dateTo, tagMode, tagFilters, sortBy, sortOrder, pageSize, ledgers, selected, bulkCatId, bulkSubId, bulkLedgerId, linkingBatch, linkBatchLogs, linkBatchProgress, rowDraft, savingRow, rowSuggestions, rowSuggestionStates, suggestionsLoading, suggestionErrors, defaultLedgerId, moveTargetLedgerId, moveTargetLedgerName, setSearch, setMonthFilter, setTypeFilter, setAccountFilter, setCategoryFilter, setSubcategoryFilter, setInstallmentFilter, setPageSize, setDateFrom, setDateTo, setTagMode, setTagFilters, setBulkCatId, setBulkSubId, setBulkLedgerId, setLinkBatchLogs, setLinkReviewId, setRowDraft, saveRow, patchRowDraft, handleHistoryLink, load, toggleSort, SortIcon, toggleOne, toggleAll, handleBulkClassify, toggleTagFilter, handlePrepareHistoricalLinks, handleUnlock, handleMoveToLedger }
}
