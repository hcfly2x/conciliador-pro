'use client'
import { Link2, Lock, LockOpen } from 'lucide-react'
import { isAdmin } from '@/lib/api'
import { formatCurrencyAbs, formatDate } from '@/lib/utils'
import type { Transaction } from '@/types'
import type { useTransactionTable } from './useTransactionTable'

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

export function TransactionGrid({ model }: { model: ReturnType<typeof useTransactionTable> }) {
  const { selected, txs, toggleAll, toggleOne, toggleSort, SortIcon, loading, rowSuggestions, rowDraft, suggestionErrors, suggestionsLoading, rowSuggestionStates, patchRowDraft, categories, subcategories, setRowDraft, saveRow, savingRow, setLinkReviewId, handleUnlock, totalPages, page, total, load } = model
  const thCls = 'px-3 py-2.5 text-left text-[11px] font-semibold text-[#5a5f73] uppercase tracking-widest select-none cursor-pointer hover:text-[#8b90a4] transition-colors'
  return (
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
                          {tx.transaction_method || 'other'} Â· {tx.merchant_norm}
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
  )
}
