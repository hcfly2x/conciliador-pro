export type AccountType = 'checking' | 'credit_card' | 'savings'
export type TransactionType = 'income' | 'expense'
export type TransactionStatus = 'pending' | 'reconciled' | 'auto_classified' | 'duplicate' | 'ignored'

export interface Account {
  id: string
  name: string
  type: AccountType
  color: string
  is_active: boolean
  created_at: string
}

export interface Ledger {
  id: string
  name: string
  description: string
  color: string
  is_active: boolean
  created_at: string
  transaction_count?: number
  pending_count?: number
  total_income?: number
  total_expense?: number
  balance?: number
}

export interface Category {
  id: string
  name: string
  color: string
  text_color: string
  type: TransactionType
}

export interface Subcategory {
  id: string
  name: string
}

export interface Transaction {
  id: string
  date: string
  competence_month: string
  description: string
  amount: number
  type: TransactionType
  status: TransactionStatus
  account_id: string
  account_name: string
  account_color: string
  category_id: string | null
  category_name: string | null
  category_color: string | null
  category_text_color: string | null
  subcategory_id: string | null
  subcategory_name: string | null
  notes: string | null
  imported_file_id: string
  installment_current?: number | null
  installment_total?: number | null
  installment_label?: string | null
  is_installment?: boolean
  installment_plan_id?: string | null
  installment_plan_total?: number | null
  installment_plan_amount?: number | null
  installment_plan_members?: number
  classification_inherited?: boolean
  flags?: string
  flags_list?: string[]
  match_probability?: number
  match_notes?: string
  history_match_id?: string | null
  history_match_confirmed?: boolean
  history_link_threshold?: number
  identity_score?: number
  match_category_id?: string | null
  match_category_name?: string | null
  match_subcategory_id?: string | null
  match_subcategory_name?: string | null
  match_history_date?: string | null
  match_history_description?: string | null
  match_history_amount?: number | null
  match_history_type?: TransactionType | null
  match_history_source?: string
  match_history_account_name?: string
  match_history_category_name?: string
  match_history_subcategory_name?: string
  merchant_norm?: string
  transaction_method?: string
  counterparty_name?: string
  bank_reference?: string
  match_date_difference_days?: number | null
  match_amount_difference?: number
  match_description_similarity?: number
  match_basis?: 'standard' | 'installment_total'
  match_comparison_date?: string
  match_comparison_amount?: number
  ledger_id?: string | null
  ledger_name?: string | null
  ledger_color?: string | null
  locked?: boolean
  classified_by?: string
  classified_at?: string
  suggestion_state?: 'pending' | 'running' | 'completed' | 'failed'
  suggestion_count?: number
  suggestion_confidence?: number
  suggestion_dismissed?: boolean
  suggestion_calculated_at?: string
  reconciliation_id?: string | null
  reconciliation_counterpart_id?: string | null
  reconciliation_counterpart_date?: string | null
  reconciliation_counterpart_description?: string
  reconciliation_counterpart_amount?: number
  reconciliation_counterpart_type?: TransactionType | null
  reconciliation_counterpart_account_name?: string
  reconciled_by?: string
  reconciled_at?: string
}

export interface TransactionSummary {
  total_income: number
  total_expense: number
  balance: number
  pending_count: number
  reconciled_count: number
}

export interface TransactionFilters {
  page?: number
  page_size?: number
  status?: string
  type?: string
  search?: string
  competence_month?: string
  date_from?: string
  date_to?: string
  account_id?: string
  category_id?: string
  subcategory_id?: string
  is_installment?: string
  tags?: string
  tag_mode?: 'include' | 'exclude'
  ledger_id?: string
  sort_by?: string
  sort_order?: 'asc' | 'desc'
  classification_queue?: 'links' | 'suggestions' | 'none' | 'waiting' | 'dismissed' | 'classified'
  suggestion_strength?: 'strong' | 'weak'
  reconciliation_status?: 'matched' | 'unmatched'
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  total_linked?: number
  page: number
  page_size: number
  total_pages: number
  summary?: TransactionSummary
}

export interface ImportPreviewRow {
  date: string
  description: string
  amount: number
  type: TransactionType
  installment_current?: number | null
  installment_total?: number | null
  installment_label?: string | null
  is_installment?: boolean
  flags?: string
  duplicate_db: boolean
  duplicate_internal: boolean
  occurrence: number
  match_probability?: number
  history_match_id?: string
}

export interface ImportBalanceCheck {
  ok?: boolean
  saldo_anterior?: number | null
  saldo_final_declarado?: number | null
  saldo_calculado?: number | null
  diferenca?: number | null
  message?: string
}

export interface ImportAccountDetection {
  bank: string
  account_type: string
  suggested_account_id?: string
  suggested_account_name?: string
  selected_account_id: string
  selected_account_name: string
  confidence: number
  evidence: string[]
  selection_source: 'automatic' | 'manual'
  conflict: boolean
}

export interface ImportMeta {
  bank?: string
  doc_type?: string
  file_format?: string
  encoding?: string
  detection_confidence?: number
  suggested_competence_month?: string
  competence_confidence?: number
  competence_strategy?: string
  competence_evidence?: string[]
  competence_warning?: string
  total_installments?: number
  total_inter_account?: number
  total_cashback?: number
  total_discarded?: number
  empty_statement_confirmed?: boolean
}

export interface ImportPreviewResult {
  preview_id: string
  filename: string
  account_id: string
  account_name: string
  account_detection?: ImportAccountDetection
  detected_type: string
  detection_confidence: number
  total_parsed: number
  duplicates_db: number
  duplicates_internal: number
  new_records: number
  income_count?: number
  expense_count?: number
  total_income?: number
  total_expense?: number
  historical_matches?: number
  quality_gate?: { can_commit: boolean; critical_errors: string[] }
  warnings?: string[]
  balance_check?: ImportBalanceCheck
  import_meta?: ImportMeta
  rejected_lines?: string[]
  discarded_lines?: string[]
  rows: ImportPreviewRow[]
}

export interface ImportResult {
  imported_file_id: string
  filename: string
  account_name: string
  total_parsed: number
  total_inserted: number
  total_duplicates: number
  total_duplicates_db?: number
  total_duplicates_internal?: number
  total_errors: number
  warnings?: string[]
  balance_check?: ImportBalanceCheck
  import_meta?: ImportMeta
  rejected_lines?: string[]
  discarded_lines?: string[]
  transactions_preview: Transaction[]
  recalculation_job_id?: string
  recalculation_status?: 'queued' | 'running' | 'completed' | 'failed'
}

export interface ReportSummary {
  total_transactions: number
  pending: number
  reconciled: number
  total_income: number
  total_expense: number
  balance: number
}

export interface CategoryReport {
  category_id: string | null
  category_name: string
  category_color: string | null
  total: number
  count: number
  percentage: number
}

export interface MonthlyReport {
  month: string
  income: number
  expense: number
  balance: number
  transaction_count: number
}

export type UserRole = 'admin' | 'colaborador'

export interface AuthUser {
  id: string | null
  username: string
  role: UserRole
}

export interface AuditEntry {
  id: string
  username: string
  action: string
  entity: string
  entity_id: string
  field: string
  old_value: string
  new_value: string
  detail: string
  created_at: string
}
