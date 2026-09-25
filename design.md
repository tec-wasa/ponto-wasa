# Ponto — Design System

Guia de design extraído do mockup (desktop 1280×800 e mobile 390×844, temas claro/escuro). Use como base para implementação em CSS/Tailwind/tokens de design.

## 1. Tipografia

| Papel | Fonte | Pesos | Uso |
|---|---|---|---|
| Display / números | `Space Grotesk` | 500, 600, 700 | Relógio, wordmark, valores em destaque, timestamps |
| Corpo | `Public Sans` | 400, 500, 600, 700 | Textos, navegação, labels |

```html
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Public+Sans:wght@400;500;600;700&display=swap">
```

```css
--font-display: 'Space Grotesk', sans-serif;
--font-body: 'Public Sans', sans-serif;
```

**Escala**
- Relógio (desktop): 56px / 700 / letter-spacing -0.02em
- Relógio (mobile): 36px / 700 / letter-spacing -0.02em
- Wordmark: 21px (desktop) / 18px (mobile) / 700
- Título de seção (uppercase): 11–12px / 700 / letter-spacing 0.06em / cor muted
- Corpo padrão: 14–15px / 400–600
- Legendas / metadados: 12–13px / 400

## 2. Cores — Tema Claro

| Token | Valor | Uso |
|---|---|---|
| `--bg` | `#F6F3EC` | Fundo geral |
| `--surface` | `#FFFFFF` | Cartões |
| `--border` | `rgba(30,35,32,.07)` a `.08` | Bordas de cartões e header |
| `--text-primary` | `#1E2320` | Texto principal |
| `--text-muted` | `#5B6660` | Texto secundário |
| `--text-faint` | `#8A928C` | Labels, legendas |
| `--text-disabled` | `#B7BDB9` | Itens futuros/inativos |
| `--accent` | `#2F6B5B` | Ação primária (verde-teal) |
| `--accent-on` | `#FFFFFF` | Texto sobre `--accent` |
| `--warn-bg` | `#FBF0DF` | Chip de status "intervalo" |
| `--warn-text` | `#8A5B1F` | Texto do chip de intervalo |
| `--status-working` | `#3F8F6B` | Dot "trabalhando" |
| `--status-break` | `#C98A3E` | Dot "intervalo" |
| `--status-off` | `#B7BDB9` | Dot "fora" |
| `--avatar-bg` | `#DCE7E1` | Fundo do avatar |
| `--avatar-text` | `#2F4A40` | Iniciais do avatar |

## 3. Cores — Tema Escuro

| Token | Valor | Uso |
|---|---|---|
| `--bg` | `#14171A` | Fundo geral |
| `--surface` | `#1B1F23` | Cartões |
| `--border` | `rgba(255,255,255,.07)` a `.08` | Bordas de cartões e header |
| `--text-primary` | `#EDEAE3` | Texto principal |
| `--text-muted` | `#9AA39D` | Texto secundário |
| `--text-faint` | `#8A928C` | Labels, legendas |
| `--text-disabled` | `#5A625C` | Itens futuros/inativos |
| `--accent` | `#5FA98D` | Ação primária (verde-teal claro) |
| `--accent-on` | `#0E1210` | Texto sobre `--accent` (contraste em fundo claro) |
| `--warn-bg` | `#3A2C18` | Chip de status "intervalo" |
| `--warn-text` | `#E3A968` | Texto do chip de intervalo |
| `--status-working` | `#5FA98D` | Dot "trabalhando" |
| `--status-break` | `#E3A968` | Dot "intervalo" |
| `--status-off` | `#5A625C` | Dot "fora" |
| `--avatar-bg` | `#24322C` | Fundo do avatar |
| `--avatar-text` | `#8FD9BB` | Iniciais do avatar |

