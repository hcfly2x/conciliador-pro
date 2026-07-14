import type { Account, Category, Subcategory, Transaction, ReportSummary, CategoryReport, MonthlyReport } from '@/types'

export const mockAccounts: Account[] = [
  { id: '1', name: 'CONTA SANTANDER', type: 'checking', color: '#2563eb', is_active: true, created_at: '2024-01-01T00:00:00' },
  { id: '2', name: 'CARTÃO XP', type: 'credit_card', color: '#7c3aed', is_active: true, created_at: '2024-01-01T00:00:00' },
  { id: '3', name: 'CARTÃO NUBANK', type: 'credit_card', color: '#8b5cf6', is_active: true, created_at: '2024-01-01T00:00:00' },
  { id: '4', name: 'CARTÃO SULIVAN', type: 'credit_card', color: '#0d9488', is_active: true, created_at: '2024-01-01T00:00:00' },
]

export const mockCategories: Category[] = [
  { id: '1',  name: 'GASTO PESSOAL',        color: '#dc2626', text_color: '#fff', type: 'expense' },
  { id: '2',  name: 'CASA NOVA',             color: '#16a34a', text_color: '#fff', type: 'expense' },
  { id: '3',  name: 'CASA ANTIGA',           color: '#15803d', text_color: '#fff', type: 'expense' },
  { id: '4',  name: 'COMPRA SPEED',          color: '#d97706', text_color: '#fff', type: 'expense' },
  { id: '5',  name: 'PAG CARTÃO',            color: '#7c3aed', text_color: '#fff', type: 'expense' },
  { id: '6',  name: 'REEMBOLSADO SMTK',      color: '#2563eb', text_color: '#fff', type: 'income' },
  { id: '7',  name: 'GASTO PESSOAL VIAGEM',  color: '#db2777', text_color: '#fff', type: 'expense' },
  { id: '8',  name: 'INVESTIMENTO',          color: '#0d9488', text_color: '#fff', type: 'expense' },
  { id: '9',  name: 'SALÁRIO',               color: '#22c55e', text_color: '#fff', type: 'income' },
  { id: '10', name: 'POKER',                 color: '#f59e0b', text_color: '#111', type: 'expense' },
  { id: '11', name: 'PAI',                   color: '#64748b', text_color: '#fff', type: 'expense' },
  { id: '12', name: 'SMARTEK',               color: '#3b82f6', text_color: '#fff', type: 'expense' },
  { id: '13', name: 'NÃO SEI',               color: '#6b7280', text_color: '#fff', type: 'expense' },
  { id: '14', name: 'ENTRE CONTAS',          color: '#94a3b8', text_color: '#111', type: 'income' },
  { id: '15', name: 'DEPOSITO SMTK',         color: '#06b6d4', text_color: '#111', type: 'income' },
  { id: '16', name: 'GASTOS SPEED',          color: '#ea580c', text_color: '#fff', type: 'expense' },
]

export const mockSubcategories: Subcategory[] = [
  { id: '1',  name: 'COMIDA/BEBIDA' },
  { id: '2',  name: 'GASOLINA' },
  { id: '3',  name: 'UBER' },
  { id: '4',  name: 'FARMÁCIA' },
  { id: '5',  name: 'IOF' },
  { id: '6',  name: 'PEDÁGIO' },
  { id: '7',  name: 'ASSINATURA' },
  { id: '8',  name: 'IMPLANTE' },
  { id: '9',  name: 'VIAGEM PESSOAL' },
  { id: '10', name: 'TARIFA BANCO' },
  { id: '11', name: 'CONFRA BARMAN' },
  { id: '12', name: 'CONFRA MERCADO' },
  { id: '13', name: 'POSTO' },
  { id: '14', name: 'JUROS' },
  { id: '15', name: 'PREVIDÊNCIA' },
]

