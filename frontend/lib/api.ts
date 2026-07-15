import type {
  AuthUser, AuditEntry,
  Account, Category, Subcategory, Transaction, Ledger,
  ImportResult, ReportSummary, CategoryReport, MonthlyReport,
  PaginatedResponse, TransactionFilters, TransactionSummary, ImportPreviewResult
} from '@/types'
import {
  mockAccounts, mockCategories, mockSubcategories,
  mockTransactions, mockMonths, mockSummary,
  mockCategoryReport, mockMonthlyReport
} from './mock-data'

const USE_MOCK = (process.env.NEXT_PUBLIC_USE_MOCK ?? 'false').toLowerCase() === 'true'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api/v1'
const BASE = API_BASE

function delay(ms = 250) { return new Promise(r => setTimeout(r, ms)) }

// --- Autenticacao (token Bearer guardado no navegador) ---
const TOKEN_KEY = 'conciliador_token'
const USER_KEY = 'conciliador_user'

export function getToken(): string {
  if (typeof window === 'undefined') return ''
  return window.localStorage.getItem(TOKEN_KEY) || ''
}
export function getStoredUser(): AuthUser | null {
  if (typeof window === 'undefined') return null
  try { return JSON.parse(window.localStorage.getItem(USER_KEY) || 'null') } catch { return null }
}
export function isAdmin(): boolean {
  return getStoredUser()?.role === 'admin'
}
function setSession(token: string, user: AuthUser) {
  window.localStorage.setItem(TOKEN_KEY, token)
  window.localStorage.setItem(USER_KEY, JSON.stringify(user))
}
export function clearSession() {
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(TOKEN_KEY)
  window.localStorage.removeItem(USER_KEY)
}
export function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}
function handleUnauthorized() {
  clearSession()
  if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
    window.location.href = '/login'
  }
}

async function http<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...authHeaders() },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (res.status === 401) {
    handleUnauthorized()
    throw { status: 401, detail: 'Nao autenticado', code: 'UNAUTHORIZED' }
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw { status: res.status, ...err }
  }
  return res.json()
}

// --- Endpoints de autenticacao e usuarios ---
export async function login(username: string, password: string): Promise<AuthUser> {
  const data = await http<{ token: string; user: AuthUser }>('POST', '/auth/login', { username, password })
  setSession(data.token, data.user)
  return data.user
}
export async function logout(): Promise<void> {
  try { await http('POST', '/auth/logout') } catch { /* sessao ja invalida */ }
  clearSession()
}
export async function getMe(): Promise<AuthUser> {
  return http<AuthUser>('GET', '/auth/me')
}
export async function listUsers(): Promise<Array<AuthUser & { is_active: boolean; created_at: string }>> {
  return http('GET', '/auth/users')
}
export async function createUser(data: { username: string; password: string; role: 'admin' | 'colaborador' }): Promise<AuthUser> {
  return http('POST', '/auth/users', data)
}
export async function updateUser(id: string, data: { password?: string; role?: string; is_active?: boolean }): Promise<{ ok: boolean }> {
  return http('PATCH', `/auth/users/${id}`, data)
}

// --- Protecao de lancamentos e auditoria ---
export async function unlockTransaction(id: string, reason?: string): Promise<{ id: string; locked: boolean; ok: boolean }> {
  return http('POST', `/transactions/${id}/unlock`, { reason: reason || '' })
}
export async function getAudit(params?: { entity_id?: string; entity?: string; limit?: number }): Promise<AuditEntry[]> {
  const qs = new URLSearchParams()
  if (params?.entity_id) qs.set('entity_id', params.entity_id)
  if (params?.entity) qs.set('entity', params.entity)
  if (params?.limit) qs.set('limit', String(params.limit))
  const q = qs.toString()
  return http('GET', `/audit${q ? `?${q}` : ''}`)
}

// Accounts
export async function getAccounts(): Promise<Account[]> {
  if (USE_MOCK) { await delay(); return mockAccounts }
  return http<Account[]>('GET', '/accounts')
}
export async function createAccount(data: Partial<Account>): Promise<Account> {
  if (USE_MOCK) { await delay(); return { ...data, id: Date.now().toString(), is_active: true, created_at: new Date().toISOString() } as Account }
  return http<Account>('POST', '/accounts', data)
}
export async function updateAccount(id: string, data: Partial<Account>): Promise<Account> {
  if (USE_MOCK) { await delay(); return { ...data, id } as Account }
  return http<Account>('PUT', `/accounts/${id}`, data)
}
export async function deleteAccount(id: string): Promise<void> {
  if (USE_MOCK) { await delay(); return }
  return http<void>('DELETE', `/accounts/${id}`)
}

