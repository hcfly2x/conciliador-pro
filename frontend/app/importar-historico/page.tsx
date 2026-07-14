'use client'
import { useRef, useState } from 'react'
import { importSeedFile } from '@/lib/api'
import { useStore } from '@/store/app'

export default function HistoricoPage() {
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const { addToast } = useStore()

  async function handleSend() {
    if (!file) return
    setLoading(true)
    setError('')
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
      <p className="text-sm text-[#8b90a4] mb-5">Use esta tela para subir sua planilha ja conciliada (abas ENTRADAS/SAIDAS).</p>

      <div className="rounded-xl p-5 mb-4" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,0.07)' }}>
        <input ref={inputRef} type="file" accept=".xlsx" className="hidden" onChange={e => setFile(e.target.files?.[0] || null)} />
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
        </div>
      )}

      <button onClick={handleSend} disabled={!file || loading} className="h-11 px-5 rounded-xl font-semibold text-sm disabled:opacity-40" style={{ background: '#c9a84c', color: '#0d0f14' }}>
        {loading ? 'Importando...' : 'Importar base historica'}
      </button>
    </div>
  )
}
