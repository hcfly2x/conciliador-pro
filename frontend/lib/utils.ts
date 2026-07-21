import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import type { Transaction } from '@/types'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatCurrencyAbs(value: number): string {
  return new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency: 'BRL',
  }).format(Math.abs(value))
}

export function formatInstallmentLinkExplanation(tx: Transaction): string {
  const current = String(tx.installment_current || 0).padStart(2, '0')
  const total = Number(tx.installment_total || 0)
  const totalLabel = String(total).padStart(2, '0')
  const sign = tx.type === 'income' ? '+' : '-'
  const comparisonAmount = tx.match_comparison_amount || (Math.abs(tx.amount) * total)
  return `Vinculo por parcelamento: REAL: ${current}/${totalLabel} = ${sign}${formatCurrencyAbs(tx.amount)} × ${total} = ${sign}${formatCurrencyAbs(comparisonAmount)}; Base historica: ${formatCurrencyAbs(tx.match_history_amount || 0)}.`
}

export function formatDate(dateStr: string): string {
  const d = new Date(dateStr + 'T12:00:00')
  return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: '2-digit' })
}
