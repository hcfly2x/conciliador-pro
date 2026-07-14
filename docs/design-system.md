# design-system.md — Design System

## Filosofia
Dark, premium, financeiro. Inspirado em ferramentas como Linear e Vercel.
Fontes mono para valores, sans para texto, display para títulos.

---

## Cores

```css
/* Background */
--bg-base:     #0d0f14   /* fundo principal */
--bg-surface:  #13161d   /* cards, sidebar */
--bg-elevated: #1a1e28   /* hover, inputs */
--bg-overlay:  #22273a   /* modais, dropdowns */

/* Bordas */
--border:      rgba(255,255,255,0.07)
--border-strong: rgba(255,255,255,0.12)

/* Texto */
--text-primary:   #e8eaf0
--text-secondary: #8b90a4
--text-tertiary:  #5a5f73

/* Accent */
--gold:        #c9a84c
--gold-light:  #e8c96e
--gold-dim:    rgba(201,168,76,0.15)

/* Semânticas */
--success:     #3ecf8e
--success-dim: rgba(62,207,142,0.12)
--danger:      #f87171
--danger-dim:  rgba(248,113,113,0.12)
--warning:     #fbbf24
--warning-dim: rgba(251,191,36,0.12)
--info:        #60a5fa
--info-dim:    rgba(96,165,250,0.12)
```

---

## Tipografia

```css
--font-display: 'Syne', sans-serif        /* títulos, logo */
--font-body:    'DM Sans', sans-serif     /* texto geral */
--font-mono:    'DM Mono', monospace      /* valores, datas, códigos */
```

Escala:
- `text-xs`: 11px — labels, badges
- `text-sm`: 13px — corpo principal
- `text-base`: 14px — parágrafo
- `text-lg`: 16px — títulos de seção
- `text-xl`: 20px — títulos de página
- `text-2xl`: 24px — valores grandes

---

## Componentes

### TransactionRow
```
Estado pendente:  bg-warning/5 border-l-2 border-warning
Estado conciliado: bg normal
Estado duplicata: bg-danger/5 opacity-70
Estado ignorado:  opacity-40 line-through

Hover: bg-elevated transition-colors
```

### StatusBadge
```
pending:    bg-warning/15    text-warning    "Pendente"
reconciled: bg-success/15    text-success    "Conciliado ✓"
duplicate:  bg-danger/15     text-danger     "Duplicata"
ignored:    bg-elevated      text-tertiary   "Ignorado"
```

### CategoryBadge
```
Pill com cor da categoria como background com 20% opacity
Texto na cor da categoria
Border 1px cor da categoria com 30% opacity
Click → abre modal de classificação
```

### AmountDisplay
```
Despesa: text-danger font-mono font-medium
Receita: text-success font-mono font-medium
Neutro:  text-secondary font-mono
Formato: R$ 11.000,00
```

### ImportDropzone
```
Estado normal:  border-2 border-dashed border-border
Estado hover:   border-gold bg-gold/5
Estado drag:    border-gold bg-gold/10 scale-[1.01]
Estado loading: skeleton animation
```

---

## Layout

```
Sidebar: 220px fixo
Topbar: 52px fixo
Content: flex-1 overflow-y-auto padding-6
```

### Sidebar
```
Logo no topo (24px padding)
Nav items: 8px padding, 6px radius
Active: bg-gold/15 text-gold border-l-2 border-gold
Hover: bg-elevated
Badge: pill vermelho para pendentes
```

### Topbar
```
Título da página (Syne bold)
Ações à direita (botão primário: Importar extrato)
```

---

## Tabela de Lançamentos

Colunas:
1. Checkbox (36px)
2. Data (90px) — fonte mono
3. Descrição (flex, elipsis)
4. Valor (100px, alinhado à direita, fonte mono)
5. Conta (120px) — badge azul
6. Categoria (180px) — CategoryBadge clicável
7. Subcategoria (120px) — texto mono pequeno
8. Observação (120px) — texto terciário
9. Status (100px) — StatusBadge

Header: sticky, fundo bg-elevated, texto uppercase mono 11px
Sorting: ↑↓ nos headers clicáveis
Row height: 44px
