import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import path from 'node:path'

const backend = 'http://127.0.0.1:5061/api/v1'
const credentials = { username: 'e2e-admin', password: 'e2e-password-123' }

async function apiLogin(request: APIRequestContext) {
  const response = await request.post(`${backend}/auth/login`, { data: credentials })
  expect(response.ok()).toBeTruthy()
  return (await response.json()).token as string
}

async function resetApplication(request: APIRequestContext) {
  const token = await apiLogin(request)
  const response = await request.post(`${backend}/system/reset`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { confirm: 'RESETAR', scope: 'all', wipe_categories: true },
  })
  expect(response.ok()).toBeTruthy()
  return token
}

async function login(page: Page) {
  await page.goto('/login')
  await page.getByLabel('Usuario').fill(credentials.username)
  await page.getByLabel('Senha').fill(credentials.password)
  await page.getByRole('button', { name: 'Entrar' }).click()
  await expect(page).toHaveURL('/')
  await expect(page.getByText('Lançamentos', { exact: true }).first()).toBeVisible()
}

async function importThroughUi(page: Page, fixture: string, accountName?: string, competenceMonth?: string) {
  await page.goto('/importar')
  await page.locator('input[type=file]').setInputFiles(fixture)
  if (accountName) await page.getByText('Conta / Cartão (opcional)').locator('..').getByRole('combobox').selectOption({ label: accountName })
  await page.getByRole('button', { name: 'Analisar arquivo' }).click()
  await expect(page.getByText('Pré-validação concluída')).toBeVisible()
  await expect(page.getByText('Novos para inserir')).toBeVisible()
  if (competenceMonth) {
    const [year, month] = competenceMonth.split('-')
    await page.getByLabel('Mês da competência').selectOption(month)
    await page.getByLabel('Ano da competência').selectOption(year)
  }
  const confirmButton = page.getByRole('button', { name: 'Confirmar importação' })
  await expect(confirmButton).toBeEnabled()
  const commitResponse = page.waitForResponse(response =>
    response.request().method() === 'POST' && response.url().includes('/api/v1/import/commit'),
  )
  await confirmButton.click()
  expect((await commitResponse).status()).toBe(202)
  await expect(page.getByText('Importação em processamento')).toBeVisible()
  await expect(page.getByText('Importação concluída')).toBeVisible({ timeout: 30_000 })
}

test.beforeEach(async ({ request }) => {
  await resetApplication(request)
})

test('protege paginas privadas e autentica o administrador', async ({ page }) => {
  await page.goto('/relatorios')
  await expect(page).toHaveURL(/\/login$/)

  await page.getByLabel('Usuario').fill('usuario-invalido')
  await page.getByLabel('Senha').fill('senha-invalida')
  await page.getByRole('button', { name: 'Entrar' }).click()
  await expect(page.getByText('Nao autenticado')).toBeVisible()

  await page.getByLabel('Usuario').fill(credentials.username)
  await page.getByLabel('Senha').fill(credentials.password)
  await page.getByRole('button', { name: 'Entrar' }).click()
  await expect(page).toHaveURL('/')
})

test('importa com preview e classifica um lancamento com bloqueio', async ({ page, request }) => {
  await login(page)
  const fixture = path.resolve(__dirname, '../../backend/tests/fixtures/imports/xp_card.csv')
  await importThroughUi(page, fixture, undefined, '2026-03')

  const token = await apiLogin(request)
  const categoryResponse = await request.post(`${backend}/categories`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { name: 'TESTE E2E', type: 'expense', color: '#334455', text_color: '#ffffff' },
  })
  expect(categoryResponse.ok()).toBeTruthy()

  await page.goto('/')
  const row = page.getByRole('row').filter({ hasText: 'LOJA ALFA' })
  await expect(row).toBeVisible()
  await row.locator('select').nth(0).selectOption({ label: 'TESTE E2E' })
  await row.getByRole('button', { name: 'Salvar e bloquear' }).click()
  await expect(row.getByText('Manual')).toBeVisible()
  await expect(row.locator('select').nth(0)).toBeDisabled()
})

test('concilia uma entrada com uma saida e permite desfazer', async ({ page }) => {
  await login(page)
  const fixture = path.resolve(__dirname, 'fixtures/reconciliation.csv')
  await importThroughUi(page, fixture, 'CONTA XP')

  await page.goto('/conciliacao')
  const candidate = page.getByRole('article').filter({ hasText: 'TRANSFERENCIA ENVIADA TESTE' })
  await expect(candidate).toContainText('TRANSFERENCIA RECEBIDA TESTE')
  page.once('dialog', dialog => dialog.accept())
  await candidate.getByRole('button', { name: 'Conciliar este par' }).click()

  await page.getByRole('button', { name: 'Ja conciliados' }).click()
  const completed = page.getByRole('article').filter({ hasText: 'TRANSFERENCIA ENVIADA TESTE' })
  await expect(completed).toContainText('Conciliado por e2e-admin')
  page.once('dialog', dialog => dialog.accept())
  await completed.getByRole('button', { name: 'Desfazer' }).click()
  await expect(page.getByText('Nenhuma conciliacao registrada.')).toBeVisible()
})