// Ledgers / razoes
export async function getLedgers(): Promise<Ledger[]> {
  if (USE_MOCK) { await delay(); return [] }
  return http<Ledger[]>('GET', '/ledgers')
}
export async function createLedger(data: Partial<Ledger>): Promise<Ledger> {
  if (USE_MOCK) { await delay(); return { ...data, id: Date.now().toString(), is_active: true, created_at: new Date().toISOString() } as Ledger }
  return http<Ledger>('POST', '/ledgers', data)
}
export async function updateLedger(id: string, data: Partial<Ledger>): Promise<Ledger> {
  if (USE_MOCK) { await delay(); return { ...data, id } as Ledger }
  return http<Ledger>('PATCH', `/ledgers/${id}`, data)
}
export async function deleteLedger(id: string): Promise<{ ok: boolean; moved_back: number }> {
  if (USE_MOCK) { await delay(); return { ok: true, moved_back: 0 } }
  return http('DELETE', `/ledgers/${id}`)
}
export async function includeTransactionsInLedger(id: string, tx_ids: string[]): Promise<{ updated: number }> {
  if (USE_MOCK) { await delay(); return { updated: tx_ids.length } }
  return http('POST', `/ledgers/${id}/include`, { tx_ids })
}
export async function excludeTransactionsFromLedger(id: string, tx_ids: string[]): Promise<{ updated: number }> {
  if (USE_MOCK) { await delay(); return { updated: tx_ids.length } }
  return http('POST', `/ledgers/${id}/exclude`, { tx_ids })
}

// Categories
export async function getCategories(type?: string): Promise<Category[]> {
  if (USE_MOCK) { await delay(); return type ? mockCategories.filter(c => c.type === type) : mockCategories }
  return http<Category[]>('GET', `/categories${type ? `?type=${type}` : ''}`)
}
export async function createCategory(data: Partial<Category>): Promise<Category> {
  if (USE_MOCK) { await delay(); return { ...data, id: Date.now().toString() } as Category }
  return http<Category>('POST', '/categories', data)
}
export async function updateCategory(id: string, data: Partial<Category>): Promise<Category> {
  if (USE_MOCK) { await delay(); return { ...data, id } as Category }
  return http<Category>('PUT', `/categories/${id}`, data)
}
export async function deleteCategory(id: string): Promise<void> {
  if (USE_MOCK) { await delay(); return }
  return http<void>('DELETE', `/categories/${id}`)
}

// Subcategories
export async function getSubcategories(): Promise<Subcategory[]> {
  if (USE_MOCK) { await delay(); return mockSubcategories }
  return http<Subcategory[]>('GET', '/subcategories')
}
export async function deleteSubcategory(id: string): Promise<{ ok: boolean }> {
  return http('DELETE', `/subcategories/${id}`)
}
export async function createSubcategory(name: string): Promise<Subcategory> {
  if (USE_MOCK) {
    await delay()
    return mockSubcategories.find(s => s.name.toUpperCase() === name.toUpperCase())
      || { id: Date.now().toString(), name: name.toUpperCase() }
  }
  return http<Subcategory>('POST', '/subcategories', { name })
}

// Transactions
export async function getTransactions(filters: TransactionFilters = {}): Promise<PaginatedResponse<Transaction>> {
  if (USE_MOCK) {
    await delay()
    let items = [...mockTransactions]
    if (filters.status) items = items.filter(t => t.status === filters.status)
    if (filters.type) items = items.filter(t => t.type === filters.type)
    if (filters.search) items = items.filter(t => t.description.toLowerCase().includes(filters.search!.toLowerCase()))
    if (filters.competence_month) items = items.filter(t => t.competence_month === filters.competence_month)
    if (filters.account_id) items = items.filter(t => t.account_id === filters.account_id)

    const page = filters.page || 1, ps = filters.page_size || 100
    const total = items.length
    const summary: TransactionSummary = {
      total_income: items.filter(t => t.type === 'income').reduce((s, t) => s + t.amount, 0),
      total_expense: items.filter(t => t.type === 'expense').reduce((s, t) => s + t.amount, 0),
      balance: items.reduce((s, t) => s + t.amount, 0),
      pending_count: items.filter(t => t.status === 'pending').length,
      reconciled_count: items.filter(t => t.status === 'reconciled').length,
    }
    return { items: items.slice((page - 1) * ps, page * ps), total, page, page_size: ps, total_pages: Math.ceil(total / ps), summary }
  }
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([k, v]) => v !== undefined && v !== '' && params.set(k, String(v)))
  return http<PaginatedResponse<Transaction>>('GET', `/transactions?${params}`)
}

