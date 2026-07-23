'use client'
import { useState } from 'react'
import { AlertTriangle, Download, FileUp, Trash2 } from 'lucide-react'
import { backfillDocument, downloadAuditExport, systemReset, isAdmin } from '@/lib/api'
import { useStore } from '@/store/app'

export default function SistemaPage() {
  const { addToast, bumpRefresh, bumpCatalogRefresh, bumpMonthsRefresh } = useStore()
  const [confirmText, setConfirmText] = useState('')
  const [wipeCategories, setWipeCategories] = useState(false)
  const [loading, setLoading] = useState<'transactions' | 'all' | null>(null)
  const [result, setResult] = useState<string>('')
  const [exporting, setExporting] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const [restoreResult, setRestoreResult] = useState<string>('')

  const admin = isAdmin()

  async function handleReset(scope: 'transactions' | 'all') {
    if (confirmText !== 'RESETAR') {
      addToast('Digite RESETAR no campo de confirmação', 'err')
      return
    }
    const msg = scope === 'all'
      ? `Apagar TODOS os lançamentos, arquivos do cofre E a base histórica${wipeCategories ? ', categorias e subcategorias' : ''}? Esta ação não pode ser desfeita.`
      : 'Apagar todos os lançamentos e arquivos do cofre? A base histórica será mantida. Esta ação não pode ser desfeita.'
    if (!window.confirm(msg)) return
    setLoading(scope)
    setResult('')
    try {
      const r = await systemReset(scope, scope === 'all' ? wipeCategories : false)
      const d = r.deleted || {}
      setResult(
        `Concluído: ${d.transactions ?? 0} lançamentos, ${d.stored_documents ?? 0} arquivos do cofre` +
        (scope === 'all' ? `, ${d.classification_history ?? 0} registros da base histórica` : '') +
        ' apagados.'
      )
      addToast('Banco de dados zerado')
      setConfirmText('')
      bumpRefresh()
      bumpMonthsRefresh()
      bumpCatalogRefresh()
    } catch (e: unknown) {
      const err = e as { detail?: string }
      addToast(err?.detail || 'Erro ao resetar', 'err')
    } finally {
      setLoading(null)
    }
  }

  async function handleAuditExport() {
    setExporting(true)
    try {
      await downloadAuditExport()
      addToast('Exportação de auditoria gerada')
    } catch (e: unknown) {
      const err = e as { detail?: string; status?: number }
      const message = err?.detail || (
        err?.status
          ? 'Erro ao exportar auditoria'
          : 'Conexão interrompida durante a geração da auditoria'
      )
      addToast(message, 'err')
    } finally {
      setExporting(false)
    }
  }

  async function handleDocumentBackfill(files: FileList | null) {
    if (!files?.length) return
    setRestoring(true)
    setRestoreResult('')
    try {
      let restored = 0
      let alreadyPresent = 0
      let transactions = 0
      for (const file of Array.from(files)) {
        const response = await backfillDocument(file)
        if (response.status === 'already_present') alreadyPresent += 1
        else restored += 1
        transactions += response.transactions
      }
      setRestoreResult(
        `${restored} documento(s) restaurado(s), ${alreadyPresent} já presente(s); ` +
        `${transactions} lançamento(s) vinculados sem reimportação.`
      )
      addToast('Documentos conferidos e vinculados ao cofre')
    } catch (e: unknown) {
      const err = e as { detail?: string }
      addToast(err?.detail || 'Erro ao restaurar documento', 'err')
    } finally {
      setRestoring(false)
    }
  }

  if (!admin) {
    return <p className="text-sm text-[#8b90a4]">Apenas o administrador pode acessar esta página.</p>
  }

  return (
    <div className="max-w-2xl">
      <h2 className="font-display text-xl text-[#e8eaf0] mb-2">Sistema</h2>
      <p className="text-sm text-[#8b90a4] mb-6">
        Ações administrativas do banco de dados. Contas bancárias, usuários e trilha de auditoria são sempre preservados.
      </p>

      <div className="rounded-xl p-5 mb-5" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,0.08)' }}>
        <h3 className="font-display font-bold text-[14px] text-[#e8eaf0] mb-2">Auditoria financeira</h3>
        <p className="text-sm text-[#8b90a4] mb-4">
          Gera uma planilha legível com resumo, filtros, legenda e uma linha por lançamento.
          Classificação, parcelas, vínculos, conciliações e documentos ficam visíveis; IDs técnicos
          permanecem disponíveis em colunas ocultas.
        </p>
        <button
          onClick={handleAuditExport}
          disabled={exporting}
          className="flex items-center justify-center gap-2 h-10 px-4 rounded-lg text-sm font-semibold disabled:opacity-40"
          style={{ background: 'rgba(59,130,246,0.12)', color: '#93c5fd', border: '1px solid rgba(59,130,246,0.3)' }}
        >
          <Download size={14} />
          {exporting ? 'Gerando planilha...' : 'Exportar auditoria em Excel'}
        </button>
      </div>

      <div className="rounded-xl p-5 mb-5" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,0.08)' }}>
        <h3 className="font-display font-bold text-[14px] text-[#e8eaf0] mb-2">Restaurar originais no cofre</h3>
        <p className="text-sm text-[#8b90a4] mb-4">
          Vincula documentos antigos ao lote existente pelo SHA-1. O conteúdo precisa ser exatamente
          igual ao arquivo importado; nenhum lançamento é criado, removido ou reimportado.
        </p>
        <label
          className="flex items-center justify-center gap-2 h-10 px-4 rounded-lg text-sm font-semibold cursor-pointer"
          style={{ background: 'rgba(34,197,94,0.12)', color: '#86efac', border: '1px solid rgba(34,197,94,0.3)' }}
        >
          <FileUp size={14} />
          {restoring ? 'Conferindo documentos...' : 'Selecionar documentos para restaurar'}
          <input
            type="file"
            multiple
            accept=".pdf,.csv,.xls,.xlsx"
            className="hidden"
            disabled={restoring}
            onChange={event => {
              void handleDocumentBackfill(event.target.files)
              event.target.value = ''
            }}
          />
        </label>
        {restoreResult && (
          <p className="mt-4 text-sm text-[#3ecf8e]">{restoreResult}</p>
        )}
      </div>

      <div className="rounded-xl p-5" style={{ background: 'rgba(248,113,113,0.05)', border: '1px solid rgba(248,113,113,0.25)' }}>
        <div className="flex items-center gap-2 mb-4">
          <AlertTriangle size={16} color="#f87171" />
          <h3 className="font-display font-bold text-[14px] text-[#fca5a5]">Zona de perigo — zerar banco de dados</h3>
        </div>

        <p className="text-sm text-[#8b90a4] mb-4">
          Antes de zerar, considere criar um backup/branch no painel do provedor do banco (Supabase).
          Para confirmar, digite <span className="font-mono-custom text-[#e8eaf0]">RESETAR</span> abaixo.
        </p>

        <input
          className="w-full h-10 rounded-md px-3 text-sm text-[#e8eaf0] outline-none mb-4"
          style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.12)' }}
          value={confirmText}
          onChange={e => setConfirmText(e.target.value.toUpperCase())}
          placeholder="Digite RESETAR para habilitar"
        />

        <div className="flex flex-col gap-3">
          <button
            onClick={() => handleReset('transactions')}
            disabled={confirmText !== 'RESETAR' || loading !== null}
            className="flex items-center justify-center gap-2 h-11 rounded-lg text-sm font-semibold disabled:opacity-40"
            style={{ background: 'rgba(248,113,113,0.12)', color: '#fca5a5', border: '1px solid rgba(248,113,113,0.3)' }}
          >
            <Trash2 size={14} />
            {loading === 'transactions' ? 'Apagando...' : 'Zerar lançamentos e cofre (mantém base histórica)'}
          </button>

          <div className="rounded-lg p-3" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,0.08)' }}>
            <label className="flex items-center gap-2 text-sm text-[#8b90a4] mb-3 cursor-pointer">
              <input
                type="checkbox"
                checked={wipeCategories}
                onChange={e => setWipeCategories(e.target.checked)}
              />
              Também apagar categorias e subcategorias (as categorias base serão recriadas)
            </label>
            <button
              onClick={() => handleReset('all')}
              disabled={confirmText !== 'RESETAR' || loading !== null}
              className="w-full flex items-center justify-center gap-2 h-11 rounded-lg text-sm font-semibold disabled:opacity-40"
              style={{ background: '#dc2626', color: '#fff' }}
            >
              <Trash2 size={14} />
              {loading === 'all' ? 'Apagando...' : 'Zerar TUDO (lançamentos + cofre + base histórica)'}
            </button>
          </div>
        </div>

        {result && (
          <p className="mt-4 text-sm text-[#3ecf8e]">{result}</p>
        )}
      </div>
    </div>
  )
}
