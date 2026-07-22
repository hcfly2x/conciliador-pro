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
  const current = window.sessionStorage.getItem(TOKEN_KEY)
  if (current) return current
  const legacy = window.localStorage.getItem(TOKEN_KEY) || ''
  if (legacy) {
    window.sessionStorage.setItem(TOKEN_KEY, legacy)
    const legacyUser = window.localStorage.getItem(USER_KEY)
    if (legacyUser) window.sessionStorage.setItem(USER_KEY, legacyUser)
    window.localStorage.removeItem(TOKEN_KEY)
    window.localStorage.removeItem(USER_KEY)
  }
  return legacy
}
export function getStoredUser(): AuthUser | null {
  if (typeof window === 'undefined') return null
  try { return JSON.parse(window.sessionStorage.getItem(USER_KEY) || 'null') } catch { return null }
}
export function isAdmin(): boolean {
  return getStoredUser()?.role === 'admin'
}
function setSession(token: string, user: AuthUser) {
  window.sessionStorage.setItem(TOKEN_KEY, token)
  window.sessionStorage.setItem(USER_KEY, JSON.stringify(user))
}
export function clearSession() {
  if (typeof window === 'undefined') return
  window.sessionStorage.removeItem(TOKEN_KEY)
  window.sessionStorage.removeItem(USER_KEY)
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

async function http<T>(method: string, path: string, body?: unknown, timeoutMs = 30000): Promise<T> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs)
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...authHeaders() },
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    })
  } catch (error) {
    if ((error as { name?: string })?.name === 'AbortError') {
      throw { status: 408, detail: 'A requisicao demorou demais', code: 'REQUEST_TIMEOUT' }
    }
    throw error
  } finally {
    window.clearTimeout(timeout)
  }
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
  const user = await http<AuthUser>('GET', '/auth/me')
  if (typeof window !== 'undefined') window.sessionStorage.setItem(USER_KEY, JSON.stringify(user))
  return user
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

export interface TransactionSuggestion {
  category_id: string
  category_name: string
  subcategory_id: string | null
  subcategory_name: string
  best_notes?: string
  probability: number
  relative_score?: number
  confidence?: number
  category_probability: number
  subcategory_probability: number
  frequency: number
  history_evidence: number
  transaction_evidence: number
  justification: string
  rank?: number
  subcategories?: Array<{
    subcategory_id: string
    subcategory_name: string
    confidence: number
    frequency: number
  }>
}

export async function getTransactionSuggestions(id: string): Promise<TransactionSuggestion[]> {
  if (USE_MOCK) {
    await delay()
    return []
  }
  const response = await http<{ items: TransactionSuggestion[] }>('GET', `/transactions/${id}/suggestions`)
  return response.items
}

export interface SuggestionBatchResult {
  items: Record<string, TransactionSuggestion[]>
  states: Record<string, 'pending' | 'running' | 'completed' | 'failed'>
}

export async function getTransactionSuggestionsBatch(ids: string[]): Promise<SuggestionBatchResult> {
  if (USE_MOCK) { await delay(); return { items: Object.fromEntries(ids.map(id => [id, []])), states: Object.fromEntries(ids.map(id => [id, 'completed'])) } }
  return http<SuggestionBatchResult>(
    'POST', '/transactions/suggestions/batch', { transaction_ids: ids },
  )
}

export interface SuggestionJob {
  id: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  mode: 'incremental' | 'full'
  processed: number
  total: number
  updated: number
  with_suggestions: number
  without_suggestions: number
  message: string
  logs: Array<{ time: string; message: string }>
  error: string
  created_at: string
  started_at: string
  finished_at: string
}

export interface SuggestionSummary {
  pending: number
  links: number
  strong: number
  weak: number
  none: number
  waiting: number
  dismissed: number
  classified: number
}

export interface SuggestionEvaluation {
  generated_at: string
  eligible_total: number
  evaluated: number
  limit: number
  truncated: boolean
  with_suggestions: number
  coverage: number
  category: { top1_hits: number; top3_hits: number; top1_accuracy: number; top3_accuracy: number }
  subcategory: { labeled: number; evaluated: number; top1_hits: number; top3_hits: number; top1_accuracy: number; top3_accuracy: number }
  calibration: Array<{ range: string; count: number; accuracy: number; average_confidence: number }>
  by_type: Array<{ type: string; evaluated: number; with_suggestions: number; top1_hits: number; top3_hits: number; coverage: number; top1_accuracy: number; top3_accuracy: number }>
  methodology: string
}