export async function classifyTransaction(id: string, data: { category_id: string; subcategory_id?: string | null; notes?: string; classification_source?: 'manual' | 'auto' | 'identity'; apply_to_installments?: boolean }): Promise<Transaction & { affected_ids?: string[]; affected_count?: number; installment_plan_id?: string | null }> {
  if (USE_MOCK) {
    await delay()
    const t = mockTransactions.find(x => x.id === id)!
    const status = data.classification_source === 'auto' ? 'auto_classified' : 'reconciled'
    return { ...t, ...data, status } as Transaction
  }
  return http<Transaction>('PATCH', `/transactions/${id}/classify`, data)
}

export async function updateTransactionFlags(id: string, flags: string): Promise<{ id: string; flags: string; flags_list: string[] }> {
  if (USE_MOCK) {
    await delay()
    const t = mockTransactions.find(x => x.id === id)
    if (t) t.flags = flags
    return { id, flags, flags_list: flags.split(',').map(flag => flag.trim()).filter(Boolean) }
  }
  return http('PATCH', `/transactions/${id}/flags`, { flags })
}

export async function unlinkHistoricalMatch(id: string): Promise<{ id: string; ok: boolean }> {
  if (USE_MOCK) { await delay(); return { id, ok: true } }
  return http('PATCH', `/transactions/${id}/unlink-history`, {})
}

export async function getTransactionSuggestions(id: string): Promise<Array<{
  category_id: string
  category_name: string
  subcategory_id: string | null
  subcategory_name: string
  best_notes?: string
  probability: number
  category_probability: number
  subcategory_probability: number
  frequency: number
  history_evidence: number
  transaction_evidence: number
  justification: string
}>> {
  if (USE_MOCK) {
    await delay()
    return []
  }
  return http('GET', `/transactions/${id}/suggestions`)
}

export async function recalculateProbabilities(): Promise<{ job_id: string; status: string }> {
  if (USE_MOCK) { await delay(800); return { job_id: 'mock-job', status: 'queued' } }
  return http('POST', '/transactions/recalculate-probabilities', {})
}

export interface RecalculationJob {
  id: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  processed: number
  total: number
  updated: number
  error: string
}

export async function getRecalculationJob(id: string): Promise<RecalculationJob> {
  return http('GET', `/recalculation-jobs/${id}`)
}

export async function clearTransactionLinks(): Promise<{ updated: number }> {
  if (USE_MOCK) { await delay(500); return { updated: 12 } }
  return http('POST', '/transactions/clear-links', {})
}

export async function clearTransactionClassifications(): Promise<{ updated: number; manual_history_deleted: number }> {
  if (USE_MOCK) { await delay(500); return { updated: 12, manual_history_deleted: 0 } }
  return http('POST', '/transactions/clear-classifications', {})
}

export async function autoClassifyByProbability(
  min_probability: number,
  filters: TransactionFilters = {}
): Promise<{ updated: number; min_probability: number }> {
  if (USE_MOCK) { await delay(800); return { updated: 12, min_probability } }
  return http('POST', '/transactions/auto-classify', { min_probability, filters })
}

export async function bulkVincular(threshold: number, filters?: {
  account_id?: string
  competence_month?: string
}): Promise<{ vinculados: number; total_candidatos: number }> {
  if (USE_MOCK) { await delay(800); return { vinculados: 10, total_candidatos: 12 } }
  return http('POST', '/transactions/bulk-vincular', { threshold, ...filters })
}

export interface HistoryFilters {
  page?: number
  page_size?: number
  type?: string
  linked?: string
  sheet?: string
  search?: string
  account_id?: string
  category_id?: string
  subcategory_id?: string
  sort_by?: string
  sort_order?: 'asc' | 'desc'
}

export interface HistoryItem {
  id: string
  date: string
  description: string
  amount: number
  type: 'income' | 'expense'
  account_id?: string | null
  account_name?: string
  category_id: string
  category_name: string
  category_color?: string
  subcategory_id?: string | null
  subcategory_name?: string
  source_file_id: string
  seed_sheet?: string
  linked_tx_id?: string | null
  linked_tx_description?: string | null
  linked_tx_date?: string | null
  linked_tx_amount?: number | null
}