export const mockTransactions: Transaction[] = [
  { id: '1',  date: '2026-01-13', competence_month: '2026/01', description: 'PIX PARA MARISA CARNEIRO CAIXA', amount: -11000, type: 'expense', status: 'pending', account_id: '1', account_name: 'CONTA SANTANDER', account_color: '#2563eb', category_id: null, category_name: null, category_color: null, category_text_color: null, subcategory_id: null, subcategory_name: null, notes: '', imported_file_id: 'f1' },
  { id: '2',  date: '2026-01-12', competence_month: '2026/01', description: 'PIX ENVIADO Felipe Junqueira de Souza', amount: -200, type: 'expense', status: 'reconciled', account_id: '1', account_name: 'CONTA SANTANDER', account_color: '#2563eb', category_id: '6', category_name: 'REEMBOLSADO SMTK', category_color: '#2563eb', category_text_color: '#fff', subcategory_id: '11', subcategory_name: 'CONFRA BARMAN', notes: 'Confra barman', imported_file_id: 'f1' },
  { id: '3',  date: '2026-01-12', competence_month: '2026/01', description: 'PIX ENVIADO Felipe Junqueira de Souza', amount: -350, type: 'expense', status: 'reconciled', account_id: '1', account_name: 'CONTA SANTANDER', account_color: '#2563eb', category_id: '6', category_name: 'REEMBOLSADO SMTK', category_color: '#2563eb', category_text_color: '#fff', subcategory_id: '11', subcategory_name: 'CONFRA BARMAN', notes: '', imported_file_id: 'f1' },
  { id: '4',  date: '2026-01-12', competence_month: '2026/01', description: 'PAGAMENTO DE BOLETO OUTROS BANCOS FGR URBANISMO', amount: -4579.18, type: 'expense', status: 'reconciled', account_id: '1', account_name: 'CONTA SANTANDER', account_color: '#2563eb', category_id: '3', category_name: 'CASA ANTIGA', category_color: '#15803d', category_text_color: '#fff', subcategory_id: null, subcategory_name: null, notes: 'COLOCAR NO SALDO DEVEDOR', imported_file_id: 'f1' },
  { id: '5',  date: '2026-01-12', competence_month: '2026/01', description: 'DEBITO AUT. FATURA CARTAO VISA FINAL 5588', amount: -14944.69, type: 'expense', status: 'reconciled', account_id: '1', account_name: 'CONTA SANTANDER', account_color: '#2563eb', category_id: '5', category_name: 'PAG CARTÃO', category_color: '#7c3aed', category_text_color: '#fff', subcategory_id: null, subcategory_name: null, notes: '', imported_file_id: 'f1' },
  { id: '6',  date: '2026-01-12', competence_month: '2026/01', description: 'TARIFA MENSALIDADE PACOTE SERVICOS DEZEMBRO / 2025', amount: -99.95, type: 'expense', status: 'reconciled', account_id: '1', account_name: 'CONTA SANTANDER', account_color: '#2563eb', category_id: '1', category_name: 'GASTO PESSOAL', category_color: '#dc2626', category_text_color: '#fff', subcategory_id: '10', subcategory_name: 'TARIFA BANCO', notes: '', imported_file_id: 'f1' },
  { id: '7',  date: '2026-01-10', competence_month: '2026/01', description: 'OESTE CARNES', amount: -731.45, type: 'expense', status: 'reconciled', account_id: '2', account_name: 'CARTÃO XP', account_color: '#7c3aed', category_id: '6', category_name: 'REEMBOLSADO SMTK', category_color: '#2563eb', category_text_color: '#fff', subcategory_id: '12', subcategory_name: 'CONFRA MERCADO', notes: '', imported_file_id: 'f2' },
  { id: '8',  date: '2026-01-10', competence_month: '2026/01', description: 'OESTE CARNES', amount: -731.45, type: 'expense', status: 'duplicate', account_id: '2', account_name: 'CARTÃO XP', account_color: '#7c3aed', category_id: null, category_name: null, category_color: null, category_text_color: null, subcategory_id: null, subcategory_name: null, notes: '', imported_file_id: 'f2' },
  { id: '9',  date: '2026-01-10', competence_month: '2026/01', description: 'GREMIO RECREATIVO', amount: -230, type: 'expense', status: 'pending', account_id: '2', account_name: 'CARTÃO XP', account_color: '#7c3aed', category_id: null, category_name: null, category_color: null, category_text_color: null, subcategory_id: null, subcategory_name: null, notes: '', imported_file_id: 'f2' },
  { id: '10', date: '2026-01-09', competence_month: '2026/01', description: 'JIM.COM ENGENHARIA DAS LAVANDEIRAS', amount: -8800, type: 'expense', status: 'reconciled', account_id: '2', account_name: 'CARTÃO XP', account_color: '#7c3aed', category_id: '2', category_name: 'CASA NOVA', category_color: '#16a34a', category_text_color: '#fff', subcategory_id: null, subcategory_name: null, notes: '', imported_file_id: 'f2' },
  { id: '11', date: '2026-01-09', competence_month: '2026/01', description: 'LINK LIC LOURENCO INDUSTRIA', amount: -4270, type: 'expense', status: 'reconciled', account_id: '2', account_name: 'CARTÃO XP', account_color: '#7c3aed', category_id: '2', category_name: 'CASA NOVA', category_color: '#16a34a', category_text_color: '#fff', subcategory_id: null, subcategory_name: null, notes: '', imported_file_id: 'f2' },
  { id: '12', date: '2026-01-09', competence_month: '2026/01', description: 'MINIBOXPREMIUM', amount: -29.28, type: 'expense', status: 'pending', account_id: '2', account_name: 'CARTÃO XP', account_color: '#7c3aed', category_id: null, category_name: null, category_color: null, category_text_color: null, subcategory_id: null, subcategory_name: null, notes: '', imported_file_id: 'f2' },
  { id: '13', date: '2026-01-09', competence_month: '2026/01', description: 'PIX ENVIADO Leandro da Silveira Campo', amount: -2900, type: 'expense', status: 'reconciled', account_id: '1', account_name: 'CONTA SANTANDER', account_color: '#2563eb', category_id: '1', category_name: 'GASTO PESSOAL', category_color: '#dc2626', category_text_color: '#fff', subcategory_id: '8', subcategory_name: 'IMPLANTE', notes: 'Implante dental', imported_file_id: 'f1' },
  { id: '14', date: '2026-01-07', competence_month: '2026/01', description: 'PIX ENVIADO Nu Pagamentos S A', amount: -2370.31, type: 'expense', status: 'reconciled', account_id: '1', account_name: 'CONTA SANTANDER', account_color: '#2563eb', category_id: '5', category_name: 'PAG CARTÃO', category_color: '#7c3aed', category_text_color: '#fff', subcategory_id: null, subcategory_name: null, notes: '', imported_file_id: 'f1' },
  { id: '15', date: '2026-01-06', competence_month: '2026/01', description: 'ALIEXPRESS', amount: -660.47, type: 'expense', status: 'reconciled', account_id: '2', account_name: 'CARTÃO XP', account_color: '#7c3aed', category_id: '4', category_name: 'COMPRA SPEED', category_color: '#d97706', category_text_color: '#fff', subcategory_id: null, subcategory_name: null, notes: '', imported_file_id: 'f2' },
  { id: '16', date: '2026-01-05', competence_month: '2026/01', description: 'PIX ENVIADO Helcio Carneiro de Avila', amount: -20000, type: 'expense', status: 'reconciled', account_id: '1', account_name: 'CONTA SANTANDER', account_color: '#2563eb', category_id: '8', category_name: 'INVESTIMENTO', category_color: '#0d9488', category_text_color: '#fff', subcategory_id: null, subcategory_name: null, notes: '', imported_file_id: 'f1' },
]

