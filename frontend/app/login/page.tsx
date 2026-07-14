'use client'
import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Lock } from 'lucide-react'
import { login } from '@/lib/api'

export default function LoginPage() {
  const router = useRouter()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit() {
    if (!username || !password) { setError('Informe usuario e senha'); return }
    setLoading(true)
    setError('')
    try {
      await login(username, password)
      router.replace('/')
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail
      setError(detail || 'Nao foi possivel entrar. Verifique usuario e senha.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex h-screen items-center justify-center" style={{ background: '#0d0f14' }}>
      <div
        className="w-full max-w-sm rounded-xl p-8 flex flex-col gap-4"
        style={{ background: '#13161d', border: '1px solid rgba(255,255,255,0.07)' }}
      >
        <div className="flex items-center gap-3 mb-2">
          <div
            className="h-10 w-10 rounded-lg flex items-center justify-center"
            style={{ background: 'rgba(201,168,76,0.15)', border: '1px solid rgba(201,168,76,0.35)' }}
          >
            <Lock size={18} color="#c9a84c" />
          </div>
          <div>
            <h1 className="font-display font-bold text-[16px] text-[#e8eaf0]">Conciliador Pro</h1>
            <p className="text-[12px] text-[#8b90a4]">Entre com seu usuario</p>
          </div>
        </div>

        <label className="flex flex-col gap-1.5">
          <span className="text-[12px] font-semibold text-[#8b90a4]">Usuario</span>
          <input
            className="h-10 px-3 rounded-md text-sm text-[#e8eaf0] outline-none"
            style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.12)' }}
            value={username}
            onChange={e => setUsername(e.target.value)}
            autoComplete="username"
            onKeyDown={e => { if (e.key === 'Enter') handleSubmit() }}
          />
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="text-[12px] font-semibold text-[#8b90a4]">Senha</span>
          <input
            type="password"
            className="h-10 px-3 rounded-md text-sm text-[#e8eaf0] outline-none"
            style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.12)' }}
            value={password}
            onChange={e => setPassword(e.target.value)}
            autoComplete="current-password"
            onKeyDown={e => { if (e.key === 'Enter') handleSubmit() }}
          />
        </label>

        {error && (
          <div
            className="text-[12px] rounded-md px-3 py-2"
            style={{ background: 'rgba(248,113,113,0.10)', color: '#fca5a5', border: '1px solid rgba(248,113,113,0.28)' }}
          >
            {error}
          </div>
        )}

        <button
          onClick={handleSubmit}
          disabled={loading}
          className="h-10 rounded-md text-sm font-semibold transition-all disabled:opacity-50"
          style={{ background: '#c9a84c', color: '#0d0f14' }}
        >
          {loading ? 'Entrando...' : 'Entrar'}
        </button>
      </div>
    </div>
  )
}
