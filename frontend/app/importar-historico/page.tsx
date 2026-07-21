'use client'
import { useEffect, useRef, useState } from 'react'
import { getActiveSeedImportJob, getSeedImportJob, importSeedFile, type SeedImportJob } from '@/lib/api'
import { useStore } from '@/store/app'

export default function HistoricoPage() {
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState('')
  const [importJob, setImportJob] = useState<SeedImportJob | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const { addToast } = useStore()

  useEffect(() => {
    let cancelled = false
    getActiveSeedImportJob()
      .then(active => { if (!cancelled && active) setImportJob(active) })
      .catch(() => undefined)
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    const jobId = importJob?.id
    if (!jobId || importJob.status === 'completed' || importJob.status === 'failed') return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const poll = async () => {
      try {
        const current = await getSeedImportJob(jobId)
        if (cancelled) return
        setImportJob(current)
        if (current.status === 'completed' && current.result) {
          setResult(current.result)
          addToast('Planilha base importada com sucesso')
        } else if (current.status === 'failed') {
          setError(current.error || 'Erro ao importar planilha base')
          addToast('Falha na importacao da base', 'err')
        } else {
          timer = setTimeout(poll, 2000)
        }
      } catch {
        if (!cancelled) timer = setTimeout(poll, 4000)
      }
    }
    timer = setTimeout(poll, 500)
    return () => { cancelled = true; if (timer) clearTimeout(timer) }
  }, [importJob?.id, importJob?.status, addToast])

  async function handleSend() {
    if (!file) return
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const r = await importSeedFile(file)
      setImportJob({ id: r.job_id, status: 'queued', filename: r.filename, result: null, error: '', phase: 'queued', processed: 0, total: 0, message: 'Arquivo recebido', logs: [] })
    } catch (e: any) {
      if (e?.code === 'SEED_REPLACE_CONFIRMATION_REQUIRED') {
        const confirmed = window.confirm(
          `Ja existe uma base historica ativa com ${e.existing_records || 'alguns'} registros. ` +
          'A nova base sera validada primeiro e, somente se estiver correta, substituira a atual. Deseja continuar?'
        )
        if (confirmed) {
          try {
            const r = await importSeedFile(file, true)
            setImportJob({ id: r.job_id, status: 'queued', filename: r.filename, result: null, error: '', phase: 'queued', processed: 0, total: 0, message: 'Arquivo recebido para substituir a base atual', logs: [] })
          } catch (retryError: any) {
            setError(retryError?.detail || 'Erro ao substituir a base historica')
            addToast('Falha ao substituir a base', 'err')
          }
        }
      } else if (e?.code === 'SEED_IMPORT_IN_PROGRESS' && e?.job_id) {
        try {
          const active = await getSeedImportJob(e.job_id)
          setImportJob(active)
          setError('')
          addToast('Acompanhando a importacao que ja estava em andamento')
        } catch {
          setError(e?.detail || 'Erro ao consultar importacao em andamento')
        }
      } else {
        setError(e?.detail || 'Erro ao importar planilha base')
        addToast('Falha na importacao da base', 'err')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-2xl">
      <h2 className="font-display text-xl text-[#e8eaf0] mb-2">Importar planilha historica</h2>
      <p className="text-sm text-[#8b90a4] mb-5">Use esta tela para subir sua planilha ja conciliada (abas ENTRADAS/SAIDAS) ou PDF. Ela alimenta apenas as sugestoes de categoria/subcategoria. Se ja houver uma base ativa, a substituicao exigira confirmacao.</p>

      <div className="rounded-xl p-5 mb-4" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,0.07)' }}>
        <input ref={inputRef} type="file" accept=".xlsx,.pdf" className="hidden" onChange={e => setFile(e.target.files?.[0] || null)} />
        <button onClick={() => inputRef.current?.click()} className="h-10 px-4 rounded-md text-sm font-semibold" style={{ background: '#1a1e28', color: '#e8eaf0', border: '1px solid rgba(255,255,255,0.12)' }}>
          Selecionar planilha
        </button>
        <p className="mt-3 text-sm text-[#8b90a4]">{file ? file.name : 'Nenhum arquivo selecionado'}</p>
      </div>

      {error && <div className="mb-4 text-sm text-[#f87171]">{error}</div>}

      {importJob && importJob.status !== 'completed' && importJob.status !== 'failed' && (
        <div className="rounded-xl p-4 mb-4" style={{ background: 'rgba(201,168,76,0.08)', border: '1px solid rgba(201,168,76,0.25)' }}>
          <p className="text-sm font-semibold text-[#c9a84c]">Arquivo recebido</p>
          <p className="mt-1 text-sm text-[#8b90a4]">
            {importJob.message || (importJob.status === 'queued' ? 'Importacao na fila...' : 'Lendo e salvando a base historica...')}
          </p>
          {importJob.total > 0 && (
            <>
              <div className="mt-3 h-2 overflow-hidden rounded bg-[#1a1e28]">
                <div className="h-full bg-[#c9a84c] transition-all" style={{ width: `${Math.min(100, (importJob.processed / importJob.total) * 100)}%` }} />
              </div>
              <p className="mt-1 text-xs text-[#5a5f73]">{importJob.processed} de {importJob.total} linhas ({Math.round((importJob.processed / importJob.total) * 100)}%)</p>
            </>
          )}
          {importJob.logs.length > 0 && (
            <div className="mt-3 max-h-40 overflow-auto rounded bg-[#0d0f14] p-3 font-mono text-xs text-[#8b90a4]">
              {importJob.logs.map((entry, index) => <p key={`${entry.time}-${index}`}><span className="text-[#5a5f73]">{entry.time}</span> {entry.message}</p>)}
            </div>
          )}
        </div>
      )}

      {result && (
        <div className="rounded-xl p-4 mb-4" style={{ background: 'rgba(62,207,142,0.06)', border: '1px solid rgba(62,207,142,0.2)' }}>
          <p className="text-sm text-[#3ecf8e] font-semibold mb-2">Importacao concluida</p>
          <p className="text-sm text-[#e8eaf0]">Total: {result.total_parsed} | Inseridos: {result.total_inserted} | Duplicados: {result.total_duplicates}</p>
        </div>
      )}

      <button onClick={handleSend} disabled={!file || loading || importJob?.status === 'queued' || importJob?.status === 'running'} className="h-11 px-5 rounded-xl font-semibold text-sm disabled:opacity-40" style={{ background: '#c9a84c', color: '#0d0f14' }}>
        {loading ? 'Enviando...' : (importJob?.status === 'queued' || importJob?.status === 'running') ? 'Processando base...' : 'Importar base historica'}
      </button>
    </div>
  )
}