export async function getHistory(filters: HistoryFilters = {}): Promise<PaginatedResponse<HistoryItem>> {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([k, v]) => v !== undefined && v !== '' && params.set(k, String(v)))
  return http<PaginatedResponse<HistoryItem>>('GET', `/history?${params}`)
}

export async function bulkClassify(ids: string[], category_id: string, subcategory_id?: string): Promise<{ updated: number; skipped_locked?: number }> {
  if (USE_MOCK) { await delay(); return { updated: ids.length } }
  return http<{ updated: number; skipped_locked?: number }>('PATCH', '/transactions/bulk-classify', { ids, category_id, subcategory_id })
}

export async function updateTransactionStatus(id: string, status: string): Promise<Transaction> {
  if (USE_MOCK) { await delay(); const t = mockTransactions.find(x => x.id === id)!; return { ...t, status: status as any } }
  return http<Transaction>('PATCH', `/transactions/${id}/status`, { status })
}

export async function deleteTransaction(id: string): Promise<void> {
  if (USE_MOCK) { await delay(); return }
  return http<void>('DELETE', `/transactions/${id}`)
}

export async function getMonths(): Promise<string[]> {
  if (USE_MOCK) { await delay(); return mockMonths }
  return http<string[]>('GET', '/transactions/months')
}

// Import
export async function importFile(file: File, account_id?: string, confirmDuplicates?: boolean): Promise<ImportResult> {
  if (USE_MOCK) {
    await delay(1200)
    return {
      imported_file_id: Date.now().toString(),
      filename: file.name,
      account_name: mockAccounts.find(a => a.id === account_id)?.name || '',
      total_parsed: 45,
      total_inserted: 43,
      total_duplicates: 2,
      total_errors: 0,
      transactions_preview: mockTransactions.slice(0, 5),
    }
  }
  const form = new FormData()
  form.append('file', file)
  if (account_id) form.append('account_id', account_id)
  if (confirmDuplicates) form.append('confirm_duplicates', '1')
  const res = await fetch(`${BASE}/import/upload`, { method: 'POST', body: form, headers: authHeaders() })
  if (!res.ok) { const err = await res.json().catch(() => ({})); throw { status: res.status, ...err } }
  return res.json()
}


export async function previewImportFile(file: File, account_id?: string): Promise<ImportPreviewResult> {
  if (USE_MOCK) {
    await delay(600)
    const detectedAccount = mockAccounts.find(a => a.id === account_id) || mockAccounts[0]
    return {
      preview_id: Date.now().toString(),
      filename: file.name,
      account_id: detectedAccount.id,
      account_name: detectedAccount.name,
      account_detection: {
        bank: 'XP', account_type: detectedAccount.type,
        suggested_account_id: detectedAccount.id, suggested_account_name: detectedAccount.name,
        selected_account_id: detectedAccount.id, selected_account_name: detectedAccount.name,
        confidence: 96, evidence: ['Nome e conteudo identificam a conta'],
        selection_source: account_id ? 'manual' : 'automatic', conflict: false,
      },
      detected_type: 'CARTAO XP',
      detection_confidence: 96.5,
      total_parsed: 45,
      duplicates_db: 2,
      duplicates_internal: 1,
      new_records: 43,
      rows: mockTransactions.slice(0, 20).map((t, i) => ({
        date: t.date,
        description: t.description,
        amount: t.amount,
        type: t.type,
        duplicate_db: i % 12 === 0,
        duplicate_internal: i % 17 === 0,
        occurrence: 1,
      })),
    }
  }
  const form = new FormData()
  form.append('file', file)
  if (account_id) form.append('account_id', account_id)
  const res = await fetch(`${BASE}/import/preview`, { method: 'POST', body: form, headers: authHeaders() })
  if (!res.ok) { const err = await res.json().catch(() => ({})); throw { status: res.status, ...err } }
  return res.json()
}

export async function commitImportPreview(preview_id: string, confirm_duplicates = true, competence_month = ''): Promise<ImportResult> {
  if (USE_MOCK) {
    await delay(700)
    return {
      imported_file_id: Date.now().toString(),
      filename: 'mock.csv',
      account_name: 'CONTA XP',
      total_parsed: 45,
      total_inserted: 43,
      total_duplicates: 2,
      total_errors: 0,
      transactions_preview: mockTransactions.slice(0, 5),
    }
  }
  return http<ImportResult>('POST', '/import/commit', { preview_id, confirm_duplicates, competence_month })
}

export interface SeedImportJob {
  id: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  filename: string
  result: ImportResult | null
  error: string
  phase: string
  processed: number
  total: number
  message: string
  logs: Array<{ time: string; message: string }>
}