export const mockMonths = ['2026/01', '2025/12', '2025/11', '2025/10', '2025/09', '2025/08', '2025/07']

export const mockSummary: ReportSummary = {
  total_transactions: 342,
  pending: 28,
  reconciled: 312,
  total_income: 55014.47,
  total_expense: -125430.50,
  balance: -70416.03,
}

export const mockCategoryReport: CategoryReport[] = [
  { category_id: '1',  category_name: 'GASTO PESSOAL',  category_color: '#dc2626', total: -45230, count: 187, percentage: 36.1 },
  { category_id: '5',  category_name: 'PAG CARTÃO',      category_color: '#7c3aed', total: -30791, count: 12,  percentage: 24.5 },
  { category_id: '2',  category_name: 'CASA NOVA',        category_color: '#16a34a', total: -18000, count: 14,  percentage: 14.3 },
  { category_id: '4',  category_name: 'COMPRA SPEED',     category_color: '#d97706', total: -9500,  count: 23,  percentage: 7.6  },
  { category_id: '8',  category_name: 'INVESTIMENTO',     category_color: '#0d9488', total: -7000,  count: 4,   percentage: 5.6  },
  { category_id: '7',  category_name: 'GASTO PESSOAL VIAGEM', category_color: '#db2777', total: -6200, count: 31, percentage: 4.9 },
  { category_id: '3',  category_name: 'CASA ANTIGA',      category_color: '#15803d', total: -4579,  count: 3,   percentage: 3.6  },
  { category_id: '16', category_name: 'GASTOS SPEED',     category_color: '#ea580c', total: -3200,  count: 18,  percentage: 2.5  },
  { category_id: null, category_name: 'Sem categoria',    category_color: '#374151', total: -1130,  count: 8,   percentage: 0.9  },
]

export const mockMonthlyReport: MonthlyReport[] = [
  { month: '2026/01', income: 55014, expense: -45230, balance: 9784,   transaction_count: 74  },
  { month: '2025/12', income: 25000, expense: -67890, balance: -42890, transaction_count: 156 },
  { month: '2025/11', income: 20000, expense: -52300, balance: -32300, transaction_count: 142 },
  { month: '2025/10', income: 15000, expense: -48100, balance: -33100, transaction_count: 138 },
  { month: '2025/09', income: 22000, expense: -61200, balance: -39200, transaction_count: 165 },
  { month: '2025/08', income: 18000, expense: -58900, balance: -40900, transaction_count: 149 },
  { month: '2025/07', income: 20000, expense: -55400, balance: -35400, transaction_count: 131 },
]
