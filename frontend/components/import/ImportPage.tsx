'use client'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Upload, CheckCircle, AlertCircle, FileText, ShieldCheck, Database } from 'lucide-react'
import { useStore } from '@/store/app'
import { commitImportPreview, getDocumentImportJob, previewImportFile, type DocumentImportJob } from '@/lib/api'
import type { ImportPreviewResult, ImportResult } from '@/types'

function fmtCurrency(v: number) {
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(v)
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
    .join(', ')
}

const ACTIVE_IMPORT_JOB_KEY = 'conciliador_active_import_job'

export default function ImportPage() {
  const { accounts, addToast, bumpRefresh } = useStore()
  const [drag, setDrag] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [accountId, setAccountId] = useState('')
  const [loading, setLoading] = useState(false)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [preview, setPreview] = useState<ImportPreviewResult | null>(null)
  const [competenceMonth, setCompetenceMonth] = useState('')
  const [result, setResult] = useState<ImportResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [importJob, setImportJob] = useState<DocumentImportJob | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const handledJobRef = useRef('')

  useEffect(() => {
    const jobId = window.sessionStorage.getItem(ACTIVE_IMPORT_JOB_KEY)
    if (!jobId) return
    setLoading(true)
    getDocumentImportJob(jobId)
      .then(setImportJob)
      .catch((error: any) => {
        if (error?.status === 404) {
          window.sessionStorage.removeItem(ACTIVE_IMPORT_JOB_KEY)
          setLoading(false)
          return
        }
        setImportJob({
          id: jobId, preview_id: '', filename: '', status: 'queued', result: null, error: '',
          phase: 'queued', processed: 0, total: 0, message: 'Retomando acompanhamento', logs: [],
          created_at: '', started_at: '', finished_at: '',
        })
      })
  }, [])

  useEffect(() => {
    if (!importJob?.id || !['queued', 'running'].includes(importJob.status)) return
    const timer = window.setTimeout(() => {
      getDocumentImportJob(importJob.id)
        .then(setImportJob)
        .catch(() => setImportJob(current => current ? { ...current } : current))
    }, 1500)
    return () => window.clearTimeout(timer)
  }, [importJob])

  useEffect(() => {
    if (!importJob?.id || !['completed', 'failed'].includes(importJob.status)) return
    if (handledJobRef.current === `${importJob.id}:${importJob.status}`) return
    handledJobRef.current = `${importJob.id}:${importJob.status}`
    window.sessionStorage.removeItem(ACTIVE_IMPORT_JOB_KEY)
    setLoading(false)
    if (importJob.status === 'completed' && importJob.result) {
      setResult(importJob.result)
      setPreview(null)
      setError(null)
      addToast(importJob.result.import_meta?.empty_statement_confirmed
        ? 'Extrato sem movimentações registrado no cofre'
        : `${importJob.result.total_inserted} lançamentos importados com sucesso`)
      bumpRefresh()
    } else {
      setError(importJob.error || 'Falha ao confirmar importação.')
      addToast('Erro ao confirmar importação', 'err')
    }
  }, [addToast, bumpRefresh, importJob])

  function resetAll() {
    setFile(null)
    setAccountId('')
    setPreview(null)
    setCompetenceMonth('')
    setResult(null)
    setError(null)
    setPreviewLoading(false)
    setLoading(false)
    setImportJob(null)
    window.sessionStorage.removeItem(ACTIVE_IMPORT_JOB_KEY)
  }

  function pickFile(f: File | undefined) {
    if (!f) return
    setFile(f)
    setAccountId('')
    setPreview(null)
    setCompetenceMonth('')
    setResult(null)
    setError(null)
  }

  const selectedAccount = useMemo(() => accounts.find(a => a.id === accountId), [accounts, accountId])

  async function handlePreview() {
    if (!file) return
    setPreviewLoading(true)
    setError(null)
    try {
      const data = await previewImportFile(file, accountId)
      setPreview(data)
      setAccountId(data.account_id)
      const suggested = String(data.import_meta?.suggested_competence_month || '')
      if (/^\d{4}\/\d{2}$/.test(suggested)) setCompetenceMonth(suggested.replace('/', '-'))
      addToast(`Prévia concluída: ${data.total_parsed} lançamentos lidos`)
    } catch (e: any) {
      setError(e?.detail || 'Falha ao gerar prévia do arquivo.')
      addToast('Erro na prévia de importação', 'err')
    } finally {
      setPreviewLoading(false)
    }
  }

  async function handleCommit() {
    if (!preview) return
    const [cy, cm] = competenceMonth.split('-')
    if (!cy || !cm) {
      setError('Selecione o mês e o ano de competência antes de confirmar a importação.')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const queued = await commitImportPreview(preview.preview_id, true, competenceMonth.replace('-', '/'))
      window.sessionStorage.setItem(ACTIVE_IMPORT_JOB_KEY, queued.job_id)
      setImportJob({
        id: queued.job_id, preview_id: preview.preview_id, filename: preview.filename,
        status: 'queued', result: null, error: '',
        phase: 'queued', processed: 0, total: 0, message: 'Aguardando processamento', logs: [],
        created_at: '', started_at: '', finished_at: '',
      })
      addToast('Importação iniciada. Você pode aguardar nesta tela.')
    } catch (e: any) {
      setError(e?.detail || 'Falha ao confirmar importação.')
      addToast('Erro ao confirmar importação', 'err')
      setLoading(false)
    }
  }

  return (
    <div className="max-w-6xl space-y-5">
      <div className="rounded-xl p-5" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,0.08)' }}>
        <h2 className="text-xl font-semibold text-[#e8eaf0] mb-1">Importar extrato ou fatura</h2>
        <p className="text-sm text-[#8b90a4]">Fluxo seguro: detectar tipo, validar lançamentos e só depois salvar no banco.</p>
      </div>

      <div
        className="rounded-xl p-8 text-center transition-all"
        style={{
          border: '2px dashed ' + (drag ? '#c9a84c' : 'rgba(255,255,255,0.12)'),
          background: drag ? 'rgba(201,168,76,0.05)' : '#13161d',
        }}
        onDragOver={e => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={e => { e.preventDefault(); setDrag(false); pickFile(e.dataTransfer.files[0]) }}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".csv,.xls,.xlsx,.pdf"
          className="hidden"
          onChange={e => pickFile(e.target.files?.[0])}
        />
        <button type="button" disabled={loading} onClick={() => inputRef.current?.click()} className="mb-4 h-10 px-4 rounded-md text-sm font-semibold disabled:opacity-40" style={{ background: '#1a1e28', color: '#e8eaf0', border: '1px solid rgba(255,255,255,0.12)' }}>
          Selecionar arquivo
        </button>
        <div className="flex justify-center mb-3">{file ? <FileText size={38} style={{ color: '#c9a84c' }} /> : <Upload size={38} style={{ color: drag ? '#c9a84c' : '#5a5f73' }} />}</div>
        {file ? <><p className="font-medium text-[#e8eaf0]">{file.name}</p><p className="text-sm text-[#5a5f73]">{(file.size / 1024).toFixed(0)} KB</p></> : <p className="text-sm text-[#8b90a4]">CSV, XLS, XLSX ou PDF</p>}
      </div>

      <div className="rounded-xl p-5" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,0.08)' }}>
        <label className="block text-[11px] font-semibold text-[#5a5f73] uppercase tracking-widest mb-2">Conta / Cartão (opcional)</label>
        <select className="w-full h-10 rounded-md px-3 text-sm text-[#e8eaf0] outline-none" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.12)' }} value={accountId} onChange={e => { setAccountId(e.target.value); setPreview(null); setCompetenceMonth(''); setError(null) }}>
          <option value="">Detectar automaticamente</option>
          {accounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
        <p className="mt-2 text-xs text-[#8b90a4]">O sistema analisa o nome e o conteúdo. Se necessário, escolha uma conta e analise novamente.</p>
        <div className="mt-3 flex gap-2">
          <button onClick={handlePreview} disabled={!file || previewLoading} className="h-10 px-4 rounded-md text-sm font-semibold disabled:opacity-40" style={{ background: '#c9a84c', color: '#0d0f14' }}>
            {previewLoading ? 'Analisando...' : 'Analisar arquivo'}
          </button>
          <button onClick={resetAll} disabled={loading || previewLoading} className="h-10 px-4 rounded-md text-sm disabled:opacity-40" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.12)', color: '#8b90a4' }}>
            Limpar
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-3 p-4 rounded-xl" style={{ background: 'rgba(248,113,113,0.08)', border: '1px solid rgba(248,113,113,0.25)' }}>
          <AlertCircle size={16} className="text-[#f87171] flex-shrink-0 mt-0.5" />
          <p className="text-sm text-[#f87171]">{error}</p>
        </div>
      )}

      {importJob && ['queued', 'running'].includes(importJob.status) && (
        <div className="p-4 rounded-xl" style={{ background: 'rgba(96,165,250,0.08)', border: '1px solid rgba(96,165,250,0.25)' }}>
          <div className="flex items-center gap-3"><div className="h-4 w-4 animate-spin rounded-full border-2 border-[#1e3a5f] border-t-[#93c5fd]" /><div className="flex-1"><p className="text-sm font-semibold text-[#93c5fd]">Importação em processamento</p><p className="text-xs text-[#8b90a4]">{importJob.message || 'Preparando importação'}</p></div><span className="text-xs font-mono text-[#93c5fd]">{importJob.total > 0 ? `${importJob.processed}/${importJob.total}` : importJob.phase}</span></div>
          {importJob.total > 0 && <div className="mt-3 h-2 overflow-hidden rounded bg-[#0f1320]"><div className="h-full bg-[#60a5fa] transition-all" style={{ width: `${Math.min(100, (importJob.processed / importJob.total) * 100)}%` }} /></div>}
          {importJob.logs.length > 0 && <div className="mt-3 max-h-36 overflow-auto rounded bg-[#0d0f14] p-3 font-mono text-xs text-[#8b90a4]">{importJob.logs.map((entry, index) => <p key={`${entry.time}-${index}`}><span className="text-[#5a5f73]">{entry.time}</span> {entry.message}</p>)}</div>}
          <p className="mt-2 text-[11px] text-[#5a5f73]">O acompanhamento será retomado mesmo se esta página for atualizada.</p>
        </div>
      )}

      {preview && !result && (
        <div className="rounded-xl p-5" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,0.08)' }}>
          <div className="flex items-center justify-between gap-3 mb-4">
            <div>
              <p className="text-sm text-[#8b90a4]">Tipo detectado</p>
              <p className="text-lg font-semibold text-[#e8eaf0]">{preview.detected_type} <span className="text-sm text-[#5a5f73]">({preview.detection_confidence.toFixed(1)}%)</span></p>
              <p className="text-sm text-[#8b90a4]">Conta selecionada: {selectedAccount?.name || preview.account_name}</p>
              {preview.account_detection && (
                <div className="mt-2 rounded-md p-2 text-xs" style={{ background: '#0f1320', border: '1px solid rgba(255,255,255,0.08)' }}>
                  <p className={preview.account_detection.conflict ? 'text-[#fbbf24]' : 'text-[#93c5fd]'}>
                    Conta {preview.account_detection.selection_source === 'automatic' ? 'detectada' : 'confirmada manualmente'}: {preview.account_detection.confidence.toFixed(0)}%
                  </p>
                  {preview.account_detection.evidence.map((item, index) => <p key={`${item}-${index}`} className="text-[#8b90a4]">• {item}</p>)}
                </div>
              )}
              <label className="mt-3 flex items-center gap-2 text-sm text-[#8b90a4]">
                Competência
                <select
                  aria-label="Mês da competência"
                  value={competenceMonth.split('-')[1] || ''}
                  onChange={e => {
                    const y = competenceMonth.split('-')[0] || String(new Date().getFullYear())
                    setCompetenceMonth(`${y}-${e.target.value}`)
                  }}
                  className="h-8 rounded-md px-2 text-sm text-[#e8eaf0] outline-none"
                  style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.12)' }}
                >
                  <option value="">Mês</option>
                  {['01','02','03','04','05','06','07','08','09','10','11','12'].map((m, i) => (
                    <option key={m} value={m}>{['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'][i]}</option>
                  ))}
                </select>
                <select
                  aria-label="Ano da competência"
                  value={competenceMonth.split('-')[0] || ''}
                  onChange={e => {
                    const m = competenceMonth.split('-')[1] || '01'
                    setCompetenceMonth(`${e.target.value}-${m}`)
                  }}
                  className="h-8 rounded-md px-2 text-sm text-[#e8eaf0] outline-none"
                  style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.12)' }}
                >
                  <option value="">Ano</option>
                  {['2023','2024','2025','2026'].map(y => <option key={y} value={y}>{y}</option>)}
                </select>
              </label>
              {(!competenceMonth || competenceMonth.split('-').filter(Boolean).length < 2) && (
                <p className="mt-1 text-xs text-[#fbbf24]">Selecione mês e ano de competência antes de confirmar.</p>
              )}
              {preview.import_meta?.competence_confidence != null && (
                <div className="mt-2 text-xs text-[#8b90a4]">
                  <p>Confiança da competência: {preview.import_meta.competence_confidence.toFixed(0)}%</p>
                  {preview.import_meta.competence_evidence?.map((item, index) => <p key={`${item}-${index}`}>• {item}</p>)}
                </div>
              )}
            </div>
            <div className="flex items-center gap-2 text-[#3ecf8e]"><ShieldCheck size={18} /><span className="text-sm font-medium">Pré-validação concluída</span></div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4">
            <div className="rounded-lg p-3" style={{ background: '#0f1320', border: '1px solid rgba(255,255,255,0.07)' }}><p className="text-xs text-[#8b90a4]">Lidos</p><p className="text-xl text-[#e8eaf0] font-semibold">{preview.total_parsed}</p></div>
            <div className="rounded-lg p-3" style={{ background: '#0f1320', border: '1px solid rgba(255,255,255,0.07)' }}><p className="text-xs text-[#8b90a4]">Duplicados no banco</p><p className="text-xl text-[#fbbf24] font-semibold">{preview.duplicates_db}</p></div>
            <div className="rounded-lg p-3" style={{ background: '#0f1320', border: '1px solid rgba(255,255,255,0.07)' }}><p className="text-xs text-[#8b90a4]">Repetições válidas no arquivo</p><p className="text-xl text-[#3ecf8e] font-semibold">{preview.duplicates_internal}</p></div>
            <div className="rounded-lg p-3" style={{ background: '#0f1320', border: '1px solid rgba(255,255,255,0.07)' }}><p className="text-xs text-[#8b90a4]">Novos para inserir</p><p className="text-xl text-[#3ecf8e] font-semibold">{preview.new_records}</p></div>
            <div className="rounded-lg p-3" style={{ background: '#0f1320', border: '1px solid rgba(255,255,255,0.07)' }}><p className="text-xs text-[#8b90a4]">Sugestões do histórico</p><p className="text-xl text-[#93c5fd] font-semibold">{preview.historical_matches || 0}</p></div>
          </div>

          <div className="grid grid-cols-2 gap-3 mb-4">
            <div className="rounded-lg p-3" style={{ background: 'rgba(62,207,142,0.06)', border: '1px solid rgba(62,207,142,0.18)' }}>
              <p className="text-xs text-[#8b90a4]">Entradas ({preview.income_count || 0})</p>
              <p className="text-lg text-[#3ecf8e] font-semibold">{fmtCurrency(preview.total_income || 0)}</p>
            </div>
            <div className="rounded-lg p-3" style={{ background: 'rgba(248,113,113,0.06)', border: '1px solid rgba(248,113,113,0.18)' }}>
              <p className="text-xs text-[#8b90a4]">Saídas ({preview.expense_count || 0})</p>
              <p className="text-lg text-[#f87171] font-semibold">{fmtCurrency(preview.total_expense || 0)}</p>
            </div>
          </div>

          {preview.quality_gate && !preview.quality_gate.can_commit && (
            <div className="mb-4 rounded-lg p-3" style={{ background: 'rgba(248,113,113,0.10)', border: '1px solid rgba(248,113,113,0.35)' }}>
              <p className="text-sm font-semibold text-[#f87171]">Importação bloqueada</p>
              {preview.quality_gate.critical_errors.map((item, index) => <p key={`${item}-${index}`} className="text-sm text-[#fecaca]">• {item}</p>)}
            </div>
          )}

          {preview.import_meta?.empty_statement_confirmed && (
            <div className="mb-4 rounded-lg p-3" style={{ background: 'rgba(96,165,250,0.08)', border: '1px solid rgba(96,165,250,0.28)' }}>
              <p className="text-sm font-semibold text-[#93c5fd]">Extrato sem movimentações confirmado</p>
              <p className="mt-1 text-sm text-[#bfdbfe]">O arquivo será guardado para cobrir esta competência, sem criar lançamentos.</p>
            </div>
          )}

          {preview.warnings && preview.warnings.length > 0 && (
            <div className="mb-4 rounded-lg p-3" style={{ background: 'rgba(251,191,36,0.08)', border: '1px solid rgba(251,191,36,0.25)' }}>
              {preview.warnings.map((w, i) => <p key={i} className="text-sm text-[#fbbf24]">{w}</p>)}
            </div>
          )}

          {preview.balance_check?.ok === false && (
            <div className="mb-4 rounded-lg p-3" style={{ background: 'rgba(248,113,113,0.08)', border: '1px solid rgba(248,113,113,0.28)' }}>
              <p className="text-sm font-semibold text-[#f87171]">Conferencia de saldo nao bateu</p>
              {preview.balance_check.message && <p className="mt-1 text-sm text-[#fecaca]">{preview.balance_check.message}</p>}
              <div className="mt-2 grid grid-cols-2 md:grid-cols-4 gap-2 text-xs text-[#fecaca]">
                <span>Inicial: {preview.balance_check.saldo_anterior == null ? '-' : fmtCurrency(preview.balance_check.saldo_anterior)}</span>
                <span>Final PDF: {preview.balance_check.saldo_final_declarado == null ? '-' : fmtCurrency(preview.balance_check.saldo_final_declarado)}</span>
                <span>Calculado: {preview.balance_check.saldo_calculado == null ? '-' : fmtCurrency(preview.balance_check.saldo_calculado)}</span>
                <span>Diferenca: {preview.balance_check.diferenca == null ? '-' : fmtCurrency(preview.balance_check.diferenca)}</span>
              </div>
            </div>
          )}

          {preview.rejected_lines && preview.rejected_lines.length > 0 && (
            <details className="mb-4 rounded-lg p-3" style={{ background: 'rgba(248,113,113,0.08)', border: '1px solid rgba(248,113,113,0.25)' }} open>
              <summary className="cursor-pointer text-sm font-semibold text-[#f87171]">
                {preview.rejected_lines.length} linha(s) candidata(s) nao foram importadas
              </summary>
              <div className="mt-3 max-h-48 overflow-auto space-y-2">
                {preview.rejected_lines.map((line, i) => (
                  <pre key={`${line}-${i}`} className="whitespace-pre-wrap rounded-md p-2 text-xs text-[#fecaca]" style={{ background: '#0d0f14', border: '1px solid rgba(248,113,113,0.18)' }}>
                    {line}
                  </pre>
                ))}
              </div>
            </details>
          )}

          {preview.discarded_lines && preview.discarded_lines.length > 0 && (
            <details className="mb-4 rounded-lg p-3" style={{ background: 'rgba(251,191,36,0.08)', border: '1px solid rgba(251,191,36,0.25)' }}>
              <summary className="cursor-pointer text-sm font-semibold text-[#fbbf24]">
                {preview.discarded_lines.length} linha(s) reconhecida(s) foram descartadas por regra de importação
              </summary>
              <div className="mt-3 max-h-48 overflow-auto space-y-2">
                {preview.discarded_lines.map((line, i) => (
                  <pre key={`${line}-${i}`} className="whitespace-pre-wrap rounded-md p-2 text-xs text-[#fde68a]" style={{ background: '#0d0f14', border: '1px solid rgba(251,191,36,0.18)' }}>
                    {line}
                  </pre>
                ))}
              </div>
            </details>
          )}

          <div className="overflow-auto rounded-lg" style={{ maxHeight: 360, border: '1px solid rgba(255,255,255,0.08)' }}>
            <table className="w-full text-sm">
              <thead style={{ background: '#0f1320' }}>
                <tr className="text-left text-[#8b90a4]">
                  <th className="px-3 py-2">Data</th>
                  <th className="px-3 py-2">Descrição</th>
                  <th className="px-3 py-2">Valor</th>
                  <th className="px-3 py-2">Tipo</th>
                  <th className="px-3 py-2">Validação</th>
                  <th className="px-3 py-2">Match hist.</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((r, i) => (
                  <tr key={`${r.date}-${r.description}-${i}`} style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}>
                    <td className="px-3 py-2 text-[#cbd2e0]">{r.date}</td>
                    <td className="px-3 py-2 text-[#e8eaf0] max-w-[420px]">
                      <span className="truncate block">{r.description}</span>
                      {r.is_installment && (
                        <span className="mt-1 inline-flex rounded px-1.5 py-0.5 text-[10px] font-semibold" style={{ background: 'rgba(201,168,76,0.12)', color: '#e8c96e', border: '1px solid rgba(201,168,76,0.25)' }}>
                          {r.installment_label || `Parcela ${r.installment_current} de ${r.installment_total}`}
                        </span>
                      )}
                      {visibleFlags(r.flags) && (
                        <span className="mt-1 ml-1 inline-flex rounded px-1.5 py-0.5 text-[10px] font-semibold" style={{ background: 'rgba(96,165,250,0.10)', color: '#93c5fd', border: '1px solid rgba(96,165,250,0.22)' }}>
                          {visibleFlags(r.flags)}
                        </span>
                      )}
                    </td>
                    <td className={`px-3 py-2 font-medium ${r.amount >= 0 ? 'text-[#3ecf8e]' : 'text-[#f87171]'}`}>{fmtCurrency(r.amount)}</td>
                    <td className="px-3 py-2 text-[#8b90a4]">{r.type === 'income' ? 'Entrada' : 'Saída'}</td>
                    <td className="px-3 py-2">
                      {r.duplicate_db ? <span className="text-[#f87171]">Já existe no banco — arquivo bloqueado</span> : r.duplicate_internal ? <span className="text-[#3ecf8e]">Repetição válida</span> : <span className="text-[#3ecf8e]">Novo</span>}
                    </td>
                    <td className="px-3 py-2 text-[#93c5fd]">{r.match_probability ? `${r.match_probability.toFixed(0)}%` : '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-4 flex justify-end">
            <button onClick={handleCommit} disabled={loading || !/^\d{4}-\d{2}$/.test(competenceMonth) || (preview.new_records <= 0 && !preview.import_meta?.empty_statement_confirmed) || preview.quality_gate?.can_commit === false} className="h-10 px-5 rounded-md font-semibold text-sm disabled:opacity-40 flex items-center gap-2" style={{ background: '#3ecf8e', color: '#0b1218' }}>
              <Database size={16} />
              {loading ? 'Salvando...' : preview.import_meta?.empty_statement_confirmed ? 'Registrar extrato vazio' : 'Confirmar importação'}
            </button>
          </div>
        </div>
      )}

      {result && (
        <div className="p-5 rounded-xl" style={{ background: 'rgba(62,207,142,0.06)', border: '1px solid rgba(62,207,142,0.2)' }}>
          <div className="flex items-center gap-2 mb-4"><CheckCircle size={16} className="text-[#3ecf8e]" /><span className="font-semibold text-[#3ecf8e]">{result.import_meta?.empty_statement_confirmed ? 'Extrato vazio registrado' : 'Importação concluída'}</span></div>
          <div className="grid grid-cols-3 gap-3 text-center">
            {[['Inseridos', result.total_inserted, '#3ecf8e'], ['Repetições válidas', result.total_duplicates_internal || 0, '#3ecf8e'], ['Total lidos', result.total_parsed, '#8b90a4']].map(([l, v, c]) => (
              <div key={String(l)}><p className="text-2xl font-bold" style={{ color: String(c) }}>{String(v)}</p><p className="text-xs text-[#5a5f73] mt-0.5">{String(l)}</p></div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