export async function importSeedFile(file: File): Promise<{ job_id: string; status: string; filename: string }> {
  if (USE_MOCK) {
    await delay(1200)
    return { job_id: 'mock-seed-job', status: 'queued', filename: file.name }
  }
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${BASE}/import/seed`, { method: 'POST', body: form, headers: authHeaders() })
  if (!res.ok) { const err = await res.json().catch(() => ({})); throw { status: res.status, ...err } }
  return res.json()
}

export async function getSeedImportJob(id: string): Promise<SeedImportJob> {
  return http('GET', `/seed-import-jobs/${id}`)
}

export async function getActiveSeedImportJob(): Promise<SeedImportJob | null> {
  try {
    return await http('GET', '/seed-import-jobs-active')
  } catch (error: any) {
    if (error?.status === 404) return null
    throw error
  }
}

export interface CoverageFile {
  filename: string
  path: string
  doc_id?: string
  size: number
  modified_at: string
}

export async function systemReset(scope: 'transactions' | 'all', wipe_categories = false): Promise<{ ok: boolean; deleted: Record<string, number> }> {
  return http('POST', '/system/reset', { confirm: 'RESETAR', scope, wipe_categories })
}

export async function downloadDocument(docId: string, filename: string): Promise<void> {
  const res = await fetch(`${BASE}/documents/${docId}/download`, { headers: authHeaders() })
  if (!res.ok) throw { status: res.status, detail: 'Erro ao baixar arquivo' }
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export interface CoverageCell {
  status: 'imported' | 'missing' | 'dispensed' | 'future'
  file_count: number
  reason?: string
}

export interface CoverageAccount {
  id: string
  name: string
  type: string
  color: string
  folder: string
  cells: Record<string, CoverageCell>
}

export interface CoverageResponse {
  year: number
  available_years: number[]
  months: string[]
  matrix: Record<string, CoverageAccount>
}

export async function reviewHistoricalMatch(id: string, action: 'confirm' | 'reject'): Promise<{
  id: string
  history_match_id: string | null
  history_match_confirmed: boolean
  category_id?: string | null
  subcategory_id?: string | null
  status?: 'reconciled'
  locked?: boolean
  classified_by?: string
  classified_at?: string
  ok: boolean
}> {
  if (USE_MOCK) { await delay(); return { id, history_match_id: action === 'confirm' ? 'mock-history' : null, history_match_confirmed: action === 'confirm', ok: true } }
  return http('POST', `/transactions/${id}/history-link`, { action })
}

export async function getCoverage(year = 2026): Promise<CoverageResponse> {
  return http<CoverageResponse>('GET', `/coverage?year=${encodeURIComponent(year)}`)
}

export async function getCoverageFiles(account_id: string, year_month: string): Promise<{ files: CoverageFile[] }> {
  const params = new URLSearchParams({ account_id, year_month })
  return http<{ files: CoverageFile[] }>('GET', `/coverage/files?${params}`)
}

export async function deleteCoverageFile(path: string): Promise<{
  ok: boolean
  deleted_file: string
  deleted_imported_files: number
  deleted_transactions: number
}> {
  return http('DELETE', '/coverage/files', { path })
}

export async function dispenseCoverage(account_id: string, year_month: string, reason = ''): Promise<{ ok: boolean }> {
  return http<{ ok: boolean }>('POST', '/coverage/dispense', { account_id, year_month, reason })
}

export async function undoDispenseCoverage(account_id: string, year_month: string): Promise<{ ok: boolean }> {
  return http<{ ok: boolean }>('DELETE', '/coverage/dispense', { account_id, year_month })
}

// Reports
export async function getReportSummary(params?: { competence_month?: string }): Promise<ReportSummary> {
  if (USE_MOCK) { await delay(); return mockSummary }
  const q = params?.competence_month ? `?competence_month=${params.competence_month}` : ''
  return http<ReportSummary>('GET', `/reports/summary${q}`)
}
export async function getReportByCategory(params?: { type?: string; competence_month?: string }): Promise<CategoryReport[]> {
  if (USE_MOCK) { await delay(); return params?.type ? mockCategoryReport : mockCategoryReport }
  const q = new URLSearchParams(params as any).toString()
  return http<CategoryReport[]>('GET', `/reports/by-category?${q}`)
}
export async function getReportMonthly(): Promise<MonthlyReport[]> {
  if (USE_MOCK) { await delay(); return mockMonthlyReport }
  return http<MonthlyReport[]>('GET', '/reports/monthly')
}


