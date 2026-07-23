'use client'

import { useRef, useState } from 'react'
import { CheckCircle, Files, Loader2, ShieldAlert } from 'lucide-react'
import { commitImportPreview, previewImportFile, waitForDocumentImportJob } from '@/lib/api'
import { useStore } from '@/store/app'

type BatchStatus = 'pending' | 'analyzing' | 'importing' | 'imported' | 'skipped' | 'review' | 'failed'

interface BatchItem {
  id: string
  name: string
  status: BatchStatus
  detail: string
  account?: string
  competence?: string
  parsed?: number
  inserted?: number
}

const STATUS_LABEL: Record<BatchStatus, string> = {
  pending: 'Aguardando',
  analyzing: 'Analisando',
  importing: 'Importando',
  imported: 'Importado',
  skipped: 'Já importado',
  review: 'Revisar',
  failed: 'Falhou',
}

function errorDetail(error: unknown) {
  const value = error as { detail?: string; code?: string }
  return value?.detail || value?.code || 'Falha inesperada'
}

export default function BatchImportPanel() {
  const { addToast, bumpRefresh, bumpMonthsRefresh } = useStore()
  const inputRef = useRef<HTMLInputElement>(null)
  const [files, setFiles] = useState<File[]>([])
  const [items, setItems] = useState<BatchItem[]>([])
  const [running, setRunning] = useState(false)

  function updateItem(id: string, patch: Partial<BatchItem>) {
    setItems(current => current.map(item => item.id === id ? { ...item, ...patch } : item))
  }

  function selectFiles(selected: FileList | null) {
    const next = Array.from(selected || [])
      .filter(file => /\.(csv|xls|xlsx|pdf)$/i.test(file.name))
      .sort((a, b) => (a.webkitRelativePath || a.name).localeCompare(b.webkitRelativePath || b.name))
    setFiles(next)
    setItems(next.map((file, index) => ({
      id: `${index}-${file.webkitRelativePath || file.name}-${file.size}`,
      name: file.webkitRelativePath || file.name,
      status: 'pending',
      detail: '',
    })))
  }

  async function runBatch() {
    if (!files.length || running) return
    if (!window.confirm(
      `Analisar e importar ${files.length} arquivo(s) sequencialmente? ` +
      'Duplicados e documentos com bloqueios serão ignorados para revisão.'
    )) return

    setRunning(true)
    let importedFiles = 0
    let importedRows = 0
    try {
      for (let index = 0; index < files.length; index += 1) {
        const file = files[index]
        const id = `${index}-${file.webkitRelativePath || file.name}-${file.size}`
        updateItem(id, { status: 'analyzing', detail: 'Gerando a prévia oficial' })
        try {
          const preview = await previewImportFile(file)
          const competence = String(preview.import_meta?.suggested_competence_month || '')
          const base = {
            account: preview.account_name,
            competence,
            parsed: preview.total_parsed,
          }
          const blockers: string[] = []
          if (preview.account_detection?.conflict) blockers.push('conflito na detecção da conta')
          if (!/^\d{4}\/\d{2}$/.test(competence)) blockers.push('competência não confirmada')
          if (preview.duplicates_db > 0) blockers.push(`${preview.duplicates_db} duplicado(s) no banco`)
          if (preview.quality_gate?.can_commit === false) {
            blockers.push(...(preview.quality_gate.critical_errors || []))
          }
          if (preview.balance_check?.ok === false) blockers.push('conferência de saldo não bateu')
          if (preview.rejected_lines?.length) {
            blockers.push(`${preview.rejected_lines.length} linha(s) candidata(s) rejeitada(s)`)
          }
          if (preview.new_records <= 0 && !preview.import_meta?.empty_statement_confirmed) {
            updateItem(id, {
              ...base,
              status: 'skipped',
              detail: 'Nenhum lançamento novo; documento já coberto pelo banco',
            })
            continue
          }
          if (blockers.length) {
            updateItem(id, {
              ...base,
              status: preview.duplicates_db > 0 ? 'skipped' : 'review',
              detail: blockers.join('; '),
            })
            continue
          }

          updateItem(id, { ...base, status: 'importing', detail: 'Aguardando o job oficial' })
          const queued = await commitImportPreview(preview.preview_id, true, competence)
          const job = await waitForDocumentImportJob(queued.job_id, progress => {
            updateItem(id, {
              status: 'importing',
              detail: progress.message || `${progress.processed}/${progress.total}`,
            })
          })
          if (job.status !== 'completed' || !job.result) {
            throw new Error(job.error || 'O job de importação falhou')
          }
          importedFiles += 1
          importedRows += job.result.total_inserted
          updateItem(id, {
            ...base,
            status: 'imported',
            inserted: job.result.total_inserted,
            detail: job.result.import_meta?.empty_statement_confirmed
              ? 'Extrato vazio registrado no cofre'
              : `${job.result.total_inserted} lançamento(s) inserido(s)`,
          })
          bumpRefresh()
          bumpMonthsRefresh()
        } catch (error: unknown) {
          const value = error as { code?: string }
          if (value?.code === 'FILE_ALREADY_IMPORTED') {
            updateItem(id, { status: 'skipped', detail: 'Arquivo já importado anteriormente' })
          } else {
            updateItem(id, { status: 'failed', detail: errorDetail(error) })
          }
        }
      }
      addToast(
        `Lote concluído: ${importedFiles} arquivo(s) e ${importedRows} lançamento(s) importados`
      )
    } finally {
      setRunning(false)
    }
  }

  const completed = items.filter(item => ['imported', 'skipped', 'review', 'failed'].includes(item.status)).length
  const imported = items.filter(item => item.status === 'imported').length
  const attention = items.filter(item => ['review', 'failed'].includes(item.status)).length

  return (
    <section className="rounded-xl p-5" style={{ background: '#13161d', border: '1px solid rgba(59,130,246,0.28)' }}>
      <div className="flex items-start gap-3">
        <Files size={19} className="mt-0.5 text-[#93c5fd]" />
        <div>
          <h3 className="font-semibold text-[#e8eaf0]">Importar vários arquivos</h3>
          <p className="mt-1 text-sm text-[#8b90a4]">
            Executa, em sequência, a mesma prévia e confirmação da importação individual.
            Duplicados, divergências de saldo, linhas rejeitadas e conflitos ficam separados para revisão.
          </p>
        </div>
      </div>

      <input
        ref={inputRef}
        data-testid="batch-import-files"
        type="file"
        multiple
        accept=".csv,.xls,.xlsx,.pdf"
        className="hidden"
        disabled={running}
        onChange={event => selectFiles(event.target.files)}
      />

      <div className="mt-4 flex flex-wrap gap-3">
        <button
          type="button"
          disabled={running}
          onClick={() => inputRef.current?.click()}
          className="h-10 rounded-md px-4 text-sm font-semibold disabled:opacity-40"
          style={{ background: 'rgba(59,130,246,0.12)', color: '#93c5fd', border: '1px solid rgba(59,130,246,0.3)' }}
        >
          Selecionar vários arquivos
        </button>
        <button
          type="button"
          disabled={!files.length || running}
          onClick={() => void runBatch()}
          className="flex h-10 items-center gap-2 rounded-md px-4 text-sm font-semibold disabled:opacity-40"
          style={{ background: '#3ecf8e', color: '#0b1218' }}
        >
          {running ? <Loader2 size={15} className="animate-spin" /> : <CheckCircle size={15} />}
          {running ? `Processando ${completed}/${files.length}` : `Analisar e importar ${files.length || ''}`}
        </button>
      </div>

      {items.length > 0 && (
        <div className="mt-4">
          <div className="mb-3 grid grid-cols-3 gap-3 text-sm">
            <div className="rounded-lg bg-[#0f1320] p-3 text-[#cbd5e1]">Concluídos: {completed}/{items.length}</div>
            <div className="rounded-lg bg-[#0f1320] p-3 text-[#86efac]">Importados: {imported}</div>
            <div className="rounded-lg bg-[#0f1320] p-3 text-[#fbbf24]">Atenção: {attention}</div>
          </div>
          <div className="max-h-80 space-y-2 overflow-auto pr-1">
            {items.map(item => (
              <div key={item.id} className="rounded-lg border border-white/8 bg-[#0f1118] p-3 text-sm">
                <div className="flex items-start gap-3">
                  {['review', 'failed'].includes(item.status)
                    ? <ShieldAlert size={15} className="mt-0.5 shrink-0 text-[#fbbf24]" />
                    : <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-[#3b82f6]" />}
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[#e8eaf0]">{item.name}</p>
                    <p className="mt-1 text-xs text-[#8b90a4]">
                      {STATUS_LABEL[item.status]}
                      {item.account ? ` · ${item.account}` : ''}
                      {item.competence ? ` · ${item.competence}` : ''}
                      {item.parsed != null ? ` · ${item.parsed} lido(s)` : ''}
                      {item.detail ? ` · ${item.detail}` : ''}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}
