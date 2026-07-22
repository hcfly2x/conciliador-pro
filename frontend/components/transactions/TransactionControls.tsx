'use client'
import { RefreshCw, Search, X } from 'lucide-react'
import type { useTransactionTable } from './useTransactionTable'

const TAG_OPTIONS = [
  { value: 'investimento', label: 'Investimento' },
  { value: 'tax', label: 'Tax' },
  { value: 'rendimento', label: 'Rendimento' },
  { value: 'fatura', label: 'Fatura' },
  { value: 'cartao_debito', label: 'Cartao debito' },
  { value: 'non_count', label: 'Non count' },
  { value: '__empty__', label: 'Sem tag' },
]

export function TransactionControls({ model }: { model: ReturnType<typeof useTransactionTable> }) {
  const { total, summary, search, setSearch, months, monthFilter, setMonthFilter, typeFilter, setTypeFilter, accounts, accountFilter, setAccountFilter, categories, categoryFilter, setCategoryFilter, subcategories, subcategoryFilter, setSubcategoryFilter, installmentFilter, setInstallmentFilter, pageSize, setPageSize, load, page, dateFrom, setDateFrom, dateTo, setDateTo, tagMode, setTagMode, tagFilters, setTagFilters, selected, bulkCatId, setBulkCatId, bulkSubId, setBulkSubId, handleBulkClassify, linkingBatch, handlePrepareHistoricalLinks, moveTargetLedgerId, handleMoveToLedger, moveTargetLedgerName, bulkLedgerId, setBulkLedgerId, defaultLedgerId, ledgers, linkBatchLogs, linkBatchProgress, setLinkBatchLogs, batchReviewIds, linkReviewId, setLinkReviewId, toggleTagFilter } = model
  const progressPercent = linkBatchProgress?.total
    ? Math.round((linkBatchProgress.completed / linkBatchProgress.total) * 100)
    : 0
  return (
    <>
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
        <div data-testid="history-link-batch-progress" className="mb-3 rounded-lg px-4 py-3" style={{ background: '#0d0f14', border: '1px solid rgba(96,165,250,0.22)' }}>
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-semibold text-[#93c5fd]">Progresso do vinculo em lote</span>
            {!linkingBatch && <button type="button" onClick={() => setLinkBatchLogs([])} className="text-[#5a5f73] hover:text-[#e8eaf0]" title="Fechar logs"><X size={14} /></button>}
          </div>
          {linkBatchProgress && (
            <>
              <div className="mb-2 flex items-center justify-between text-xs">
                <span className="font-medium text-[#e8eaf0]">
                  {linkBatchProgress.status === 'completed'
                    ? 'Processamento concluido'
                    : linkBatchProgress.status === 'error'
                      ? 'Processamento interrompido'
                      : `Processando bloco ${linkBatchProgress.currentBlock} de ${linkBatchProgress.blockCount}`}
                </span>
                <strong className="text-[#93c5fd]">{linkBatchProgress.completed}/{linkBatchProgress.total} · {progressPercent}%</strong>
              </div>
              <div role="progressbar" aria-label="Progresso do vinculo" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progressPercent} className="h-2 overflow-hidden rounded-full bg-white/[.06]">
                <div className="h-full rounded-full bg-[#60a5fa] transition-all duration-300" style={{ width: `${progressPercent}%` }} />
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2 text-center sm:grid-cols-5">
                {[
                  ['Confirmados', linkBatchProgress.matched, '#3ecf8e'],
                  ['Para revisar', linkBatchProgress.manualReview, '#fbbf24'],
                  ['Sem vinculo', linkBatchProgress.withoutMatch, '#8b90a4'],
                  ['Ignorados', linkBatchProgress.skipped, '#8b90a4'],
                  ['Falhas', linkBatchProgress.failed, '#f87171'],
                ].map(([label, value, color]) => (
                  <div key={String(label)} className="rounded-md bg-white/[.025] px-2 py-2">
                    <div className="text-lg font-bold" style={{ color: String(color) }}>{value}</div>
                    <div className="text-[10px] uppercase tracking-wide text-[#5a5f73]">{label}</div>
                  </div>
                ))}
              </div>
            </>
          )}
          <details className="mt-3 text-[11px] text-[#8b90a4]">
            <summary className="cursor-pointer select-none text-[#5a5f73] hover:text-[#8b90a4]">Ver detalhes tecnicos ({linkBatchLogs.length})</summary>
            <div className="mt-2 max-h-32 overflow-auto rounded bg-black/15 p-2 font-mono">
              {linkBatchLogs.map((entry, index) => <div key={`${entry.time}-${index}`}><span className="text-[#5a5f73]">{entry.time}</span> · {entry.message}</div>)}
            </div>
          </details>
          {batchReviewIds.length > 0 && !linkReviewId && (
            <button type="button" onClick={() => setLinkReviewId(batchReviewIds[0])} className="mt-3 h-8 rounded-md px-3 text-xs font-semibold" style={{ background: 'rgba(96,165,250,0.18)', border: '1px solid rgba(96,165,250,0.35)', color: '#93c5fd' }}>
              Continuar revisao manual ({batchReviewIds.length})
            </button>
          )}
        </div>
      )}

    </>
  )
}
