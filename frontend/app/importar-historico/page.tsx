'use client'
import { useEffect, useRef, useState } from 'react'
import { getRecalculationJob, importSeedFile, type RecalculationJob } from '@/lib/api'
import { useStore } from '@/store/app'

export default function HistoricoPage() {
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState('')
  const [job, setJob] = useState<RecalculationJob | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const { addToast } = useStore()

  useEffect(() => {
    const jobId = result?.recalculation_job_id
    if (!jobId) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const poll = async () => {
      try {
        const current = await getRecalculationJob(jobId)
        if (cancelled) return
        setJob(current)
        if (current.status === 'queued' || current.status === 'running') {
          timer = setTimeout(poll, 2000)
        }
      } catch {
        if (!cancelled) timer = setTimeout(poll, 4000)
      }
    }
    poll()
    return () => { cancelled = true; if (timer) clearTimeout(timer) }
  }, [result?.recalculation_job_id])

  async function handleSend() {
    if (!file) return
    setLoading(true)
    setError('')
    setJob(null)
    try {
      const r = await importSeedFile(file)
      setResult(r)
      addToast('Planilha base importada com sucesso')
    } catch (e: any) {
      setError(e?.detail || 'Erro ao importar planilha base')
      addToast('Falha na importacao da base', 'err')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-2xl">
      <h2 className="font-display text-xl text-[#e8eaf0] mb-2">Importar planilha historica</h2>
      <p className="text-sm text-[#8b90a4] mb-5">Use esta tela para subir sua planilha ja conciliada (abas ENTRADAS/SAIDAS) ou PDF. Ela alimenta apenas as sugestoes de categoria/subcategoria.</p>

      <div className="rounded-xl p-5 mb-4" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,0.07)' }}>
        <input ref={inputRef} type="file" accept=".xlsx,.pdf" className="hidden" onChange={e => setFile(e.target.files?.[0] || null)} />
        <button onClick={() => inputRef.current?.click()} className="h-10 px-4 rounded-md text-sm font-semibold" style={{ background: '#1a1e28', color: '#e8eaf0', border: '1px solid rgba(255,255,255,0.12)' }}>
          Selecionar planilha
        </button>
        <p className="mt-3 text-sm text-[#8b90a4]">{file ? file.name : 'Nenhum arquivo selecionado'}</p>
      </div>

      {error && <div className="mb-4 text-sm text-[#f87171]">{error}</div>}

      {result && (
        <div className="rounded-xl p-4 mb-4" style={{ background: 'rgba(62,207,142,0.06)', border: '1px solid rgba(62,207,142,0.2)' }}>
          <p className="text-sm text-[#3ecf8e] font-semibold mb-2">Importacao concluida</p>
          <p className="text-sm text-[#e8eaf0]">Total: {result.total_parsed} | Inseridos: {result.total_inserted} | Duplicados: {result.total_duplicates}</p>
          {result.recalculation_job_id && (
            <div className="mt-3">
              <p className="text-sm text-[#8b90a4]">
                {job?.status === 'completed' && `Sugestoes atualizadas para ${job.updated} lancamentos.`}
                {job?.status === 'failed' && `Falha ao atualizar sugestoes: ${job.error || 'erro interno'}`}
                {(!job || job.status === 'queued') && 'Base salva. Atualizacao das sugestoes aguardando inicio...'}
                {job?.status === 'running' && `Atualizando sugestoes: ${job.processed} de ${job.total} lancamentos...`}
              </p>
              {job && job.total > 0 && (job.status === 'running' || job.status === 'completed') && (
                <div className="mt-2 h-2 overflow-hidden rounded bg-[#1a1e28]">
                  <div className="h-full bg-[#3ecf8e] transition-all" style={{ width: `${Math.min(100, (job.processed / job.total) * 100)}%` }} />
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <button onClick={handleSend} disabled={!file || loading} className="h-11 px-5 rounded-xl font-semibold text-sm disabled:opacity-40" style={{ background: '#c9a84c', color: '#0d0f14' }}>
        {loading ? 'Importando...' : 'Importar base historica'}
      </button>
    </div>
  )
}
