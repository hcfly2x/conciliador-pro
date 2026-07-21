'use client'

import { useCallback, useEffect, useState } from 'react'
import { AlertCircle, BarChart3, CheckCircle2, ChevronLeft, ChevronRight, Loader2, Play, RefreshCw } from 'lucide-react'
import {
  bulkClassify,
  classifyTransaction,
  dismissTransactionSuggestions,
  getActiveSuggestionJob,
  getSuggestionJob,
  getSuggestionEvaluation,
  getSuggestionSummary,
  getTransactionSuggestionsBatch,
  getTransactions,
  reviewHistoricalMatch,
  startSuggestionJob,
  type SuggestionJob,
  type SuggestionEvaluation,
  type SuggestionSummary,
  type TransactionSuggestion,
} from '@/lib/api'
import { useStore } from '@/store/app'
import type { Transaction } from '@/types'
import { formatCurrencyAbs, formatDate } from '@/lib/utils'

type Queue = 'links' | 'suggestions' | 'none' | 'waiting' | 'dismissed' | 'classified'
type Draft = { category_id: string; subcategory_id: string; notes: string }

const EMPTY_SUMMARY: SuggestionSummary = {
  pending: 0, links: 0, strong: 0, weak: 0, none: 0, waiting: 0, dismissed: 0, classified: 0,
}

function similarityKey(tx: Transaction) {
  return (tx.merchant_norm || tx.description || '').trim().toLowerCase()
}