export async function startSuggestionJob(full = false): Promise<{ job_id: string; status: string }> {
  return http('POST', '/transactions/suggestions/jobs', { full })
}

export async function getSuggestionJob(id: string): Promise<SuggestionJob> {
  return http('GET', `/suggestion-jobs/${id}`)
}

export async function getActiveSuggestionJob(): Promise<SuggestionJob | null> {
  try { return await http('GET', '/suggestion-jobs-active') }
  catch (error) { if ((error as { status?: number }).status === 404) return null; throw error }
}

export async function getSuggestionSummary(): Promise<SuggestionSummary> {
  return http('GET', '/transactions/suggestions/summary')
}

export async function getSuggestionEvaluation(limit = 250): Promise<SuggestionEvaluation> {
  return http('GET', `/transactions/suggestions/evaluation?limit=${limit}`)
}

export async function dismissTransactionSuggestions(id: string): Promise<{ id: string; dismissed: boolean }> {
  return http('POST', `/transactions/${id}/suggestions/dismiss`, {})
}

export async function recalculateProbabilities(): Promise<{ job_id: string; status: string }> {
  if (USE_MOCK) { await delay(800); return { job_id: 'mock-job', status: 'queued' } }
  return http('POST', '/transactions/recalculate-history-links', {})
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

export async function bulkClassify(ids: string[], category_id: string, subcategory_id?: string): Promise<{ updated: number; skipped_locked?: number; skipped_history_links?: number }> {
  if (USE_MOCK) { await delay(); return { updated: ids.length } }
  return http<{ updated: number; skipped_locked?: number; skipped_history_links?: number }>('PATCH', '/transactions/bulk-classify', { ids, category_id, subcategory_id })
}

export async function downloadAuditExport(): Promise<{ filename: string; dataUrl: string }> {
  const res = await fetch(`${BASE}/system/audit-export`, { headers: authHeaders() })
  if (res.status === 401) {
    handleUnauthorized()
    throw { status: 401, detail: 'Não autenticado', code: 'UNAUTHORIZED' }
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw { status: res.status, ...err }
  }
  const blob = await res.blob()
  const disposition = res.headers.get('content-disposition') || ''
  const match = disposition.match(/filename\*?=(?:UTF-8''|\")?([^\";]+)/i)
  const filename = match ? decodeURIComponent(match[1]) : 'production-audit.zip'
  const url = window.URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.URL.revokeObjectURL(url)
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(blob)
  })
  return { filename, dataUrl }
}

export async function getMonths(): Promise<string[]> {
  if (USE_MOCK) { await delay(); return mockMonths }
  return http<string[]>('GET', '/transactions/months')
}

export interface ReconciliationTransaction {
  id: string
  date: string
  description: string
  amount: number
  type: 'income' | 'expense'
  account_id: string
  account_name: string
  status: string
}

export interface ReconciliationCandidate {
  expense: ReconciliationTransaction
  income: ReconciliationTransaction
  amount: number
  date_difference_days: number
}

export interface ReconciliationRecord {
  id: string
  expense: ReconciliationTransaction
  income: ReconciliationTransaction
  amount: number
  created_by: string
  created_at: string
}

export async function getReconciliations(view: 'candidates' | 'completed', search = ''): Promise<{ items: Array<ReconciliationCandidate | ReconciliationRecord> }> {
  if (USE_MOCK) { await delay(); return { items: [] } }
  const params = new URLSearchParams({ view })
  if (search) params.set('search', search)
  return http('GET', `/reconciliations?${params}`)
}

export async function createReconciliation(expense_transaction_id: string, income_transaction_id: string): Promise<{ id: string }> {
  return http('POST', '/reconciliations', { expense_transaction_id, income_transaction_id })
}

export async function undoReconciliation(id: string): Promise<{ id: string; ok: boolean }> {
  return http('POST', `/reconciliations/${id}/undo`, {})
}

// Importacao sempre usa preview e confirmacao.
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

export interface DocumentImportJob {
  id: string
  preview_id: string
  filename: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  phase: string
  processed: number
  total: number
  message: string
  logs: Array<{ time: string; message: string }>
  result: ImportResult | null
  error: string
  created_at: string
  started_at: string
  finished_at: string
}

export async function commitImportPreview(preview_id: string, confirm_duplicates = true, competence_month = ''): Promise<{ job_id: string; status: string }> {
  if (USE_MOCK) {
    await delay(700)
    return { job_id: 'mock-document-import', status: 'queued' }
  }
  return http<{ job_id: string; status: string }>('POST', '/import/commit', { preview_id, confirm_duplicates, competence_month })
}

export async function getDocumentImportJob(id: string): Promise<DocumentImportJob> {
  if (USE_MOCK) {
    await delay(700)
    return {
      id, preview_id: 'mock-preview', filename: 'mock.csv', status: 'completed', error: '',
      phase: 'completed', processed: 45, total: 45, message: 'Importacao concluida', logs: [],
      created_at: '', started_at: '', finished_at: '',
      result: {
        imported_file_id: Date.now().toString(), filename: 'mock.csv', account_name: 'CONTA XP',
        total_parsed: 45, total_inserted: 43, total_duplicates: 2, total_errors: 0,
        transactions_preview: mockTransactions.slice(0, 5),
      },
    }
  }
  return http<DocumentImportJob>('GET', `/import/jobs/${id}`)
}

export async function waitForDocumentImportJob(id: string, onProgress?: (job: DocumentImportJob) => void): Promise<DocumentImportJob> {
  for (;;) {
    try {
      const job = await getDocumentImportJob(id)
      onProgress?.(job)
      if (job.status === 'completed' || job.status === 'failed') return job
    } catch (error: any) {
      if (error?.status === 401 || error?.status === 404) throw error
    }
    await delay(1500)
  }
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

export async function importSeedFile(file: File, replaceExisting = false): Promise<{ job_id: string; status: string; filename: string }> {
  if (USE_MOCK) {
    await delay(1200)
    return { job_id: 'mock-seed-job', status: 'queued', filename: file.name }
  }
  const form = new FormData()
  form.append('file', file)
  if (replaceExisting) {
    form.append('replace_existing', 'true')
    form.append('replace_confirmation', 'SUBSTITUIR BASE HISTORICA')
  }
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
  affected_ids?: string[]
  affected_count?: number
  ok: boolean
}> {
  if (USE_MOCK) { await delay(); return { id, history_match_id: action === 'confirm' ? 'mock-history' : null, history_match_confirmed: action === 'confirm', ok: true } }
  return http('POST', `/transactions/${id}/history-link`, { action })
}

export interface HistoryLinkBatchResult {
  selected: number
  matched: number
  manual_review: number
  without_match: number
  skipped: number
  failed: number
  matched_ids: string[]
  manual_review_ids: string[]
  without_match_ids: string[]
  skipped_ids: string[]
  failed_ids: string[]
  affected_ids: string[]
  operation_id: string
  duration_ms: number
  logs: Array<{ time: string; message: string }>
}

export async function prepareHistoricalLinks(ids: string[]): Promise<HistoryLinkBatchResult> {
  if (USE_MOCK) { await delay(); return { selected: ids.length, matched: ids.length, manual_review: 0, without_match: 0, skipped: 0, failed: 0, matched_ids: ids, manual_review_ids: [], without_match_ids: [], skipped_ids: [], failed_ids: [], affected_ids: ids, operation_id: 'mock', duration_ms: 250, logs: [{ time: new Date().toLocaleTimeString('pt-BR'), message: `Lote concluido: ${ids.length} confirmado(s)` }] } }
  return http('POST', '/transactions/history-links/batch', { ids }, 120000)
}

export async function getCoverage(year = 2026): Promise<CoverageResponse> {
  return http<CoverageResponse>('GET', `/coverage?year=${encodeURIComponent(year)}`)
}

export async function getCoverageFiles(account_id: string, year_month: string): Promise<{ files: CoverageFile[] }> {
  const params = new URLSearchParams({ account_id, year_month })
  return http<{ files: CoverageFile[] }>('GET', `/coverage/files?${params}`)
}

export async function deleteCoverageFile(path: string, deleteTransactions = false): Promise<{
  ok: boolean
  deleted_file: string
  deleted_imported_files: number
  deleted_transactions: number
}> {
  return http('DELETE', '/coverage/files', {
    path,
    delete_transactions: deleteTransactions,
    ...(deleteTransactions && { confirm_delete_transactions: 'EXCLUIR LANCAMENTOS' }),
  })
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


