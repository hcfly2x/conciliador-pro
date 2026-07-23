import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import path from 'node:path'
import { readFileSync } from 'node:fs'

test('frontend envia Content-Security-Policy', async ({ request }) => {
  const response = await request.get('/')
  expect(response.ok()).toBeTruthy()
  const csp = response.headers()['content-security-policy'] || ''
  expect(csp).toContain("default-src 'self'")
  expect(csp).toContain("frame-ancestors 'none'")
})

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

async function seedHistoricalLinks(request: APIRequestContext) {
  const token = await apiLogin(request)
  const headers = { Authorization: `Bearer ${token}` }
  for (const category of [
    { name: 'E2E VINCULO SAIDA', type: 'expense' },
    { name: 'E2E VINCULO ENTRADA', type: 'income' },
  ]) {
    const response = await request.post(`${backend}/categories`, {
      headers,
      data: { ...category, color: '#335577', text_color: '#ffffff' },
    })
    expect(response.status()).toBe(201)
  }

  const fixture = path.resolve(__dirname, 'fixtures/history-links.xlsx')
  const response = await request.post(`${backend}/import/seed`, {
    headers,
    multipart: {
      file: {
        name: 'history-links.xlsx',
        mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        buffer: readFileSync(fixture),
      },
    },
  })
  expect(response.status()).toBe(202)
  const jobId = (await response.json()).job_id as string
  let result: { status: string; result?: { total_inserted?: number }; error?: string } | undefined
  await expect.poll(async () => {
    const statusResponse = await request.get(`${backend}/seed-import-jobs/${jobId}`, { headers })
    expect(statusResponse.ok()).toBeTruthy()
    result = await statusResponse.json()
    return result?.status
  }, { timeout: 60_000 }).toBe('completed')
  expect(result?.result?.total_inserted).toBe(14)
}

async function login(page: Page) {
  await page.goto('/login')
  await page.getByLabel('Usuario').fill(credentials.username)
  await page.getByLabel('Senha').fill(credentials.password)
  const sessionValidated = page.waitForResponse(response =>
    response.request().method() === 'GET'
      && response.url().includes('/api/v1/auth/me')
      && response.status() === 200,
  )
  await page.getByRole('button', { name: 'Entrar' }).click()
  await expect(page).toHaveURL('/')
  await sessionValidated
  await expect(page.getByText('Lançamentos', { exact: true }).first()).toBeVisible()
}

