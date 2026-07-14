'use client'
import { useState } from 'react'
import { AlertTriangle, Trash2 } from 'lucide-react'
import { systemReset, isAdmin } from '@/lib/api'
import { useStore } from '@/store/app'

export default function SistemaPage() {
  const { addToast, bumpRefresh } = useStore()
  const [confirmText, setConfirmText] = useState('')
  const [wipeCategories, setWipeCategories] = useState(false)
  const [loading, setLoading] = useState<'transactions' | 'all' | null>(null)
  const [result, setResult] = useState<string>('')

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
    } catch (e: unknown) {
      const err = e as { detail?: string }
      addToast(err?.detail || 'Erro ao resetar', 'err')
    } finally {
      setLoading(null)
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