> Regra geral: no escuro, `--accent-on` muda de branco para um tom quase preto (`#0E1210`), pois o teal claro (#5FA98D) não garante contraste 4.5:1 com texto branco.

## 4. Espaçamento & raio

- Escala de espaçamento: `4 · 6 · 8 · 10 · 12 · 14 · 16 · 20 · 24 · 28 · 32`
- Raio de cartões: `18px` (mobile) / `20px` (desktop)
- Raio de botões primários: `999px` (pill) no desktop; `14px` (retangular arredondado) no mobile, largura total
- Raio de avatares e dots de status: `50%`
- Barras do gráfico semanal: `5–6px` no topo, retas na base

## 5. Layout

### Desktop (1280×800)
- Header fixo 72px: wordmark + nav horizontal + toggle de tema + avatar
- Corpo: grid `1fr 340px`, gap 24px, padding 32px 40px
- Coluna esquerda: cartão do relógio + timeline "Hoje"
- Coluna direita: resumo semanal (mini gráfico de barras) + equipe (lista vertical com dot + nome + status)

### Mobile / Tablet retrato (390×844, prioridade do produto)
- Header enxuto 56px: wordmark + toggle de tema + avatar
- Conteúdo em coluna única, gap 14px, padding 20px 20px 16px
- Botão "Bater ponto" em largura total
- Equipe vira faixa horizontal de chips (dot + primeiro nome) em vez de lista
- **Navegação inferior fixa (64px)**: 4 abas — Painel, Registros, Equipe, Relatórios — ícone 20px + label 10px; aba ativa colorida com `--accent`, demais em `--text-faint`

> Tablet: reaproveitar o grid desktop (1fr/340px) a partir de ~768px de largura; abaixo disso, usar o layout mobile de coluna única com tab bar inferior.

## 6. Componentes

- **Cartão**: `background: var(--surface)`; `border: 1px solid var(--border)`; `border-radius` conforme item 4; sem sombra pesada (evitar drop-shadow genérico).
- **Botão primário**: fundo `--accent`, texto `--accent-on`, sem borda, `font-weight: 600`, hover `opacity: .9`.
- **Chip de status**: fundo `--warn-bg` / texto `--warn-text`, `border-radius: 999px`, uppercase, `font-size: 11–12px`.
- **Dot de status**: círculo 7–8px, cor conforme `--status-*`.
- **Toggle de tema**: botão circular 32–36px, borda `1px solid var(--border)`, ícone sol (claro→ação vai para escuro) / lua (escuro→ação vai para claro).
- **Avatar**: círculo com iniciais, `--avatar-bg` / `--avatar-text`.
- **Linha de timeline**: `flex; justify-content: space-between`, separador `border-bottom: 1px solid var(--border)` (última linha sem borda).
- **Gráfico de barras semanal**: barras `flex: 1`, altura proporcional às horas trabalhadas, último dia (se incompleto) em `--accent` com opacidade reduzida (~25%).

## 7. Iconografia

- Ícones em **stroke SVG** (viewBox 24×24, `stroke-width: 2`, `fill: none`), nunca emoji.
- Conjunto usado: sol/lua (tema), casa (Painel), lista (Registros), pessoas (Equipe), barras (Relatórios).
- Cor herdada via `currentColor` para reagir ao tema e ao estado ativo.

## 8. Acessibilidade

- Contraste mínimo 4.5:1 para texto normal, 3:1 para texto ≥24px — validar especialmente `--accent-on` sobre `--accent` em cada tema.
- Alvos de toque ≥44px de altura (botões e abas da tab bar já seguem essa métrica).
- Toggle de tema e demais botões apenas com ícone precisam de `aria-label`.
- Cor nunca é o único diferenciador de status: os dots já variam em tonalidade/luminosidade (verde/âmbar/cinza), mantendo essa lógica em outros elementos.
- Usar elementos semânticos reais (`<button>`, `<a href>`, `<nav>`) — sem `div` com `onClick`.

## 9. Como aplicar

Defina os tokens acima como CSS custom properties no root e alterne com um atributo (`data-theme="dark"`) ou `prefers-color-scheme`:

```css
:root {
  --bg: #F6F3EC;
  --surface: #FFFFFF;
  /* ...demais tokens do tema claro */
}
:root[data-theme="dark"] {
  --bg: #14171A;
  --surface: #1B1F23;
  /* ...demais tokens do tema escuro */
}
```

O mockup completo (desktop + mobile, claro + escuro) está disponível no canvas: https://claude.ai/artifact/X2wS9xqvF9xo56QaiSmnCB
