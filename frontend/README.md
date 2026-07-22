# Conciliador Pro - Frontend

Interface web em Next.js para importar documentos financeiros, revisar lancamentos,
classificar categorias e subcategorias e consultar relatorios.

## Desenvolvimento local

1. Copie `.env.example` para `.env.local`.
2. Inicie o backend na porta `5061`.
3. Instale as dependencias com `npm install`.
4. Execute `npm run dev`.

Quando `NEXT_PUBLIC_API_URL` nao estiver definida, o frontend envia requisicoes para
`/api/v1` e o Next.js as encaminha para `API_PROXY_TARGET`. O valor padrao e
`http://127.0.0.1:5061`.

## Producao

Na Vercel, configure:

```env
NEXT_PUBLIC_API_URL=https://seu-backend.onrender.com/api/v1
NEXT_PUBLIC_AUTH_DISABLED=false
NEXT_PUBLIC_SENTRY_DSN=
```

No Render, configure `CORS_ORIGINS` com o dominio do frontend e mantenha a
autenticacao habilitada. Consulte `../docs/DEPLOY.md` para o checklist completo.
Sem DSN, o Sentry fica desativado.

## Comandos

```bash
npm run dev
npm run build
npm start
```
