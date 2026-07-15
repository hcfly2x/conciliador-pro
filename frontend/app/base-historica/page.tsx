'use client'
import { useCallback, useEffect, useState } from 'react'
import { Search, RefreshCw } from 'lucide-react'
import { getHistory, getRecalculationJob, recalculateProbabilities, unlinkHistoricalMatch, type HistoryItem, type RecalculationJob } from '@/lib/api'
import { useStore } from '@/store/app'
import { formatCurrencyAbs, formatDate } from '@/lib/utils'

export default function Page() {
  const { accounts, categories, subcategories, addToast } = useStore()
  const [items, setItems] = useState<HistoryItem[]>([])
  const [total, setTotal] = useState(0)
  const [totalLinked, setTotalLinked] = useState(0)
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [accountFilter, setAccountFilter] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const [subcategoryFilter, setSubcategoryFilter] = useState('')
  const [linkedFilter, setLinkedFilter] = useState('')
  const [sheetFilter, setSheetFilter] = useState<'saidas' | 'entradas' | 'helcio_smartek'>('saidas')
  const [sortBy, setSortBy] = useState('date')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [unlinkMenu, setUnlinkMenu] = useState<{ txId: string; x: number; y: number } | null>(null)
  const [recalcJob, setRecalcJob] = useState<RecalculationJob | null>(null)

  useEffect(() => {
    if (!recalcJob?.id || !['queued', 'running'].includes(recalcJob.status)) return
    const timer = setTimeout(async () => {
      try { setRecalcJob(await getRecalculationJob(recalcJob.id)) } catch { /* tenta novamente no proximo ciclo */ }
    }, 2000)
    return () => clearTimeout(timer)
  }, [recalcJob])

  async function startRecalculation() {
    try {
      const response = await recalculateProbabilities()
      setRecalcJob({ id: response.job_id, status: 'queued', processed: 0, total: 0, updated: 0, error: '' })
    } catch {
      addToast('Erro ao iniciar o calculo de sugestoes', 'err')
    }
  }

  const load = useCallback(async (p = 1) => {
    setLoading(true)
    try {
      const data = await getHistory({
        page: p,
        page_size: pageSize,
        ...(search && { search }),
        ...(typeFilter && { type: typeFilter }),
        ...(accountFilter && { account_id: accountFilter }),
        ...(categoryFilter && { category_id: categoryFilter }),
        ...(subcategoryFilter && { subcategory_id: subcategoryFilter }),
        ...(linkedFilter && { linked: linkedFilter }),
        sheet: sheetFilter,
        sort_by: sortBy,
        sort_order: sortOrder,
      })
      setItems(data.items)
      setTotal(data.total)
      setTotalLinked(data.total_linked ?? 0)
      setPage(data.page)
      setTotalPages(data.total_pages)
    } finally {
      setLoading(false)
    }
  }, [accountFilter, categoryFilter, linkedFilter, pageSize, search, sheetFilter, sortBy, sortOrder, subcategoryFilter, typeFilter])

  useEffect(() => { load(1) }, [load])
  useEffect(() => {
    if (!unlinkMenu) return
    function close() { setUnlinkMenu(null) }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') close()
    }
    window.addEventListener('click', close)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('click', close)
      window.removeEventListener('keydown', onKey)
    }
  }, [unlinkMenu])

  function toggleSort(col: string) {
    if (sortBy === col) setSortOrder(o => o === 'asc' ? 'desc' : 'asc')
    else { setSortBy(col); setSortOrder('desc') }
  }

  function sortMark(col: string) {
    if (sortBy !== col) return '↕'
    return sortOrder === 'asc' ? '↑' : '↓'
  }

  async function handleUnlinkHistory(txId: string) {
    try {
      await unlinkHistoricalMatch(txId)
      setUnlinkMenu(null)
      addToast('Vinculo historico removido')
      load(page)
    } catch {
      addToast('Erro ao desvincular', 'err')
    }
  }

  const th = 'px-3 py-2.5 text-left text-[11px] font-semibold text-[#5a5f73] uppercase tracking-widest cursor-pointer hover:text-[#8b90a4]'
  const sheetTabs = [
    { value: 'saidas', label: 'Saidas' },
    { value: 'entradas', label: 'Entradas' },
    { value: 'helcio_smartek', label: 'Helcio Smartek' },
  ] as const

  return (
    <div>
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-bold text-[#e8eaf0]">Base Historica</h1>
          <p className="text-sm text-[#8b90a4] mt-1">Consulta somente leitura usada pelo motor de probabilidades.</p>
        </div>
        <button onClick={startRecalculation} disabled={recalcJob?.status === 'queued' || recalcJob?.status === 'running'} className="h-10 rounded-lg px-4 text-sm font-semibold disabled:opacity-50" style={{ background: '#c9a84c', color: '#0d0f14' }}>
          {recalcJob?.status === 'queued' || recalcJob?.status === 'running' ? 'Calculando...' : 'Calcular sugestoes'}
        </button>
      </div>

      {recalcJob && (
        <div className="mb-5 rounded-xl p-4" style={{ background: '#13161d', border: '1px solid rgba(201,168,76,0.25)' }}>
          <p className="text-sm text-[#e8eaf0]">
            {recalcJob.status === 'queued' && 'Calculo aguardando inicio...'}
            {recalcJob.status === 'running' && `Analisando ${recalcJob.processed} de ${recalcJob.total} lancamentos...`}
            {recalcJob.status === 'completed' && `Calculo concluido: ${recalcJob.updated} sugestoes atualizadas.`}
            {recalcJob.status === 'failed' && `Falha no calculo: ${recalcJob.error || 'erro interno'}`}
          </p>
          {recalcJob.total > 0 && (
            <div className="mt-2 h-2 overflow-hidden rounded bg-[#1a1e28]">
              <div className="h-full bg-[#c9a84c] transition-all" style={{ width: `${Math.min(100, (recalcJob.processed / recalcJob.total) * 100)}%` }} />
            </div>
          )}
        </div>
      )}

      <div className="flex gap-2 mb-4">
        {sheetTabs.map(tab => (
          <button
            key={tab.value}
            type="button"
            onClick={() => {
              setSheetFilter(tab.value)
              setPage(1)
            }}
            className="h-9 px-3 rounded-md text-sm font-semibold transition-all"
            style={{
              background: sheetFilter === tab.value ? 'rgba(201,168,76,0.18)' : '#1a1e28',
              border: `1px solid ${sheetFilter === tab.value ? 'rgba(201,168,76,0.45)' : 'rgba(255,255,255,0.07)'}`,
              color: sheetFilter === tab.value ? '#e8c96e' : '#8b90a4',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-4 gap-3 mb-5">
        <div className="rounded-lg p-4" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,0.07)' }}>
          <p className="text-[11px] text-[#5a5f73] uppercase tracking-widest font-semibold mb-1.5">Registros</p>
          <p className="font-display font-bold text-xl leading-none text-[#e8c96e]">{total.toLocaleString('pt-BR')}</p>
        </div>
        <div className="rounded-lg p-4" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,0.07)' }}>
          <p className="text-[11px] text-[#5a5f73] uppercase tracking-widest font-semibold mb-1.5">Vinculados</p>
          <p className="font-display font-bold text-xl leading-none text-[#3ecf8e]">{totalLinked.toLocaleString('pt-BR')}</p>
        </div>
        <div className="rounded-lg p-4" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,0.07)' }}>
          <p className="text-[11px] text-[#5a5f73] uppercase tracking-widest font-semibold mb-1.5">Pagina</p>
          <p className="font-display font-bold text-xl leading-none text-[#60a5fa]">{page} / {totalPages}</p>
        </div>
        <div className="rounded-lg p-4" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,0.07)' }}>
          <p className="text-[11px] text-[#5a5f73] uppercase tracking-widest font-semibold mb-1.5">Modo</p>
          <p className="font-display font-bold text-xl leading-none text-[#3ecf8e]">Somente leitura</p>
        </div>
      </div>

      <div className="flex gap-2 mb-4 flex-wrap items-center">
        <div className="relative">
          <Search size={12} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#5a5f73]" />
          <input className="h-8 pl-8 pr-3 rounded-md text-sm text-[#e8eaf0] placeholder-[#5a5f73] outline-none w-64" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.07)' }} placeholder="Buscar descricao..." value={search} onChange={e => setSearch(e.target.value)} />
        </div>
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
        <select className="h-8 px-2 rounded-md text-sm text-[#8b90a4] outline-none" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.07)' }} value={linkedFilter} onChange={e => setLinkedFilter(e.target.value)}>
          <option value="">Todos vinculos</option>
          <option value="true">Ja vinculados</option>
          <option value="false">Nao vinculados</option>
        </select>
        <div className="flex items-center gap-1.5 ml-auto">
          <span className="text-[11px] text-[#5a5f73]">Linhas:</span>
          {[25, 50, 100, 200].map(n => (
            <button key={n} onClick={() => setPageSize(n)} className="h-7 px-2.5 rounded text-[11px]" style={{ background: pageSize === n ? 'rgba(201,168,76,0.18)' : '#1a1e28', border: `1px solid ${pageSize === n ? 'rgba(201,168,76,0.4)' : 'rgba(255,255,255,0.07)'}`, color: pageSize === n ? '#e8c96e' : '#5a5f73' }}>{n}</button>
          ))}
        </div>
        <button onClick={() => load(page)} className="h-8 w-8 flex items-center justify-center rounded-md text-[#5a5f73]" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.07)' }}><RefreshCw size={13} /></button>
      </div>

      <div className="rounded-xl overflow-hidden" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,0.07)' }}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr style={{ background: '#1a1e28', borderBottom: '1px solid rgba(255,255,255,0.07)' }}>
                <th className={th} onClick={() => toggleSort('date')}>Data <span className="text-[10px]">{sortMark('date')}</span></th>
                <th className={th} onClick={() => toggleSort('description')}>Descricao <span className="text-[10px]">{sortMark('description')}</span></th>
                <th className={`${th} text-right`} onClick={() => toggleSort('amount')}>Valor <span className="text-[10px]">{sortMark('amount')}</span></th>
                <th className={th} onClick={() => toggleSort('type')}>Tipo <span className="text-[10px]">{sortMark('type')}</span></th>
                <th className={th} onClick={() => toggleSort('account')}>Conta <span className="text-[10px]">{sortMark('account')}</span></th>
                <th className={th} onClick={() => toggleSort('category')}>Categoria <span className="text-[10px]">{sortMark('category')}</span></th>
                <th className={th} onClick={() => toggleSort('subcategory')}>Subcategoria <span className="text-[10px]">{sortMark('subcategory')}</span></th>
                <th className={th} onClick={() => toggleSort('linked')}>Vinculado <span className="text-[10px]">{sortMark('linked')}</span></th>
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan={8} className="text-center py-12 text-[#5a5f73]">Carregando...</td></tr>}
              {!loading && items.length === 0 && <tr><td colSpan={8} className="text-center py-12 text-[#5a5f73]">Nenhum registro encontrado</td></tr>}
              {!loading && items.map(item => (
                <tr key={item.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                  <td className="px-3 py-2.5 text-xs text-[#8b90a4] whitespace-nowrap">{item.date ? formatDate(item.date) : '-'}</td>
                  <td className="px-3 py-2.5 max-w-[360px]"><span className="block truncate text-[#e8eaf0]" title={item.description}>{item.description}</span></td>
                  <td className="px-3 py-2.5 text-right whitespace-nowrap"><span style={{ color: item.type === 'income' ? '#3ecf8e' : '#f87171' }}>{item.type === 'income' ? '+' : '-'}{formatCurrencyAbs(item.amount)}</span></td>
                  <td className="px-3 py-2.5 text-[#8b90a4] text-xs">{item.type === 'income' ? 'Receita' : 'Despesa'}</td>
                  <td className="px-3 py-2.5 text-[#8b90a4] text-xs">{item.account_name || '-'}</td>
                  <td className="px-3 py-2.5"><span className="text-[11px] font-semibold px-2 py-0.5 rounded" style={{ background: item.category_color || '#223044', color: '#fff' }}>{item.category_name}</span></td>
                  <td className="px-3 py-2.5 text-[#8b90a4] text-xs">{item.subcategory_name || '-'}</td>
                  <td className="px-3 py-2.5 min-w-[170px]">
                    {item.linked_tx_id ? (
                      <div>
                        <span
                          onContextMenu={(e) => {
                            e.preventDefault()
                            if (item.linked_tx_id) setUnlinkMenu({ txId: item.linked_tx_id, x: e.clientX, y: e.clientY })
                          }}
                          className="inline-flex rounded px-1.5 py-0.5 text-[10px] font-semibold mb-0.5 cursor-context-menu"
                          title="Clique com o botao auxiliar para desvincular"
                          style={{ background: 'rgba(62,207,142,0.10)', color: '#86efac', border: '1px solid rgba(62,207,142,0.22)' }}
                        >
                          vinculado
                        </span>
                        <p className="text-[11px] text-[#5a5f73] mt-1 truncate max-w-[190px]" title={item.linked_tx_description || ''}>
                          {item.linked_tx_description || '-'}
                        </p>
                        <p className="text-[10px] text-[#3a3f50]">
                          {item.linked_tx_date ? formatDate(item.linked_tx_date) : '-'} · {formatCurrencyAbs(item.linked_tx_amount ?? 0)}
                        </p>
                      </div>
                    ) : (
                      <span className="text-xs text-[#3a3f50]">-</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {totalPages > 1 && (
          <div className="flex items-center justify-between px-4 py-3" style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}>
            <span className="text-[11px] text-[#5a5f73] font-mono">Pagina {page} de {totalPages} - {total.toLocaleString('pt-BR')} registros</span>
            <div className="flex items-center gap-1">
              <button disabled={page <= 1} onClick={() => load(1)} className="h-7 w-7 rounded text-[11px] disabled:opacity-30" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.07)', color: '#8b90a4' }}>{'<<'}</button>
              <button disabled={page <= 1} onClick={() => load(page - 1)} className="h-7 px-2.5 rounded text-[11px] disabled:opacity-30" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.07)', color: '#8b90a4' }}>Ant</button>
              <button disabled={page >= totalPages} onClick={() => load(page + 1)} className="h-7 px-2.5 rounded text-[11px] disabled:opacity-30" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.07)', color: '#8b90a4' }}>Prox</button>
              <button disabled={page >= totalPages} onClick={() => load(totalPages)} className="h-7 w-7 rounded text-[11px] disabled:opacity-30" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.07)', color: '#8b90a4' }}>{'>>'}</button>
            </div>
          </div>
        )}
      </div>
      {unlinkMenu && (
        <div
          className="fixed z-50 rounded-lg p-1 shadow-xl"
          style={{ left: unlinkMenu.x, top: unlinkMenu.y, background: '#13161d', border: '1px solid rgba(255,255,255,0.12)' }}
          onClick={(e) => e.stopPropagation()}
        >
          <button
            type="button"
            onClick={() => handleUnlinkHistory(unlinkMenu.txId)}
            className="block w-full rounded-md px-3 py-2 text-left text-xs font-semibold text-[#fca5a5] hover:bg-[#1a1e28]"
          >
            Desvincular
          </button>
        </div>
      )}
    </div>
  )
}
