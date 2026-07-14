'use client'
import { useState } from 'react'
import { Plus, Pencil, Trash2, Check, X } from 'lucide-react'
import { useStore } from '@/store/app'
import { createAccount, updateAccount, deleteAccount } from '@/lib/api'
import type { Account } from '@/types'

const TYPE_LABELS: Record<string, string> = { checking: 'Conta corrente', credit_card: 'Cartão de crédito', savings: 'Poupança' }
const COLORS = ['#2563eb','#7c3aed','#8b5cf6','#0d9488','#dc2626','#d97706','#16a34a','#64748b']

export default function AccountsPage() {
  const { accounts, setAccounts, addToast } = useStore()
  const [editing, setEditing] = useState<Partial<Account> | null>(null)

  async function save() {
    if (!editing?.name?.trim()) { addToast('Nome obrigatório', 'err'); return }
    try {
      if (editing.id) {
        const updated = await updateAccount(editing.id, editing)
        setAccounts(accounts.map(a => a.id === editing.id ? updated : a))
        addToast('Conta atualizada')
      } else {
        const created = await createAccount(editing)
        setAccounts([...accounts, created])
        addToast('Conta criada')
      }
      setEditing(null)
    } catch { addToast('Erro ao salvar', 'err') }
  }

  async function del(id: string) {
    if (!confirm('Remover conta?')) return
    try {
      await deleteAccount(id)
      setAccounts(accounts.filter(a => a.id !== id))
      addToast('Removida')
    } catch (e: any) { addToast(e?.detail || 'Erro ao remover', 'err') }
  }

  return (
    <div className="max-w-2xl">
      <div className="flex justify-end mb-5">
        <button onClick={() => setEditing({ name: '', type: 'checking', color: '#2563eb' })} className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold" style={{ background: '#c9a84c', color: '#0d0f14' }}>
          <Plus size={14} /> Nova conta
        </button>
      </div>

      {editing && (
        <div className="rounded-xl p-5 mb-5" style={{ background: '#13161d', border: '1px solid rgba(201,168,76,0.3)' }}>
          <h3 className="font-display font-bold text-[14px] text-[#e8eaf0] mb-4">{editing.id ? 'Editar' : 'Nova'} conta</h3>
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block text-[11px] font-semibold text-[#5a5f73] uppercase tracking-widest mb-2">Nome</label>
              <input className="w-full h-9 rounded-md px-3 text-sm text-[#e8eaf0] outline-none" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.12)' }} value={editing.name || ''} onChange={e => setEditing({ ...editing, name: e.target.value.toUpperCase() })} placeholder="CONTA SANTANDER" />
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-[#5a5f73] uppercase tracking-widest mb-2">Tipo</label>
              <select className="w-full h-9 rounded-md px-3 text-sm text-[#e8eaf0] outline-none" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.12)' }} value={editing.type || 'checking'} onChange={e => setEditing({ ...editing, type: e.target.value as any })}>
                <option value="checking">Conta corrente</option>
                <option value="credit_card">Cartão de crédito</option>
                <option value="savings">Poupança</option>
              </select>
            </div>
          </div>
          <div className="mb-4">
            <label className="block text-[11px] font-semibold text-[#5a5f73] uppercase tracking-widest mb-2">Cor</label>
            <div className="flex gap-2">
              {COLORS.map(c => (
                <button key={c} onClick={() => setEditing({ ...editing, color: c })} className="w-7 h-7 rounded-md transition-all" style={{ background: c, border: editing.color === c ? '2px solid white' : '2px solid transparent', transform: editing.color === c ? 'scale(1.2)' : 'scale(1)' }} />
              ))}
            </div>
          </div>
          <div className="flex gap-2 justify-end">
            <button onClick={() => setEditing(null)} className="px-4 py-2 rounded-md text-sm text-[#8b90a4]" style={{ background: '#1a1e28' }}><X size={13} /></button>
            <button onClick={save} className="flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-semibold" style={{ background: '#c9a84c', color: '#0d0f14' }}><Check size={13} /> Salvar</button>
          </div>
        </div>
      )}

      <div className="rounded-xl overflow-hidden" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,0.07)' }}>
        <table className="w-full text-sm">
          <thead>
            <tr style={{ background: '#1a1e28', borderBottom: '1px solid rgba(255,255,255,0.07)' }}>
              {['Conta','Tipo','Cor','Ações'].map(h => <th key={h} className="px-4 py-3 text-left text-[11px] font-semibold text-[#5a5f73] uppercase tracking-widest">{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {accounts.map(a => (
              <tr key={a.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }} className="hover:brightness-110">
                <td className="px-4 py-3">
                  <span className="px-2.5 py-1 rounded text-[11px] font-semibold" style={{ background: a.color + '20', color: a.color, border: `1px solid ${a.color}40` }}>{a.name}</span>
                </td>
                <td className="px-4 py-3 text-xs text-[#5a5f73]">{TYPE_LABELS[a.type]}</td>
                <td className="px-4 py-3"><span className="w-5 h-5 rounded block" style={{ background: a.color }} /></td>
                <td className="px-4 py-3">
                  <div className="flex gap-2">
                    <button onClick={() => setEditing(a)} className="p-1.5 rounded text-[#5a5f73] hover:text-[#e8eaf0]" style={{ background: '#1a1e28' }}><Pencil size={12} /></button>
                    <button onClick={() => del(a.id)} className="p-1.5 rounded" style={{ background: 'rgba(248,113,113,0.1)', color: '#f87171' }}><Trash2 size={12} /></button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
