'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Check, Download, FileUp, RefreshCw, Search, Trash2, X } from 'lucide-react'
import {
  commitImportPreview,
  deleteCoverageFile,
  downloadDocument,
  dispenseCoverage,
  getCoverage,
  getCoverageFiles,
  previewImportFile,
  undoDispenseCoverage,
  type CoverageAccount,
  type CoverageFile,
  type CoverageResponse,
} from '@/lib/api'
import { formatCurrencyAbs } from '@/lib/utils'
import { useStore } from '@/store/app'

type SelectedCell = {
  accountId: string
  accountName: string
  yearMonth: string
}

function visibleFlags(flags?: string) {
  return (flags || '')
    .split(',')
    .map(flag => flag.trim())
    .filter(flag => flag && flag !== 'INSTALLMENT')
    .map(flag => ({
      CARD_PAYMENT: 'fatura',
      TAX: 'tax',
      INTER_ACCOUNT: 'movimentacao interna',
      CASHBACK: 'cashback',
      non_count: 'non_count',
    }[flag] || flag))
}

export default function ArquivosPage() {
  const { addToast, bumpRefresh } = useStore()
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [coverage, setCoverage] = useState<CoverageResponse | null>(null)
  const [selected, setSelected] = useState<SelectedCell | null>(null)
  const [files, setFiles] = useState<CoverageFile[]>([])
  const [query, setQuery] = useState('')
  const [year, setYear] = useState('2026')
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [preview, setPreview] = useState<any | null>(null)
  const [competenceMonth, setCompetenceMonth] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await getCoverage(Number(year))
      setCoverage(data)
    } finally {
      setLoading(false)
    }
  }, [year])

  useEffect(() => { load() }, [load])

  const years = useMemo(() => {
    return (coverage?.available_years ?? [2023, 2024, 2025, 2026])
      .map(String)
      .reverse()
  }, [coverage])

  const months = useMemo(() => {
    return coverage?.months ?? []
  }, [coverage])

  const accounts = useMemo(() => {
    const list = Object.values(coverage?.matrix ?? {})
    const needle = query.trim().toLowerCase()
    if (!needle) return list
    return list.filter(a => a.name.toLowerCase().includes(needle))
  }, [coverage, query])

  async function selectCell(account: CoverageAccount, yearMonth: string) {
    const next = { accountId: account.id, accountName: account.name, yearMonth }
    setSelected(next)
    setPreview(null)
    setCompetenceMonth(yearMonth.replace('/', '-'))
    const data = await getCoverageFiles(account.id, yearMonth)
    setFiles(data.files)
  }

  async function markDispensed() {
    if (!selected) return
    setBusy(true)
    try {
      await dispenseCoverage(selected.accountId, selected.yearMonth, 'Dispensado pelo usuario')
      addToast('Mes dispensado no controle de arquivos')
      await load()
      await selectCell({ id: selected.accountId, name: selected.accountName } as CoverageAccount, selected.yearMonth)
    } finally {
      setBusy(false)
    }
  }

  async function undoDispensed() {
    if (!selected) return
    setBusy(true)
    try {
      await undoDispenseCoverage(selected.accountId, selected.yearMonth)
      addToast('Dispensa removida')
      await load()
      await selectCell({ id: selected.accountId, name: selected.accountName } as CoverageAccount, selected.yearMonth)
    } finally {
      setBusy(false)
    }
  }

  async function onFileChange(file?: File) {
    if (!file || !selected) return
    setBusy(true)
    try {
      const data = await previewImportFile(file, selected.accountId)
      setPreview(data)
      const suggested = String(data.import_meta?.suggested_competence_month || selected.yearMonth || '')
      setCompetenceMonth((suggested || selected.yearMonth).replace('/', '-'))
      addToast('Pre-validacao concluida')
    } catch (err: any) {
      addToast(err?.detail || 'Erro ao analisar arquivo', 'err')
    } finally {
      setBusy(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  async function commitPreview() {
    if (!preview) return
    setBusy(true)
    try {
      const result = await commitImportPreview(preview.preview_id, true, competenceMonth.replace('-', '/'))
      addToast(`${result.total_inserted} lancamentos importados`)
      setPreview(null)
      bumpRefresh()
      await load()
      if (selected) await selectCell({ id: selected.accountId, name: selected.accountName } as CoverageAccount, selected.yearMonth)
    } catch (err: any) {
      addToast(err?.detail || 'Erro ao importar arquivo', 'err')
    } finally {
      setBusy(false)
    }
  }

  async function removeFile(file: CoverageFile) {
    if (!selected) return
    const ok = window.confirm(`Remover este arquivo do cofre?\n\n${file.filename}`)
    if (!ok) return
    setBusy(true)
    try {
      const result = await deleteCoverageFile(file.path)
      const txMsg = result.deleted_transactions > 0 ? ` e ${result.deleted_transactions} lancamentos` : ''
      addToast(`Arquivo removido${txMsg}`)
      bumpRefresh()
      await load()
      await selectCell({ id: selected.accountId, name: selected.accountName } as CoverageAccount, selected.yearMonth)
    } catch (err: any) {
      addToast(err?.detail || 'Erro ao remover arquivo', 'err')
    } finally {
      setBusy(false)
    }
  }

  const totals = useMemo(() => {
    let imported = 0, missing = 0, dispensed = 0
    Object.values(coverage?.matrix ?? {}).forEach(account => {
      Object.values(account.cells).forEach(cell => {
        if (cell.status === 'imported') imported += 1
        if (cell.status === 'missing') missing += 1
        if (cell.status === 'dispensed') dispensed += 1
      })
    })
    return { imported, missing, dispensed }
  }, [coverage])

  return (
    <div>
      <div className="mb-5 flex items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-bold text-[#e8eaf0]">Cofre de Arquivos</h1>
          <p className="text-sm text-[#8b90a4] mt-1">Controle fisico dos extratos e faturas por mes, conta e banco.</p>
        </div>
        <button onClick={load} className="h-9 px-3 rounded-md bg-[#1a1e28] text-[#cfd3df] text-sm flex items-center gap-2" disabled={loading}>
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Atualizar
        </button>
      </div>

      <div className="grid grid-cols-3 gap-3 mb-5">
        <Stat label="Importados" value={totals.imported} color="#3ecf8e" />
        <Stat label="Faltando" value={totals.missing} color="#ff6b6b" />
        <Stat label="Dispensados" value={totals.dispensed} color="#e8c96e" />
      </div>

      <div className="flex flex-wrap gap-2 mb-4">
        <div className="relative">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#5a5f73]" />
          <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Buscar conta..." className="h-9 w-64 rounded-md bg-[#151923] border border-white/10 pl-9 pr-3 text-sm text-[#e8eaf0] outline-none" />
        </div>
        <select value={year} onChange={e => { setYear(e.target.value); setSelected(null); setFiles([]); setPreview(null) }} className="h-9 rounded-md bg-[#151923] border border-white/10 px-3 text-sm text-[#cfd3df] outline-none">
          {years.map(y => <option key={y} value={y}>{y}</option>)}
        </select>
      </div>

      <div className="overflow-auto rounded-lg border border-white/10 mb-5">
        <table className="min-w-full text-sm">
          <thead className="bg-[#171b25]">
            <tr>
              <th className="sticky left-0 z-10 bg-[#171b25] px-3 py-3 text-left text-[11px] uppercase tracking-widest text-[#5a5f73] min-w-56">Conta</th>
              {months.map(month => <th key={month} className="px-2 py-3 text-center text-[11px] uppercase tracking-widest text-[#5a5f73] min-w-24">{month.slice(5)}</th>)}
            </tr>
          </thead>
          <tbody>
            {accounts.map(account => (
              <tr key={account.id} className="border-t border-white/10">
                <td className="sticky left-0 bg-[#11151d] px-3 py-2 font-medium text-[#dfe3ec]">{account.name}</td>
                {months.map(month => {
                  const cell = account.cells[month]
                  const active = selected?.accountId === account.id && selected.yearMonth === month
                  if (!cell) return <td key={month} className="px-2 py-2 text-center text-[#5a5f73]">-</td>
                  return (
                    <td key={month} className="px-2 py-2 text-center">
                      <button
                        onClick={() => selectCell(account, month)}
                        className={[
                          'h-8 w-full rounded-md border text-xs font-semibold',
                          cell.status === 'imported' ? 'bg-emerald-500/12 border-emerald-400/25 text-emerald-300' : '',
                          cell.status === 'missing' ? 'bg-red-500/10 border-red-400/20 text-red-300' : '',
                          cell.status === 'dispensed' ? 'bg-yellow-500/10 border-yellow-400/25 text-yellow-300' : '',
                          cell.status === 'future' ? 'bg-slate-500/10 border-slate-400/15 text-slate-500' : '',
                          active ? 'ring-1 ring-[#e8c96e]' : '',
                        ].join(' ')}
                        title={cell.reason || cell.status}
                      >
                        {cell.status === 'imported' ? cell.file_count : cell.status === 'dispensed' ? '-' : cell.status === 'future' ? '...' : '0'}
                      </button>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selected && (
        <div className="grid grid-cols-[1fr_1.2fr] gap-4">
          <section className="rounded-lg border border-white/10 bg-[#13161d] p-4">
            <p className="text-[11px] uppercase tracking-widest text-[#5a5f73] font-semibold mb-1">Celula selecionada</p>
            <h2 className="text-lg font-bold text-[#e8eaf0] mb-1">{selected.accountName}</h2>
            <p className="text-sm text-[#8b90a4] mb-4">{selected.yearMonth}</p>

            <div className="flex flex-wrap gap-2 mb-4">
              <input ref={inputRef} type="file" className="hidden" accept=".csv,.xls,.xlsx,.pdf" onChange={e => onFileChange(e.target.files?.[0])} />
              <button onClick={() => inputRef.current?.click()} disabled={busy} className="h-9 px-3 rounded-md bg-[#c9a84c] text-[#11151d] text-sm font-semibold flex items-center gap-2">
                <FileUp size={14} /> Analisar arquivo
              </button>
              <button onClick={markDispensed} disabled={busy} className="h-9 px-3 rounded-md bg-[#1a1e28] text-[#cfd3df] text-sm">Dispensar mes</button>
              <button onClick={undoDispensed} disabled={busy} className="h-9 px-3 rounded-md bg-[#1a1e28] text-[#cfd3df] text-sm">Reabrir</button>
            </div>

            <div className="space-y-2">
              {files.length === 0 && <p className="text-sm text-[#8b90a4]">Nenhum arquivo no cofre para esta celula.</p>}
              {files.map(file => (
                <div key={file.path} className="rounded-md bg-[#0d0f14] border border-white/10 px-3 py-2 flex items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-[#e8eaf0] break-all">{file.filename}</p>
                    <p className="text-xs text-[#5a5f73] break-all">{file.path.startsWith('db://') ? 'guardado no banco de dados' : file.path}</p>
                  </div>
                  {file.doc_id && (
                    <button
                      onClick={() => downloadDocument(file.doc_id!, file.filename)}
                      disabled={busy}
                      className="h-8 w-8 rounded-md bg-[#1a1e28] text-[#93c5fd] border border-white/10 flex items-center justify-center hover:bg-[#232838] disabled:opacity-50"
                      title="Baixar arquivo"
                    >
                      <Download size={14} />
                    </button>
                  )}
                  <button
                    onClick={() => removeFile(file)}
                    disabled={busy}
                    className="h-8 w-8 rounded-md bg-red-500/10 text-red-300 border border-red-400/20 flex items-center justify-center hover:bg-red-500/20 disabled:opacity-50"
                    title="Remover arquivo"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
            </div>
          </section>

          <section className="rounded-lg border border-white/10 bg-[#13161d] p-4">
            {!preview ? (
              <div className="h-full min-h-52 flex items-center justify-center text-sm text-[#8b90a4]">
                Analise um arquivo para ver totais, duplicados e linhas lidas.
              </div>
            ) : (
              <>
                <div className="flex items-start justify-between gap-3 mb-4">
                  <div>
                    <p className="text-[11px] uppercase tracking-widest text-[#5a5f73] font-semibold mb-1">Pre-validacao</p>
                    <h2 className="text-lg font-bold text-[#e8eaf0]">{preview.filename}</h2>
                    <p className="text-sm text-[#8b90a4]">{preview.detected_type} ({preview.detection_confidence}%)</p>
                    <label className="mt-2 flex items-center gap-2 text-sm text-[#8b90a4]">
                      Competência
                      <input
                        type="month"
                        value={competenceMonth}
                        onChange={e => setCompetenceMonth(e.target.value)}
                        className="h-8 rounded-md bg-[#1a1e28] border border-white/10 px-2 text-sm text-[#e8eaf0] outline-none"
                      />
                    </label>
                  </div>
                  <button onClick={commitPreview} disabled={busy || preview.quality_gate?.can_commit === false} className="h-9 px-3 rounded-md bg-emerald-500/15 text-emerald-300 text-sm font-semibold flex items-center gap-2 disabled:opacity-40">
                    <Check size={14} /> Confirmar
                  </button>
                </div>
                <div className="grid grid-cols-5 gap-2 mb-4">
                  <Mini label="Lidos" value={preview.total_parsed} />
                  <Mini label="Dup. banco" value={preview.duplicates_db} />
                  <Mini label="Dup. internos" value={preview.duplicates_internal} />
                  <Mini label="Novos" value={preview.new_records} />
                  <Mini label="Match hist." value={preview.historical_matches || 0} />
                </div>
                <div className="grid grid-cols-2 gap-2 mb-4">
                  <Mini label={`Entradas (${preview.income_count || 0})`} value={formatCurrencyAbs(preview.total_income || 0)} />
                  <Mini label={`Saidas (${preview.expense_count || 0})`} value={formatCurrencyAbs(preview.total_expense || 0)} />
                </div>
                {preview.quality_gate && !preview.quality_gate.can_commit && (
                  <div className="mb-4 rounded-md border border-red-400/30 bg-red-500/10 p-3">
                    <p className="text-sm font-semibold text-red-300">Importacao bloqueada</p>
                    {preview.quality_gate.critical_errors.map((item: string, index: number) => <p key={`${item}-${index}`} className="text-sm text-red-200">• {item}</p>)}
                  </div>
                )}
                {preview.balance_check?.ok === false && (
                  <div className="mb-4 rounded-md border border-red-400/25 bg-red-500/10 p-3">
                    <p className="text-sm font-semibold text-red-300">Conferencia de saldo nao bateu</p>
                    {preview.balance_check.message && <p className="mt-1 text-sm text-red-200">{preview.balance_check.message}</p>}
                  </div>
                )}
                {preview.rejected_lines && preview.rejected_lines.length > 0 && (
                  <details className="mb-4 rounded-md border border-red-400/25 bg-red-500/10 p-3" open>
                    <summary className="cursor-pointer text-sm font-semibold text-red-300">
                      {preview.rejected_lines.length} linha(s) candidata(s) nao foram importadas
                    </summary>
                    <div className="mt-3 max-h-40 overflow-auto space-y-2">
                      {preview.rejected_lines.map((line: string, idx: number) => (
                        <pre key={`${line}-${idx}`} className="whitespace-pre-wrap rounded bg-[#0d0f14] border border-red-400/15 p-2 text-xs text-red-200">
                          {line}
                        </pre>
                      ))}
                    </div>
                  </details>
                )}
                {preview.discarded_lines && preview.discarded_lines.length > 0 && (
                  <details className="mb-4 rounded-md border border-yellow-400/25 bg-yellow-500/10 p-3">
                    <summary className="cursor-pointer text-sm font-semibold text-yellow-300">
                      {preview.discarded_lines.length} linha(s) reconhecida(s) foram descartadas por regra
                    </summary>
                    <div className="mt-3 max-h-40 overflow-auto space-y-2">
                      {preview.discarded_lines.map((line: string, idx: number) => (
                        <pre key={`${line}-${idx}`} className="whitespace-pre-wrap rounded bg-[#0d0f14] border border-yellow-400/15 p-2 text-xs text-yellow-100">
                          {line}
                        </pre>
                      ))}
                    </div>
                  </details>
                )}
                <div className="max-h-80 overflow-auto border border-white/10 rounded-md">
                  {preview.rows.map((row: any, idx: number) => (
                    <div key={`${row.date}-${idx}`} className="grid grid-cols-[88px_1fr_110px_80px_80px] gap-3 border-b border-white/10 px-3 py-2 text-sm">
                      <span className="text-[#b7c4e8]">{row.date}</span>
                      <span className="text-[#e8eaf0] min-w-0">
                        <span className="block truncate">{row.description}</span>
                        {visibleFlags(row.flags).length > 0 && (
                          <span className="mt-1 flex flex-wrap gap-1">
                            {visibleFlags(row.flags).map(flag => (
                              <span key={flag} className="rounded px-1.5 py-0.5 text-[10px] font-semibold bg-sky-500/10 text-sky-300 border border-sky-400/20">
                                {flag}
                              </span>
                            ))}
                          </span>
                        )}
                      </span>
                      <span className={row.amount < 0 ? 'text-red-300' : 'text-emerald-300'}>{formatCurrencyAbs(row.amount)}</span>
                      <span className={row.duplicate_db ? 'text-yellow-300' : 'text-emerald-300'}>{row.duplicate_db ? 'Duplicado' : 'Novo'}</span>
                      <span className="text-sky-300">{row.match_probability ? `${Number(row.match_probability).toFixed(0)}%` : '-'}</span>
                    </div>
                  ))}
                </div>
                <button onClick={() => setPreview(null)} className="mt-3 h-8 px-3 rounded-md bg-[#1a1e28] text-[#cfd3df] text-sm flex items-center gap-2">
                  <X size={13} /> Fechar preview
                </button>
              </>
            )}
          </section>
        </div>
      )}
    </div>
  )
}

function Stat({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="rounded-lg border border-white/10 bg-[#13161d] p-4">
      <p className="text-[11px] text-[#5a5f73] uppercase tracking-widest font-semibold mb-1.5">{label}</p>
      <p className="font-display font-bold text-xl leading-none" style={{ color }}>{value.toLocaleString('pt-BR')}</p>
    </div>
  )
}

function Mini({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-md bg-[#0d0f14] border border-white/10 p-3">
      <p className="text-[10px] text-[#5a5f73] uppercase tracking-widest font-semibold mb-1">{label}</p>
      <p className="text-lg font-bold text-[#e8c96e]">{Number(value || 0).toLocaleString('pt-BR')}</p>
    </div>
  )
}