export default function ClassificationCenter() {
  const { categories, subcategories, addToast, bumpRefresh } = useStore()
  const [queue, setQueue] = useState<Queue>('links')
  const [strength, setStrength] = useState<'all' | 'strong' | 'weak'>('all')
  const [search, setSearch] = useState('')
  const [items, setItems] = useState<Transaction[]>([])
  const [suggestions, setSuggestions] = useState<Record<string, TransactionSuggestion[]>>({})
  const [drafts, setDrafts] = useState<Record<string, Draft>>({})
  const [summary, setSummary] = useState<SuggestionSummary>(EMPTY_SUMMARY)
  const [job, setJob] = useState<SuggestionJob | null>(null)
  const [evaluation, setEvaluation] = useState<SuggestionEvaluation | null>(null)
  const [evaluationLoading, setEvaluationLoading] = useState(false)
  const [loading, setLoading] = useState(false)
  const [busyId, setBusyId] = useState('')
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [total, setTotal] = useState(0)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkCategory, setBulkCategory] = useState('')
  const [bulkSubcategory, setBulkSubcategory] = useState('')

  const loadSummary = useCallback(async () => {
    try { setSummary(await getSuggestionSummary()) } catch { /* mantem ultimo resumo */ }
  }, [])

  const loadQueue = useCallback(async (targetPage = 1) => {
    setLoading(true)
    try {
      const data = await getTransactions({
        page: targetPage,
        page_size: 25,
        ledger_id: 'all',
        classification_queue: queue,
        ...(queue === 'suggestions' && strength !== 'all' ? { suggestion_strength: strength } : {}),
        ...(search ? { search } : {}),
        sort_by: queue === 'suggestions' ? 'suggestion_confidence' : queue === 'links' ? 'identity_score' : 'date',
        sort_order: 'desc',
      })
      setItems(data.items)
      setPage(data.page)
      setTotalPages(Math.max(1, data.total_pages))
      setTotal(data.total)
      setSelected(new Set())
      const nextDrafts: Record<string, Draft> = {}
      data.items.forEach(tx => {
        nextDrafts[tx.id] = {
          category_id: tx.category_id || '', subcategory_id: tx.subcategory_id || '', notes: tx.notes || '',
        }
      })
      setDrafts(nextDrafts)
      if (data.items.length) {
        const result = await getTransactionSuggestionsBatch(data.items.map(tx => tx.id))
        setSuggestions(result.items)
      } else {
        setSuggestions({})
      }
    } catch {
      addToast('Nao foi possivel carregar a fila de classificacao', 'err')
    } finally {
      setLoading(false)
    }
  }, [addToast, queue, search, strength])

  useEffect(() => { loadQueue(1); loadSummary() }, [loadQueue, loadSummary])
  useEffect(() => {
    getActiveSuggestionJob().then(active => { if (active) setJob(active) }).catch(() => undefined)
  }, [])
  useEffect(() => {
    if (!job?.id || !['queued', 'running'].includes(job.status)) return
    const timer = window.setTimeout(async () => {
      try {
        const updated = await getSuggestionJob(job.id)
        setJob(updated)
        if (updated.status === 'completed') {
          addToast(updated.message || 'Sugestoes calculadas')
          bumpRefresh()
          await Promise.all([loadSummary(), loadQueue(1)])
        } else if (updated.status === 'failed') {
          addToast(updated.error || 'Falha ao calcular sugestoes', 'err')
        }
      } catch { /* tenta novamente */ }
    }, 1500)
    return () => window.clearTimeout(timer)
  }, [addToast, bumpRefresh, job, loadQueue, loadSummary])

  function patchDraft(id: string, patch: Partial<Draft>) {
    setDrafts(current => ({ ...current, [id]: { ...(current[id] || { category_id: '', subcategory_id: '', notes: '' }), ...patch } }))
  }

  function removeLocally(ids: string[]) {
    const removed = new Set(ids)
    setItems(current => current.filter(tx => !removed.has(tx.id)))
    setTotal(current => Math.max(0, current - removed.size))
    setSelected(new Set())
  }

  async function runSuggestions(full = false) {
    if (full && !window.confirm('Recalcular todas as sugestoes, inclusive as ja calculadas?')) return
    try {
      const response = await startSuggestionJob(full)
      setJob({
        id: response.job_id, status: 'queued', mode: full ? 'full' : 'incremental', processed: 0, total: 0,
        updated: 0, with_suggestions: 0, without_suggestions: 0, message: 'Aguardando inicio', logs: [],
        error: '', created_at: '', started_at: '', finished_at: '',
      })
    } catch {
      addToast('Nao foi possivel iniciar o calculo', 'err')
    }
  }

  async function runEvaluation() {
    setEvaluationLoading(true)
    try {
      setEvaluation(await getSuggestionEvaluation())
    } catch {
      addToast('Nao foi possivel avaliar as sugestoes', 'err')
    } finally {
      setEvaluationLoading(false)
    }
  }

  async function applyOne(tx: Transaction) {
    const draft = drafts[tx.id]
    if (!draft?.category_id) { addToast('Escolha uma categoria', 'err'); return }
    setBusyId(tx.id)
    try {
      const result = await classifyTransaction(tx.id, {
        category_id: draft.category_id,
        subcategory_id: draft.subcategory_id || null,
        notes: draft.notes,
        apply_to_installments: true,
      })
      removeLocally(result.affected_ids || [tx.id])
      addToast('Classificado. Proximo lancamento pronto.')
      loadSummary()
    } catch {
      addToast('Erro ao classificar o lancamento', 'err')
    } finally { setBusyId('') }
  }

  async function applySimilar(tx: Transaction) {
    const draft = drafts[tx.id]
    if (!draft?.category_id) { addToast('Escolha uma categoria primeiro', 'err'); return }
    const key = similarityKey(tx)
    const ids = items.filter(item => item.type === tx.type && similarityKey(item) === key).map(item => item.id)
    if (ids.length < 2) { addToast('Nenhum outro lancamento semelhante nesta fila', 'err'); return }
    if (!window.confirm(`Aplicar esta classificacao a ${ids.length} lancamentos semelhantes?`)) return
    setBusyId(tx.id)
    try {
      const result = await bulkClassify(ids, draft.category_id, draft.subcategory_id || undefined)
      removeLocally(ids)
      addToast(`${result.updated} lancamentos classificados`)
      loadSummary()
    } catch { addToast('Erro na classificacao de semelhantes', 'err') }
    finally { setBusyId('') }
  }

  async function applySelected() {
    const ids = [...selected]
    const txTypes = new Set(items.filter(tx => selected.has(tx.id)).map(tx => tx.type))
    if (!ids.length || !bulkCategory) { addToast('Selecione lancamentos e categoria', 'err'); return }
    if (txTypes.size !== 1) { addToast('O lote deve conter somente receitas ou somente despesas', 'err'); return }
    if (!window.confirm(`Classificar ${ids.length} lancamentos selecionados?`)) return
    setBusyId('bulk')
    try {
      const result = await bulkClassify(ids, bulkCategory, bulkSubcategory || undefined)
      removeLocally(ids)
      addToast(`${result.updated} lancamentos classificados`)
      loadSummary()
    } catch { addToast('Erro na classificacao em lote', 'err') }
    finally { setBusyId('') }
  }

  async function dismiss(tx: Transaction) {
    setBusyId(tx.id)
    try {
      await dismissTransactionSuggestions(tx.id)
      removeLocally([tx.id]); addToast('Sugestoes ignoradas para este lancamento'); loadSummary()
    } catch { addToast('Erro ao ignorar sugestoes', 'err') }
    finally { setBusyId('') }
  }

  async function reviewLink(tx: Transaction, action: 'confirm' | 'reject') {
    setBusyId(tx.id)
    try {
      const result = await reviewHistoricalMatch(tx.id, action)
      removeLocally(result.affected_ids || [tx.id])
      addToast(action === 'confirm' ? 'Vinculo confirmado e classificacao aplicada' : 'Vinculo rejeitado; o lancamento seguira para sugestoes')
      loadSummary()
    } catch { addToast('Nao foi possivel revisar o vinculo', 'err') }
    finally { setBusyId('') }
  }

  const activeTx = items[0]
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null
      if (target && ['INPUT', 'SELECT', 'TEXTAREA'].includes(target.tagName)) return
      if (!activeTx || !['suggestions', 'none'].includes(queue)) return
      if (['1', '2', '3'].includes(event.key)) {
        const suggestion = suggestions[activeTx.id]?.[Number(event.key) - 1]
        if (suggestion) {
          patchDraft(activeTx.id, { category_id: suggestion.category_id, subcategory_id: '' })
          event.preventDefault()
        }
      }
      if (event.key === 'Enter' && drafts[activeTx.id]?.category_id) {
        applyOne(activeTx)
        event.preventDefault()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [activeTx, drafts, queue, suggestions])

  const queueTabs = [
    { value: 'links' as const, label: 'Vinculos diretos', count: summary.links },
    { value: 'suggestions' as const, label: 'Com sugestoes', count: summary.strong + summary.weak },
    { value: 'none' as const, label: 'Sem evidencia', count: summary.none },
    { value: 'waiting' as const, label: 'Aguardando calculo', count: summary.waiting },
    { value: 'dismissed' as const, label: 'Ignorados', count: summary.dismissed },
    { value: 'classified' as const, label: 'Classificados', count: summary.classified },
  ]

  const selectedType = items.find(tx => selected.has(tx.id))?.type
  const bulkCategories = categories.filter(category => !selectedType || category.type === selectedType)
  const progress = job?.total ? Math.min(100, (job.processed / job.total) * 100) : 0

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-bold text-[#e8eaf0]">Central de Classificacao</h1>
          <p className="mt-1 text-sm text-[#8b90a4]">Revise vinculos primeiro; depois use o Top 3 para classificar com poucos cliques.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => runSuggestions(false)} disabled={!!job && ['queued', 'running'].includes(job.status)} className="h-10 rounded-lg px-4 text-sm font-semibold disabled:opacity-50" style={{ background: '#c9a84c', color: '#0d0f14' }}>
            <span className="flex items-center gap-2"><Play size={14} /> Calcular pendentes</span>
          </button>
          <button onClick={() => runSuggestions(true)} disabled={!!job && ['queued', 'running'].includes(job.status)} className="h-10 rounded-lg px-4 text-sm font-semibold text-[#8b90a4] disabled:opacity-50" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.10)' }}>
            <span className="flex items-center gap-2"><RefreshCw size={14} /> Recalcular tudo</span>
          </button>
          <button onClick={runEvaluation} disabled={evaluationLoading} className="h-10 rounded-lg px-4 text-sm font-semibold text-blue-300 disabled:opacity-50" style={{ background: '#1a1e28', border: '1px solid rgba(96,165,250,.25)' }}>
            <span className="flex items-center gap-2">{evaluationLoading ? <Loader2 size={14} className="animate-spin" /> : <BarChart3 size={14} />} Avaliar qualidade</span>
          </button>
        </div>
      </div>

      {evaluation && (
        <section className="rounded-xl p-4" style={{ background: '#13161d', border: '1px solid rgba(96,165,250,.25)' }}>
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div><h2 className="text-sm font-semibold text-[#e8eaf0]">Avaliacao objetiva das sugestoes</h2><p className="mt-1 text-xs text-[#8b90a4]">Cada lancamento e retirado das proprias evidencias. A avaliacao nao altera classificacoes nem pesos.</p></div>
            <span className="text-xs text-[#5a5f73]">{evaluation.evaluated} de {evaluation.eligible_total} classificados{evaluation.truncated ? ' (amostra)' : ''}</span>
          </div>
          <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
            {[
              ['Cobertura', evaluation.coverage, `${evaluation.with_suggestions} com sugestao`],
              ['Categoria Top 1', evaluation.category.top1_accuracy, `${evaluation.category.top1_hits} acertos`],
              ['Categoria Top 3', evaluation.category.top3_accuracy, `${evaluation.category.top3_hits} acertos`],
              ['Subcategoria Top 1', evaluation.subcategory.top1_accuracy, `${evaluation.subcategory.top1_hits}/${evaluation.subcategory.evaluated}`],
              ['Subcategoria Top 3', evaluation.subcategory.top3_accuracy, `${evaluation.subcategory.top3_hits}/${evaluation.subcategory.evaluated}`],
            ].map(([label, value, detail]) => <div key={String(label)} className="rounded-lg bg-white/[.025] p-3"><p className="text-[10px] font-semibold uppercase tracking-wider text-[#5a5f73]">{label}</p><p className="mt-1 text-xl font-bold text-[#e8c96e]">{Number(value).toFixed(1)}%</p><p className="text-[11px] text-[#8b90a4]">{detail}</p></div>)}
          </div>
          <div className="mt-4"><p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-[#5a5f73]">Confianca x acerto Top 1</p><div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">{evaluation.calibration.map(bucket => <div key={bucket.range} className="rounded-md bg-black/10 px-3 py-2 text-xs text-[#8b90a4]"><span className="text-[#e8eaf0]">{bucket.range}</span><span className="float-right">{bucket.count} caso(s)</span><p className="mt-1">Confianca media {bucket.average_confidence.toFixed(1)}% · acerto {bucket.accuracy.toFixed(1)}%</p></div>)}</div></div>
        </section>
      )}

      {job && (
        <section className="rounded-xl p-4" style={{ background: '#13161d', border: `1px solid ${job.status === 'failed' ? 'rgba(248,113,113,.35)' : 'rgba(201,168,76,.28)'}` }}>
          <div className="flex items-center gap-2 text-sm text-[#e8eaf0]">
            {['queued', 'running'].includes(job.status) ? <Loader2 size={15} className="animate-spin text-[#e8c96e]" /> : job.status === 'completed' ? <CheckCircle2 size={15} className="text-emerald-400" /> : <AlertCircle size={15} className="text-red-400" />}
            <span>{job.message || 'Preparando calculo'}</span>
            <span className="ml-auto text-xs text-[#8b90a4]">{job.processed} / {job.total}</span>
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded bg-[#1a1e28]"><div className="h-full bg-[#c9a84c] transition-all" style={{ width: `${progress}%` }} /></div>
          {!!job.logs.length && <div className="mt-3 max-h-24 overflow-auto rounded bg-black/15 px-3 py-2 font-mono text-[11px] text-[#8b90a4]">{job.logs.slice(-5).map((log, index) => <div key={`${log.time}-${index}`}>{log.time} · {log.message}</div>)}</div>}
        </section>
      )}

      <div className="flex flex-wrap gap-2">
        {queueTabs.map(tab => <button key={tab.value} onClick={() => { setQueue(tab.value); setPage(1) }} className="rounded-lg px-3 py-2 text-sm font-semibold" style={{ background: queue === tab.value ? 'rgba(201,168,76,.18)' : '#1a1e28', border: `1px solid ${queue === tab.value ? 'rgba(201,168,76,.45)' : 'rgba(255,255,255,.07)'}`, color: queue === tab.value ? '#e8c96e' : '#8b90a4' }}>{tab.label} <span className="ml-1 opacity-60">{tab.count}</span></button>)}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <input value={search} onChange={event => setSearch(event.target.value)} placeholder="Buscar lancamento..." className="h-9 w-64 rounded-md px-3 text-sm text-[#e8eaf0] outline-none" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,.08)' }} />
        {queue === 'suggestions' && <select value={strength} onChange={event => setStrength(event.target.value as typeof strength)} className="h-9 rounded-md px-3 text-sm text-[#e8eaf0]" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,.08)' }}><option value="all">Todas as forcas</option><option value="strong">Fortes (70%+)</option><option value="weak">Moderadas</option></select>}
        <button onClick={() => { loadQueue(page); loadSummary() }} className="h-9 rounded-md px-3 text-sm text-[#8b90a4]" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,.08)' }}><RefreshCw size={14} /></button>
        <span className="ml-auto text-xs text-[#8b90a4]">{total} lancamento(s)</span>
      </div>

      {selected.size > 0 && queue !== 'links' && queue !== 'classified' && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl p-3" style={{ background: 'rgba(96,165,250,.08)', border: '1px solid rgba(96,165,250,.22)' }}>
          <span className="text-sm font-semibold text-blue-300">{selected.size} selecionado(s)</span>
          <select value={bulkCategory} onChange={event => { setBulkCategory(event.target.value); setBulkSubcategory('') }} className="h-9 rounded-md px-2 text-sm text-[#e8eaf0]" style={{ background: '#1a1e28' }}><option value="">Categoria do lote</option>{bulkCategories.map(category => <option key={category.id} value={category.id}>{category.name}</option>)}</select>
          <select value={bulkSubcategory} onChange={event => setBulkSubcategory(event.target.value)} className="h-9 rounded-md px-2 text-sm text-[#e8eaf0]" style={{ background: '#1a1e28' }}><option value="">Sem subcategoria</option>{subcategories.map(subcategory => <option key={subcategory.id} value={subcategory.id}>{subcategory.name}</option>)}</select>
          <button onClick={applySelected} disabled={busyId === 'bulk'} className="h-9 rounded-md bg-blue-500/20 px-3 text-sm font-semibold text-blue-300 disabled:opacity-50">Aplicar ao lote</button>
        </div>
      )}

      {loading ? <div className="py-16 text-center"><Loader2 className="mx-auto animate-spin text-[#c9a84c]" /></div> : items.length === 0 ? (
        <div className="rounded-xl py-16 text-center text-sm text-[#8b90a4]" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,.07)' }}>Esta fila esta vazia.</div>
      ) : <div className="space-y-3">
        {items.map((tx, index) => {
          const txSuggestions = suggestions[tx.id] || []
          const draft = drafts[tx.id] || { category_id: '', subcategory_id: '', notes: '' }
          const chosenSuggestion = txSuggestions.find(suggestion => suggestion.category_id === draft.category_id)
          const similarCount = items.filter(item => item.type === tx.type && similarityKey(item) === similarityKey(tx)).length
          return (
            <article key={tx.id} className="rounded-xl p-4" style={{ background: '#13161d', border: `1px solid ${index === 0 ? 'rgba(201,168,76,.4)' : 'rgba(255,255,255,.07)'}` }}>
              <div className="flex items-start gap-3">
                {queue !== 'links' && queue !== 'classified' && <input type="checkbox" checked={selected.has(tx.id)} onChange={() => setSelected(current => { const next = new Set(current); if (next.has(tx.id)) next.delete(tx.id); else { const first = items.find(item => next.has(item.id)); if (!first || first.type === tx.type) next.add(tx.id); else addToast('Selecione somente receitas ou somente despesas', 'err') } return next })} className="mt-1" />}
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1"><strong className="text-sm text-[#e8eaf0]">{tx.description}</strong><span className="text-xs text-[#8b90a4]">{formatDate(tx.date)} · {tx.account_name}</span><span className={`ml-auto text-sm font-bold ${tx.type === 'income' ? 'text-emerald-400' : 'text-red-400'}`}>{tx.type === 'income' ? '+' : '-'}{formatCurrencyAbs(tx.amount)}</span></div>
                  {!!tx.merchant_norm && <p className="mt-1 text-[11px] text-[#5a5f73]">{tx.transaction_method} · {tx.merchant_norm}</p>}
                </div>
              </div>

              {queue === 'links' ? (
                <div className="mt-4 grid gap-3 md:grid-cols-2">
                  <div className="rounded-lg bg-white/[.025] p-3"><p className="text-[10px] font-semibold uppercase tracking-wider text-[#5a5f73]">Lancamento real</p><p className="mt-2 text-sm text-[#e8eaf0]">{tx.description}</p><p className="mt-1 text-xs text-[#8b90a4]">{formatDate(tx.date)} · {formatCurrencyAbs(tx.amount)}</p></div>
                  <div className="rounded-lg bg-blue-500/[.05] p-3"><p className="text-[10px] font-semibold uppercase tracking-wider text-blue-300">Base historica</p><p className="mt-2 text-sm text-[#e8eaf0]">{tx.match_history_description}</p><p className="mt-1 text-xs text-[#8b90a4]">{formatDate(tx.match_history_date || '')} · {formatCurrencyAbs(tx.match_history_amount || 0)} · {tx.match_history_category_name}{tx.match_history_subcategory_name ? ` / ${tx.match_history_subcategory_name}` : ''}</p></div>
                  {tx.match_basis === 'installment_total' && <p className="md:col-span-2 rounded-lg bg-amber-500/[.07] p-3 text-xs text-amber-200">Vinculo por parcelamento: a parcela real de {formatCurrencyAbs(tx.amount)} foi comparada ao total estimado de {formatCurrencyAbs(tx.match_comparison_amount || 0)}, na data reconstruida da primeira parcela ({formatDate(tx.match_comparison_date || '')}). Os valores reais nao serao alterados.</p>}
                  <div className="md:col-span-2 flex flex-wrap items-center gap-2 text-xs text-[#8b90a4]"><span>Compatibilidade {tx.identity_score?.toFixed(0)}%</span><span>Data: {tx.match_date_difference_days ?? '?'} dia(s)</span><span>Valor: {formatCurrencyAbs(tx.match_amount_difference || 0)}</span><span>Descricao: {tx.match_description_similarity?.toFixed(0)}%</span><button onClick={() => reviewLink(tx, 'confirm')} disabled={busyId === tx.id} className="ml-auto rounded-md bg-emerald-500/15 px-3 py-2 font-semibold text-emerald-300">Confirmar mesmo lancamento</button><button onClick={() => reviewLink(tx, 'reject')} disabled={busyId === tx.id} className="rounded-md bg-red-500/10 px-3 py-2 font-semibold text-red-300">Nao e o mesmo</button></div>
                </div>
              ) : queue === 'classified' ? (
                <div className="mt-3 flex items-center gap-2 text-sm"><CheckCircle2 size={15} className="text-emerald-400" /><span className="text-[#e8eaf0]">{tx.category_name}</span>{tx.subcategory_name && <span className="text-[#8b90a4]">/ {tx.subcategory_name}</span>}<span className="ml-auto text-xs text-[#5a5f73]">{tx.history_match_confirmed ? 'Vinculado' : `Classificado por ${tx.classified_by || 'usuario'}`}</span></div>
              ) : (
                <div className="mt-4 space-y-3">
                  {txSuggestions.length > 0 ? <div className="grid gap-2 md:grid-cols-3">{txSuggestions.slice(0, 3).map((suggestion, suggestionIndex) => <button key={`${tx.id}-${suggestion.category_id}`} onClick={() => patchDraft(tx.id, { category_id: suggestion.category_id, subcategory_id: '' })} className="rounded-lg p-3 text-left" style={{ background: draft.category_id === suggestion.category_id ? 'rgba(201,168,76,.15)' : 'rgba(255,255,255,.025)', border: `1px solid ${draft.category_id === suggestion.category_id ? 'rgba(201,168,76,.45)' : 'rgba(255,255,255,.07)'}` }}><div className="flex items-center gap-2"><span className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] text-[#8b90a4]">{suggestionIndex + 1}</span><strong className="text-sm text-[#e8eaf0]">{suggestion.category_name}</strong><span className="ml-auto text-sm font-bold text-[#e8c96e]">{(suggestion.confidence ?? suggestion.category_probability ?? 0).toFixed(0)}%</span></div><p className="mt-2 text-[11px] text-[#8b90a4]">{suggestion.history_evidence} historico · {suggestion.transaction_evidence} classificados</p></button>)}</div> : <p className="rounded-lg bg-white/[.025] p-3 text-sm text-[#8b90a4]">{queue === 'waiting' ? 'Este lancamento ainda nao foi calculado.' : queue === 'dismissed' ? 'As sugestoes deste lancamento foram ignoradas.' : 'Nenhuma evidencia atingiu o minimo para sugerir uma categoria.'}</p>}

                  <div className="grid gap-2 md:grid-cols-3">
                    <select value={draft.category_id} onChange={event => patchDraft(tx.id, { category_id: event.target.value, subcategory_id: '' })} className="h-10 rounded-md px-3 text-sm text-[#e8eaf0]" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,.10)' }}><option value="">Escolha a categoria</option>{categories.filter(category => category.type === tx.type).map(category => <option key={category.id} value={category.id}>{category.name}</option>)}</select>
                    <select value={draft.subcategory_id} onChange={event => patchDraft(tx.id, { subcategory_id: event.target.value })} disabled={!draft.category_id} className="h-10 rounded-md px-3 text-sm text-[#e8eaf0] disabled:opacity-40" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,.10)' }}><option value="">Sem subcategoria</option>{(chosenSuggestion?.subcategories || []).map(subcategory => <option key={`suggested-${subcategory.subcategory_id}`} value={subcategory.subcategory_id}>★ {subcategory.subcategory_name} ({subcategory.confidence.toFixed(0)}%)</option>)}{subcategories.filter(subcategory => !(chosenSuggestion?.subcategories || []).some(candidate => candidate.subcategory_id === subcategory.id)).map(subcategory => <option key={subcategory.id} value={subcategory.id}>{subcategory.name}</option>)}</select>
                    <input value={draft.notes} onChange={event => patchDraft(tx.id, { notes: event.target.value })} placeholder="Observacao opcional" className="h-10 rounded-md px-3 text-sm text-[#e8eaf0]" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,.10)' }} />
                  </div>
                  {!!chosenSuggestion?.subcategories?.length && <div className="flex flex-wrap gap-2"><span className="text-xs text-[#8b90a4]">Subcategorias sugeridas:</span>{chosenSuggestion.subcategories.map(subcategory => <button key={subcategory.subcategory_id} onClick={() => patchDraft(tx.id, { subcategory_id: subcategory.subcategory_id })} className="rounded px-2 py-1 text-xs" style={{ background: draft.subcategory_id === subcategory.subcategory_id ? 'rgba(96,165,250,.18)' : 'rgba(255,255,255,.04)', color: '#93c5fd' }}>{subcategory.subcategory_name} {subcategory.confidence.toFixed(0)}%</button>)}</div>}
                  <div className="flex flex-wrap items-center gap-2"><button onClick={() => applyOne(tx)} disabled={!draft.category_id || busyId === tx.id} className="rounded-md bg-emerald-500/15 px-4 py-2 text-sm font-semibold text-emerald-300 disabled:opacity-40">Salvar e proximo <span className="ml-1 text-[10px] opacity-50">Enter</span></button>{similarCount > 1 && <button onClick={() => applySimilar(tx)} disabled={!draft.category_id || busyId === tx.id} className="rounded-md bg-blue-500/10 px-3 py-2 text-sm font-semibold text-blue-300 disabled:opacity-40">Aplicar a {similarCount} semelhantes</button>}<button onClick={() => dismiss(tx)} disabled={busyId === tx.id} className="rounded-md px-3 py-2 text-sm text-[#8b90a4] hover:bg-white/5">Ignorar sugestoes</button>{index === 0 && txSuggestions.length > 0 && <span className="ml-auto text-[11px] text-[#5a5f73]">Atalhos: 1, 2, 3 e Enter</span>}</div>
                </div>
              )}
            </article>
          )
        })}
      </div>}

      <div className="flex items-center justify-center gap-3"><button onClick={() => loadQueue(page - 1)} disabled={page <= 1 || loading} className="rounded-md p-2 text-[#8b90a4] disabled:opacity-30" style={{ background: '#1a1e28' }}><ChevronLeft size={16} /></button><span className="text-xs text-[#8b90a4]">Pagina {page} de {totalPages}</span><button onClick={() => loadQueue(page + 1)} disabled={page >= totalPages || loading} className="rounded-md p-2 text-[#8b90a4] disabled:opacity-30" style={{ background: '#1a1e28' }}><ChevronRight size={16} /></button></div>
    </div>
  )
}
