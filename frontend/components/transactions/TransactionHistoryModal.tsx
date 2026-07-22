'use client'
import { X } from 'lucide-react'
import { formatCurrencyAbs, formatDate, formatInstallmentLinkExplanation } from '@/lib/utils'
import type { useTransactionTable } from './useTransactionTable'

export function TransactionHistoryModal({ model }: { model: ReturnType<typeof useTransactionTable> }) {
  const { linkReviewId, txs, batchReviewIds, setLinkReviewId, reviewingLink, handleHistoryLink } = model
  if (!linkReviewId) return null
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
            <p className="text-xs font-semibold uppercase tracking-widest text-[#93c5fd]">
              {batchReviewIds.includes(tx.id) ? `Revisao manual do lote Â· ${batchReviewIds.length} restante(s)` : 'Possivel vinculo historico'}
            </p>
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
            {formatInstallmentLinkExplanation(tx)}
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
}