async function importThroughUi(page: Page, fixture: string, accountName?: string, competenceMonth?: string) {
  await page.goto('/importar')
  await page.getByTestId('single-import-file').setInputFiles(fixture)
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
  await expect(page.getByText('Importação concluída')).toBeVisible({ timeout: 60_000 })
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

test('cofre remove somente o documento e preserva os lancamentos', async ({ page, request }) => {
  await login(page)
  const fixture = path.resolve(__dirname, '../../backend/tests/fixtures/imports/xp_card.csv')
  await importThroughUi(page, fixture, undefined, '2026-03')

  const token = await apiLogin(request)
  const headers = { Authorization: `Bearer ${token}` }
  const accountsResponse = await request.get(`${backend}/accounts`, { headers })
  expect(accountsResponse.ok()).toBeTruthy()
  const accounts = await accountsResponse.json() as Array<{ id: string; name: string }>
  const account = accounts.find(item => item.name === 'CARTAO XP')
  expect(account).toBeTruthy()

  const beforeResponse = await request.get(`${backend}/transactions?page_size=100&account_id=${account!.id}`, { headers })
  expect(beforeResponse.ok()).toBeTruthy()
  const before = await beforeResponse.json() as { total: number }
  expect(before.total).toBeGreaterThan(0)

  const filesResponse = await request.get(
    `${backend}/coverage/files?account_id=${account!.id}&year_month=2026%2F03`,
    { headers },
  )
  expect(filesResponse.ok()).toBeTruthy()
  const files = await filesResponse.json() as { files: Array<{ path: string }> }
  const storedDocument = files.files.find(file => file.path.startsWith('db://'))
  expect(storedDocument).toBeTruthy()

  const deletion = await request.delete(`${backend}/coverage/files`, {
    headers,
    data: { path: storedDocument!.path, delete_transactions: false },
  })
  expect(deletion.ok()).toBeTruthy()
  expect(await deletion.json()).toMatchObject({ deleted_transactions: 0 })

  const afterResponse = await request.get(`${backend}/transactions?page_size=100&account_id=${account!.id}`, { headers })
  expect(afterResponse.ok()).toBeTruthy()
  const after = await afterResponse.json() as { total: number }
  expect(after.total).toBe(before.total)

  const remainingFilesResponse = await request.get(
    `${backend}/coverage/files?account_id=${account!.id}&year_month=2026%2F03`,
    { headers },
  )
  expect(remainingFilesResponse.ok()).toBeTruthy()
  expect((await remainingFilesResponse.json()).files).toHaveLength(0)
})

test('aplica permissoes de colaborador e registra auditoria administrativa', async ({ request }) => {
  const adminToken = await apiLogin(request)
  const adminHeaders = { Authorization: `Bearer ${adminToken}` }
  const username = `e2e-colaborador-${Date.now()}`
  const password = 'e2e-collab-password-123'

  const created = await request.post(`${backend}/auth/users`, {
    headers: adminHeaders,
    data: { username, password, role: 'colaborador' },
  })
  expect(created.status()).toBe(201)

  const collaboratorLogin = await request.post(`${backend}/auth/login`, {
    data: { username, password },
  })
  expect(collaboratorLogin.ok()).toBeTruthy()
  const collaboratorToken = (await collaboratorLogin.json()).token as string
  const collaboratorHeaders = { Authorization: `Bearer ${collaboratorToken}` }

  const forbiddenReset = await request.post(`${backend}/system/reset`, {
    headers: collaboratorHeaders,
    data: { confirm: 'RESETAR', scope: 'transactions' },
  })
  expect(forbiddenReset.status()).toBe(403)

  const readableTransactions = await request.get(`${backend}/transactions?page_size=1`, {
    headers: collaboratorHeaders,
  })
  expect(readableTransactions.ok()).toBeTruthy()

  const auditResponse = await request.get(`${backend}/audit?entity=user&limit=100`, {
    headers: adminHeaders,
  })
  expect(auditResponse.ok()).toBeTruthy()
  const audit = await auditResponse.json() as Array<{ username: string; action: string; new_value: string }>
  expect(audit).toEqual(expect.arrayContaining([
    expect.objectContaining({ username: 'e2e-admin', action: 'create_user', new_value: username }),
  ]))
})

test('exporta auditoria administrativa como download real', async ({ page }) => {
  await login(page)
  await page.goto('/sistema')
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Exportar auditoria em Excel' }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toMatch(/^auditoria-lancamentos-\d{8}-\d{6}\.xlsx$/)
  await expect(page.getByText('Exportação de auditoria gerada')).toBeVisible()
})

test('vincula selecao grande em blocos e exibe progresso real', async ({ page, request }) => {
  test.setTimeout(180_000)
  await login(page)
  await seedHistoricalLinks(request)
  const fixture = path.resolve(__dirname, 'fixtures/history-links.csv')
  await importThroughUi(page, fixture, 'CONTA XP')

  await page.goto('/pendentes')
  await expect(page.getByText('VINCULO E2E 01', { exact: true })).toBeVisible()
  await page.locator('thead input[type=checkbox]').check()
  await page.getByRole('button', { name: 'Vincular selecionados' }).click()

  const progress = page.getByTestId('history-link-batch-progress')
  await expect(progress.getByText('Processamento concluido')).toBeVisible({ timeout: 90_000 })
  await expect(progress.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100')
  await expect(progress.getByText('12/12 · 100%')).toBeVisible()
  await expect(progress.getByText('Confirmados').locator('..').getByText('12', { exact: true })).toBeVisible()
  await expect(progress.getByText(/Lote completo:/)).toBeHidden()
  await expect(page.getByText('Nenhum lancamento encontrado')).toBeVisible()
})

test('rejeita, confirma, desvincula e recalcula vinculos pela interface', async ({ page, request }) => {
  test.setTimeout(180_000)
  await login(page)
  await seedHistoricalLinks(request)

  const cardFixture = path.resolve(__dirname, '../../backend/tests/fixtures/imports/xp_card.csv')
  await importThroughUi(page, cardFixture, undefined, '2026-03')
  await page.goto('/pendentes')
  const marketRow = page.getByRole('row').filter({ hasText: 'MERCADO BETA' })
  await marketRow.getByRole('button', { name: /Possivel vinculo/ }).click()
  await expect(page.getByText('Confira se os dois registros representam o mesmo lancamento')).toBeVisible()
  await page.getByRole('button', { name: 'Nao sao o mesmo' }).click()
  await expect(marketRow.getByRole('button', { name: /Possivel vinculo/ })).toHaveCount(0)

  const statementFixture = path.resolve(__dirname, '../../backend/tests/fixtures/imports/xp_statement.csv')
  await importThroughUi(page, statementFixture, 'CONTA XP')
  await page.goto('/pendentes')
  const incomeRow = page.getByRole('row').filter({ hasText: 'PIX RECEBIDO CLIENTE TESTE' })
  await incomeRow.getByRole('button', { name: /Possivel vinculo/ }).click()
  await expect(page.getByRole('paragraph').filter({ hasText: 'E2E VINCULO ENTRADA' })).toBeVisible()
  await page.getByRole('button', { name: 'Confirmar vinculo' }).click()
  await expect(incomeRow.getByText('Vinculado', { exact: true })).toBeVisible()

  await page.goto('/base-historica')
  await page.getByRole('button', { name: 'Entradas' }).click()
  const historyRow = page.getByRole('row').filter({ hasText: 'PIX RECEBIDO CLIENTE TESTE' })
  await expect(historyRow.getByText('vinculado', { exact: true })).toBeVisible()
  page.once('dialog', dialog => dialog.accept())
  await historyRow.getByRole('button', { name: 'desvincular' }).click()
  await expect(historyRow.getByText('vinculado', { exact: true })).toHaveCount(0)

  await page.getByRole('button', { name: 'Calcular vinculos historicos' }).click()
  await expect(page.getByText(/Calculo concluido:/)).toBeVisible({ timeout: 60_000 })
})
