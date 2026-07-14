'use client'
import { useStore } from '@/store/app'
import { CheckCircle, XCircle } from 'lucide-react'

export default function Toasts() {
  const { toasts } = useStore()
  if (!toasts.length) return null
  return (
    <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-2">
      {toasts.map(t => (
        <div
          key={t.id}
          className="flex items-center gap-3 px-4 py-3 rounded-lg text-sm shadow-2xl animate-slide-up min-w-[280px]"
          style={{
            background: '#1a1e28',
            border: `1px solid ${t.type === 'ok' ? 'rgba(62,207,142,0.3)' : 'rgba(248,113,113,0.3)'}`,
          }}
        >
          {t.type === 'ok'
            ? <CheckCircle size={15} className="text-[#3ecf8e] flex-shrink-0" />
            : <XCircle size={15} className="text-[#f87171] flex-shrink-0" />
          }
          <span className="text-[#e8eaf0]">{t.msg}</span>
        </div>
      ))}
    </div>
  )
}
