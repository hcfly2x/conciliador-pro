'use client'
import { useState } from 'react'
import { Plus, Pencil, Trash2, Check, X } from 'lucide-react'
import { useStore } from '@/store/app'
import { createCategory, updateCategory, deleteCategory, createSubcategory, deleteSubcategory } from '@/lib/api'
import type { Category } from '@/types'

const COLORS = ['#dc2626','#f97316','#d97706','#16a34a','#0d9488','#2563eb','#7c3aed','#db2777','#94a3b8','#c9a84c','#3ecf8e','#60a5fa','#ea580c','#06b6d4','#f59e0b','#64748b']

export default function CategoriesPage() {
  const { categories, setCategories, subcategories, setSubcategories, addToast } = useStore()
  const [editing, setEditing] = useState<Partial<Category> & { isNew?: boolean } | null>(null)
  const [newSub, setNewSub] = useState('')

  async function save() {
    if (!editing?.name?.trim()) { addToast('Nome obrigatório', 'err'); return }
    try {
      if (editing.id) {
        const updated = await updateCategory(editing.id, editing)
        setCategories(categories.map(c => c.id === editing.id ? updated : c))
        addToast('Categoria atualizada')
      } else {
        const created = await createCategory(editing)
        setCategories([...categories, created])
        addToast('Categoria criada')
      }
      setEditing(null)
    } catch { addToast('Erro ao salvar', 'err') }
  }

  async function del(id: string) {
    if (!confirm('Remover categoria?')) return
    try {
      await deleteCategory(id)
      setCategories(categories.filter(c => c.id !== id))
      addToast('Removida')
    } catch { addToast('Erro ao remover', 'err') }
  }

  async function delSubcategory(id: string, name: string) {
    if (!confirm(`Remover a subcategoria ${name}?`)) return
    try {
      await deleteSubcategory(id)
      setSubcategories(subcategories.filter(s => s.id !== id))
      addToast('Subcategoria removida')
    } catch (err: unknown) {
      const e = err as { code?: string; detail?: string }
      addToast(e?.code === 'HAS_TRANSACTIONS' ? (e.detail || 'Subcategoria em uso') : 'Erro ao remover subcategoria', 'err')
    }
  }

  async function addSubcategory() {
    const name = newSub.trim()
    if (!name) return
    try {
      const created = await createSubcategory(name)
      setSubcategories([...subcategories, created].filter((s, i, a) => a.findIndex(x => x.id === s.id) === i))
      setNewSub('')
      addToast('Subcategoria criada')
    } catch {
      addToast('Erro ao criar subcategoria', 'err')
    }
  }

  return (
    <div className="max-w-2xl">
      <div className="flex justify-end mb-5">
        <button onClick={() => setEditing({ name: '', color: '#dc2626', text_color: '#fff', type: 'expense', isNew: true })} className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold" style={{ background: '#c9a84c', color: '#0d0f14' }}>
          <Plus size={14} /> Nova categoria
        </button>
      </div>

      {editing && (
        <div className="rounded-xl p-5 mb-5" style={{ background: '#13161d', border: '1px solid rgba(201,168,76,0.3)' }}>
          <h3 className="font-display font-bold text-[14px] text-[#e8eaf0] mb-4">{editing.id ? 'Editar' : 'Nova'} categoria</h3>
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block text-[11px] font-semibold text-[#5a5f73] uppercase tracking-widest mb-2">Nome</label>
              <input className="w-full h-9 rounded-md px-3 text-sm text-[#e8eaf0] outline-none" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.12)' }} value={editing.name || ''} onChange={e => setEditing({ ...editing, name: e.target.value.toUpperCase() })} placeholder="GASTO PESSOAL" />
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-[#5a5f73] uppercase tracking-widest mb-2">Tipo</label>
              <select className="w-full h-9 rounded-md px-3 text-sm text-[#e8eaf0] outline-none" style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.12)' }} value={editing.type || 'expense'} onChange={e => setEditing({ ...editing, type: e.target.value as any })}>
                <option value="expense">Despesa</option>
                <option value="income">Receita</option>
              </select>
            </div>
          </div>
          <div className="mb-4">
            <label className="block text-[11px] font-semibold text-[#5a5f73] uppercase tracking-widest mb-2">Cor</label>
            <div className="flex gap-2 flex-wrap">
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
              {['Categoria', 'Tipo', 'Cor', 'Ações'].map(h => (
                <th key={h} className="px-4 py-3 text-left text-[11px] font-semibold text-[#5a5f73] uppercase tracking-widest">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {categories.map(c => (
              <tr key={c.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }} className="hover:brightness-110">
                <td className="px-4 py-3">
                  <span className="px-2.5 py-1 rounded text-[11px] font-semibold font-mono-custom" style={{ background: c.color + '25', color: c.color, border: `1px solid ${c.color}40` }}>{c.name}</span>
                </td>
                <td className="px-4 py-3 text-xs text-[#5a5f73]">{c.type === 'expense' ? 'Despesa' : 'Receita'}</td>
                <td className="px-4 py-3"><span className="w-5 h-5 rounded block" style={{ background: c.color }} /></td>
                <td className="px-4 py-3">
                  <div className="flex gap-2">
                    <button onClick={() => setEditing(c)} className="p-1.5 rounded text-[#5a5f73] hover:text-[#e8eaf0] transition-colors" style={{ background: '#1a1e28' }}><Pencil size={12} /></button>
                    <button onClick={() => del(c.id)} className="p-1.5 rounded transition-colors" style={{ background: 'rgba(248,113,113,0.1)', color: '#f87171' }}><Trash2 size={12} /></button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-6 rounded-xl p-5" style={{ background: '#13161d', border: '1px solid rgba(255,255,255,0.07)' }}>
        <h3 className="font-display font-bold text-[14px] text-[#e8eaf0] mb-3">Subcategorias ({subcategories.length})</h3>
        <div className="flex gap-2 mb-3">
          <input
            className="flex-1 h-9 rounded-md px-3 text-sm text-[#e8eaf0] outline-none"
            style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.12)' }}
            value={newSub}
            onChange={e => setNewSub(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') addSubcategory() }}
            placeholder="Nova subcategoria"
          />
          <button onClick={addSubcategory} className="px-4 py-2 rounded-md text-sm font-semibold" style={{ background: '#c9a84c', color: '#0d0f14' }}>Adicionar</button>
        </div>
        {subcategories.length === 0 ? (
          <p className="text-xs text-[#5a5f73]">
            Nenhuma subcategoria ainda. Elas sao criadas automaticamente ao importar a base historica
            (menu Importar historico) e tambem quando voce adiciona pelo campo acima.
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {[...subcategories].sort((a, b) => a.name.localeCompare(b.name)).map(s => (
              <span
                key={s.id}
                className="inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-mono-custom group"
                style={{ background: '#1a1e28', color: '#e8eaf0', border: '1px solid rgba(255,255,255,0.12)' }}
              >
                {s.name}
                <button
                  type="button"
                  onClick={() => delSubcategory(s.id, s.name)}
                  className="opacity-40 hover:opacity-100 transition-opacity"
                  title="Remover subcategoria (bloqueado se estiver em uso)"
                  style={{ color: '#f87171', lineHeight: 0 }}
                >
                  <X size={11} />
                </button>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
