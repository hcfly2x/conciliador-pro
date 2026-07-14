'use client'
import { useState, useEffect } from 'react'
import { useStore } from '@/store/app'
import { getReportSummary, getReportByCategory, getReportMonthly } from '@/lib/api'
import type { ReportSummary, CategoryReport, MonthlyReport } from '@/types'

function fmtAbs(v: number) { return 'R$ ' + Math.abs(v).toLocaleString('pt-BR', { minimumFractionDigits: 2 }) }
function fmt(v: number) { return (v < 0 ? '-' : '') + 'R$ ' + Math.abs(v).toLocaleString('pt-BR', { minimumFractionDigits: 2 }) }

export default function ReportsPage() {
  const { months } = useStore()
  const [month, setMonth] = useState('')
  const [type, setType] = useState<'expense'|'income'>('expense')
  const [summary, setSummary] = useState<ReportSummary|null>(null)
  const [bycat, setBycat] = useState<CategoryReport[]>([])
  const [monthly, setMonthly] = useState<MonthlyReport[]>([])

  useEffect(() => {
    getReportSummary(month ? { competence_month: month } : {}).then(setSummary)
    getReportByCategory({ type, ...(month && { competence_month: month }) }).then(setBycat)
    getReportMonthly().then(setMonthly)
  }, [month, type])

  const maxCat = Math.max(...bycat.map(c => Math.abs(c.total)), 1)
  const maxMonth = Math.max(...monthly.map(m => Math.abs(m.expense)), 1)

  return (
    <div>
      <div className="flex gap-3 mb-6 items-center">
        <select className="h-9 px-3 rounded-md text-sm text-[#8b90a4] outline-none" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,0.07)' }} value={month} onChange={e => setMonth(e.target.value)}>
          <option value="">Todos os meses</option>
          {months.map(m => <option key={m} value={m}>{m}</option>)}
        </select>
        {(['expense','income'] as const).map(t => (
          <button key={t} onClick={() => setType(t)} className="px-4 h-9 rounded-full text-sm transition-all" style={{ background: type===t ? 'rgba(201,168,76,0.15)' : '#13161d', border: `1px solid ${type===t ? '#c9a84c' : 'rgba(255,255,255,0.07)'}`, color: type===t ? '#e8c96e' : '#8b90a4' }}>
            {t==='expense' ? 'Despesas' : 'Receitas'}
          </button>
        ))}
      </div>

      {summary && (
        <div className="grid grid-cols-4 gap-3 mb-6">
          {[
            { label: 'Lançamentos', value: summary.total_transactions.toLocaleString(), color: '#e8c96e' },
            { label: 'Saídas', value: fmtAbs(summary.total_expense), color: '#f87171' },
            { label: 'Entradas', value: fmt(summary.total_income), color: '#3ecf8e' },
            { label: 'Saldo', value: fmt(summary.balance), color: summary.balance >= 0 ? '#3ecf8e' : '#f87171' },
          ].map(s => (
            <div key={s.label} className="rounded-lg p-4" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,0.07)' }}>
              <p className="text-[11px] text-[#5a5f73] uppercase tracking-widest font-semibold mb-2">{s.label}</p>
              <p className="font-display font-bold text-lg leading-none" style={{ color: s.color }}>{s.value}</p>
            </div>
          ))}
        </div>
      )}

      <div className="grid grid-cols-2 gap-4">
        <div className="rounded-xl p-5" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,0.07)' }}>
          <h3 className="font-display font-bold text-[14px] text-[#e8eaf0] mb-4">Por categoria</h3>
          <div className="space-y-3">
            {bycat.slice(0,12).map(c => (
              <div key={c.category_id||'none'}>
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2 min-w-0">
                    {c.category_color && <span className="w-2 h-2 rounded-sm flex-shrink-0" style={{ background: c.category_color }} />}
                    <span className="text-xs text-[#e8eaf0] truncate">{c.category_name}</span>
                    <span className="text-[10px] text-[#5a5f73] flex-shrink-0">({c.count})</span>
                  </div>
                  <span className="text-xs font-semibold font-mono-custom ml-2 flex-shrink-0" style={{ color: type==='expense'?'#f87171':'#3ecf8e' }}>{fmtAbs(c.total)}</span>
                </div>
                <div className="h-1.5 rounded-full overflow-hidden" style={{ background: '#1a1e28' }}>
                  <div className="h-full rounded-full transition-all duration-500" style={{ width: `${(Math.abs(c.total)/maxCat)*100}%`, background: c.category_color||'#c9a84c' }} />
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-xl p-5" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,0.07)' }}>
          <h3 className="font-display font-bold text-[14px] text-[#e8eaf0] mb-4">Evolução mensal</h3>
          <div className="space-y-3">
            {monthly.map(m => (
              <div key={m.month}>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-mono-custom text-[#8b90a4]">{m.month}</span>
                  <div className="flex gap-3">
                    <span className="text-[11px] font-mono-custom text-[#f87171]">{fmtAbs(m.expense)}</span>
                    <span className="text-[11px] font-mono-custom text-[#3ecf8e]">{fmt(m.income)}</span>
                  </div>
                </div>
                <div className="h-1.5 rounded-full overflow-hidden" style={{ background: '#1a1e28' }}>
                  <div className="h-full rounded-full" style={{ width: `${(Math.abs(m.expense)/maxMonth)*100}%`, background: '#f87171' }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
