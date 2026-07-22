import type { Transaction, TransactionFilters } from '@/types'

export interface TransactionTableProps {
  defaultStatus?: string
  defaultSortBy?: string
  defaultSortOrder?: 'asc' | 'desc'
  defaultLedgerId?: string
  moveTargetLedgerId?: string
  moveTargetLedgerName?: string
  defaultReconciliationStatus?: 'matched' | 'unmatched'
}

export function hasPendingDirectHistoryLink(tx: Transaction) {
  return Boolean(
    tx.history_match_id
    && !tx.history_match_confirmed
    && Number(tx.identity_score || 0) >= Number(tx.history_link_threshold || 96)
  )
}

interface FilterInput {
  page: number
  pageSize: number
  search: string
  status: string
  type: string
  month: string
  dateFrom: string
  dateTo: string
  account: string
  category: string
  subcategory: string
  installment: string
  tagFilters: string[]
  tagMode: 'include' | 'exclude'
  reconciliationStatus?: 'matched' | 'unmatched'
  ledgerId: string
  sortBy: string
  sortOrder: 'asc' | 'desc'
}

export function buildTransactionFilters(input: FilterInput): TransactionFilters {
  return {
    page: input.page,
    page_size: input.pageSize,
    ...(input.search && { search: input.search }),
    ...(input.status && { status: input.status }),
    ...(input.type && { type: input.type }),
    ...(input.month && { competence_month: input.month }),
    ...(input.dateFrom && { date_from: input.dateFrom }),
    ...(input.dateTo && { date_to: input.dateTo }),
    ...(input.account && { account_id: input.account }),
    ...(input.category && { category_id: input.category }),
    ...(input.subcategory && { subcategory_id: input.subcategory }),
    ...(input.installment && { is_installment: input.installment }),
    ...(input.tagFilters.length && {
      tags: input.tagFilters.join(','),
      tag_mode: input.tagMode,
    }),
    ...(input.reconciliationStatus && {
      reconciliation_status: input.reconciliationStatus,
    }),
    ledger_id: input.ledgerId,
    sort_by: input.sortBy,
    sort_order: input.sortOrder,
  }
}
