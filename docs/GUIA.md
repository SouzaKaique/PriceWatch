# PRICE WATCH — Guia completo

> Visão geral, capturas de tela e início rápido no [README](../README.md).
> Os comandos partem da pasta onde você clonou o repositório (`PriceWatch`).

Monitor pessoal de preços (PWA). Roda 100% no seu computador Windows: Angular + Flask + SQLite,
sem hospedagem paga, sem cartão de crédito.

> O monitoramento só acontece enquanto o computador estiver ligado e o backend rodando.
> Com o PC desligado as verificações ficam pausadas e são retomadas quando o serviço voltar.

## Estrutura

```
PriceWatch/
├── backend/                 API Flask + SQLite
│   ├── app/
│   │   ├── __init__.py      fábrica da aplicação (CORS, chave de acesso, rotas)
│   │   ├── config.py        configuração lida do .env
│   │   ├── extensions.py    SQLAlchemy + PRAGMAs do SQLite (WAL, foreign keys)
│   │   ├── models.py        produtos, ofertas, histórico, cupons, notificações, push
│   │   ├── adapters/        um adaptador por loja + cliente HTTP com limite por domínio
│   │   ├── services/        lookup (consulta, cache), matching, events (alterações relevantes),
│   │   │                    monitor (rodadas), settings, ml_auth (OAuth Mercado Livre),
│   │   │                    analysis (preço habitual, médias, promoções enganosas),
│   │   │                    coupons (coleta oficial, aplicabilidade, estimativa),
│   │   │                    notify (Telegram/ntfy/Web Push, preferências, silêncio, limites),
│   │   │                    webpush (chaves VAPID locais, inscrições, envio),
│   │   │                    maintenance (integridade, backups), diagnostics
│   │   ├── scheduler.py     APScheduler: rodadas periódicas + retomada após reinício
│   │   ├── migrations.py    adiciona colunas novas ao SQLite sem perder dados
│   │   ├── stores.py        lojas suportadas + detecção da loja pelo domínio do link
│   │   ├── summary.py       menor preço, variação, preço-alvo (só com dados reais)
│   │   └── routes/
│   │       ├── health.py    /api/health, /api/stats, /api/stores
│   │       ├── products.py  produtos, ofertas, identificação por link
│   │       ├── integrations.py  status das lojas, Mercado Livre, preço manual
│   │       ├── monitor.py   monitoramento, configurações, eventos, histórico
│   │       ├── coupons.py   cupons: listagem, cadastro, verificação, atualização
│   │       ├── notifications.py  canais, teste, envio, histórico e Web Push
│   │       └── spa.py       serve o PWA (build do Angular) no mesmo endereço da API
│   ├── tests/               98 testes (pytest): API, lojas, falhas de rede, análise, cupons,
│   │                        alertas, Web Push, reinício/queda, backups — sem acessar a internet
│   ├── diagnostico.py       verificação de saúde pela linha de comando
│   ├── instance/            pricewatch.db, pricewatch.log, pricewatch.pid (não versionados)
│   ├── .env.example
│   ├── requirements.txt
│   └── run.py
└── frontend/                Angular 21 (standalone, zoneless) + Bootstrap 5 + SCSS + PWA
    ├── proxy.conf.json      encaminha /api → http://127.0.0.1:5000 em desenvolvimento
    └── src/app/
        ├── core/            api.service, models, store.service, money (R$ ↔ centavos)
        ├── shared/          product-card, price-chart (SVG), event-list
        └── pages/
            ├── dashboard/       indicadores, atividade recente, filtros e cards
            ├── product-form/    cadastro e edição (identificação pelo link)
            ├── product-detail/  comparação entre lojas, histórico em gráfico, alterações
            ├── coupons/         área de cupons (copiar código, verificar, cadastrar)
            ├── alerts/          alertas no celular: canais, preferências, histórico
            ├── integrations/    situação de cada loja e conexão com o Mercado Livre
            └── status/          "Sistema": saúde, configurações e execuções do monitoramento
scripts/                     iniciar/parar o backend, início automático no Windows, gerar ícones
```

## Pré-requisitos

- Python 3.10+ (`python --version`)
- Node.js 24.x (`node --version`)

> Usamos Angular 21 porque o Angular 22 exige Node ≥ 24.15. Se você atualizar o Node,
> dá para migrar depois com `ng update`.

## Instalação (uma vez) — PowerShell

```powershell
cd "PriceWatch\backend"
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
Copy-Item .env.example .env
```

```powershell
cd "PriceWatch\frontend"
npm install
```

## Execução

### Uso diário (um único processo) — recomendado

Compile o app uma vez (e de novo sempre que atualizar o código do frontend):

```powershell
cd "PriceWatch\frontend"
npm run build
```

Depois basta o backend — ele serve o app e a API no mesmo endereço, **http://localhost:5000**:

```powershell
cd "PriceWatch\backend"
.\.venv\Scripts\python run.py
```

Nesse modo o app é um PWA completo: instalável ("Instalar app" no Chrome/Edge), funciona offline
com os últimos dados salvos e avisa quando há nova versão.

### Desenvolvimento (recarregamento automático)

Backend como acima + `npm start` na pasta frontend → http://localhost:4200 (o `/api` é
encaminhado ao Flask). Service worker e Web Push ficam desligados nesse modo.

## Monitoramento automático

O backend traz um agendador (APScheduler) que consulta todas as ofertas ativas a cada
**2 horas** (ajustável em **Sistema**: 30 min a 24 h). Ele só roda **enquanto o backend estiver
aberto no seu computador** — com o PC desligado, as verificações ficam pausadas. Ao iniciar, se a
última verificação estiver atrasada, uma **verificação de retomada** acontece em ~1 minuto.

A cada consulta o preço vai para o histórico e o app registra **alterações relevantes**
(base das notificações da Fase 8): queda, aumento, voltou ao estoque, ficou indisponível,
menor preço registrado (com pelo menos 3 consultas anteriores), preço-alvo atingido e oferta
melhor em outra loja. Oscilações menores que **2% e R$ 5,00** (ajustáveis) são ignoradas, e cada
alteração é uma *transição* — não se repete a cada rodada.

### Rodar sem terminal aberto (opcional)

```powershell
cd "PriceWatch"
scripts\iniciar-backend.bat          # inicia em segundo plano (logs em backend\instance\pricewatch.log)
powershell -ExecutionPolicy Bypass -File scripts\parar-backend.ps1
```

Para iniciar sozinho quando você entrar no Windows (cria uma tarefa só para o seu usuário,
sem administrador):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\instalar-inicio-automatico.ps1
powershell -ExecutionPolicy Bypass -File scripts\remover-inicio-automatico.ps1   # desfaz
```

Abra http://localhost:5000 — a tela **Sistema** deve mostrar API, SQLite e agendador em verde.

## Testes

```powershell
cd "PriceWatch\backend"
.\.venv\Scripts\pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest
```

```powershell
cd "PriceWatch\frontend"
npx ng test --watch=false
```

## API

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/health` | saúde da API e do banco |
| GET | `/api/diagnostics` | verificações com orientação (tela Sistema) |
| GET | `/api/stats` | indicadores do dashboard |
| GET | `/api/stores` | lojas suportadas |
| POST | `/api/lookup` | identifica um produto pelo link (consulta real) |
| POST | `/api/offers/<id>/check` | consulta a oferta na loja agora |
| POST | `/api/offers/<id>/manual-price` | registra preço visto pelo usuário (identificado como manual) |
| GET | `/api/integrations` | situação de cada loja (sem expor tokens) |
| GET | `/api/monitor` | agendador, próxima rodada e últimas execuções |
| POST | `/api/monitor/run` | verificar todas as ofertas agora |
| GET/PATCH | `/api/settings` | intervalo, ativação e limites de variação |
| GET | `/api/events` | alterações detectadas (`product_id`, `limit`) |
| GET | `/api/products/<id>/history?days=N` | séries de preço por loja (0 = tudo) |
| GET | `/api/products/<id>/analysis` | classificação, preço habitual, médias 7/30/90/180, menor registrado |
| GET/POST | `/api/coupons` | lista (`store`, `validity`=active/upcoming/expired/all) / cadastro manual |
| PATCH/DELETE | `/api/coupons/<id>` | marcar "funcionou"/"não funcionou"; editar/excluir manuais |
| POST | `/api/coupons/refresh` | relê a página oficial da KaBuM! (mín. 10 min entre pedidos) |
| GET | `/api/products/<id>/coupons` | cupons do produto com aplicabilidade e preço estimado |
| GET | `/api/notifications/status` | canais (sem expor tokens), pendentes, preferências |
| POST | `/api/notifications/telegram/{connect,disconnect}` | detecta/remove o chat do Telegram |
| POST | `/api/notifications/test` | mensagem de teste nos canais ativos |
| POST | `/api/notifications/dispatch` | envia agora os alertas pendentes |
| GET | `/api/notifications/log` | histórico de envios |
| GET | `/api/push/key` | chave pública VAPID |
| POST | `/api/push/{subscribe,unsubscribe}` | inscrever/remover este aparelho no Web Push |
| POST | `/api/integrations/mercadolivre/{test,authorize,connect,disconnect}` | conexão com a API do ML |
| GET/POST | `/api/products` | listar / cadastrar (com links de ofertas) |
| GET/PATCH/DELETE | `/api/products/<id>` | detalhar / editar / excluir |
| POST | `/api/products/<id>/offers` | vincular link de outra loja |
| PATCH/DELETE | `/api/offers/<id>` | confirmar correspondência / remover |
| GET | `/api/offers/<id>/history` | histórico de preços da oferta |

Preços trafegam em **centavos** (inteiros). Ofertas cadastradas ficam como "não consultado"
até que um adaptador real obtenha o preço — nenhum valor é estimado.

## Estabilidade, backups e diagnóstico

- **Diagnóstico:** tela **Sistema** (lista com o que verificar e o que fazer) ou, mesmo com o
  backend parado:
  ```powershell
  cd "PriceWatch\backend"
  .\.venv\Scripts\python diagnostico.py
  ```
- **Backups automáticos:** 1 por dia em `backend\instance\backups\` (mantém os 7 últimos), feitos
  com a API de backup do SQLite (seguros com o app rodando). Para restaurar: pare o backend
  (`scripts\parar-backend.ps1`), copie o backup escolhido por cima de
  `backend\instance\pricewatch.db` (apague `pricewatch.db-wal` e `pricewatch.db-shm`) e inicie de novo.
- **Integridade:** verificada a cada início (`PRAGMA quick_check`); problema aparece no diagnóstico.
- **Queda de energia / PC desligado no meio de uma verificação:** o que já foi consultado fica
  salvo (cada oferta é gravada na hora); a rodada é marcada como interrompida e uma **retomada**
  acontece ~1 min depois de religar. Testado matando o processo à força.
- **Suspensão/hibernação:** ao acordar, a verificação atrasada roda uma vez (sem acumular).
- **Duas cópias abertas:** a segunda é recusada na hora (porta em uso) e não interfere na primeira.
- **Loja fora do ar / bloqueando / mudando a página:** a oferta mantém o último preço real e mostra
  o motivo; a rodada continua com as demais lojas.

### Problemas comuns

| Sintoma | O que fazer |
|---|---|
| `localhost:5000` diz "Build do app não encontrado" | `npm run build` na pasta frontend |
| App mostra "Sem conexão com o PRICE WATCH" | backend parado ou PC desligado — os últimos dados salvos continuam visíveis |
| "PRICE WATCH já está rodando" ao iniciar | já há uma instância; use `scripts\parar-backend.ps1` se quiser reiniciar |
| Loja aparece como "Loja bloqueou" | proteção anti-robô da loja; registre o preço manualmente (Integrações explica cada loja) |
| Alertas não chegam | **Alertas → Enviar teste**; veja o histórico de envios e o diagnóstico |
| Celular não abre o endereço `.ts.net` | Tailscale ligado no celular e no PC, e `tailscale serve --bg 5000` ativo |

## Segurança

- A API escuta apenas em `127.0.0.1` (inacessível para outros dispositivos da rede).
- CORS liberado só para o frontend local.
- `API_ACCESS_KEY` no `.env` (opcional) passa a exigir o cabeçalho `X-API-Key` em `/api/*`.
- `.env` e o banco ficam fora do git.

## Roadmap

| Fase | Conteúdo | Status |
|---|---|---|
| 1 | Estrutura Angular + Flask + SQLite, comunicação | ✅ concluída |
| 2 | Interface: dashboard, navegação, cards, formulários | ✅ concluída |
| 3 | Cadastro por URL, edição e remoção | ✅ concluída |
| 4 | Adaptadores Mercado Livre, Amazon, KaBuM!, Pichau | ✅ concluída |
| 5 | Monitoramento automático (APScheduler) e histórico | ✅ concluída |
| 6 | Inteligência de preços / falsas promoções | ✅ concluída |
| 7 | Cupons | ✅ concluída |
| 8 | Notificações (Telegram Bot e ntfy; Web Push na Fase 9) | ✅ concluída |
| 9 | PWA: instalação, offline, Web Push e acesso pelo celular | ✅ concluída |
| 10 | Testes e estabilidade | ✅ concluída |

## Inteligência de preços

Tudo é calculado **somente com o histórico coletado** pelo PRICE WATCH (consultas automáticas e
preços informados por você). Nada anterior ao início do monitoramento é estimado.

- **Preço do dia** = mediana das consultas do dia (fuso de Brasília), para que dias com muitas
  consultas não pesem mais.
- **Preço habitual** = mediana diária de 90 dias **sem os últimos 7** (ou 30 dias sem os últimos 3,
  com menos histórico). Excluir os dias recentes evita que uma alta artificial vire referência.
- **Médias 7/30/90/180 dias** com mínimo/máximo; cada janela só é considerada com dados suficientes
  (ex.: ≥ 7 dias com preço para 30 dias).
- **Desconto anunciado × real**: compara o preço "de" da loja com o preço habitual observado.
- **Calendário promocional** (Dia do Consumidor, Mães, Pais, Crianças, Black Friday, Natal): avisa
  quando o preço sobe nas semanas anteriores.

| Classificação | Regra (resumo) |
|---|---|
| Ótima oportunidade | ≥ 15% abaixo do habitual, ou menor preço registrado e ≥ 10% abaixo |
| Boa oportunidade | ≥ 5% abaixo do habitual |
| Preço dentro da média | até ±5% do habitual |
| Acima do preço habitual | > 5% acima do habitual |
| Desconto pouco vantajoso | loja anuncia desconto (ou houve queda recente), mas o preço só voltou ao habitual |
| Possível promoção enganosa | preço "de" ≥ 10% acima do habitual observado **ou** alta ≥ 10% nos últimos 30 dias seguida de "queda" que não fica abaixo do habitual — sempre com o motivo explicado |
| Dados insuficientes | menos de 5–7 dias de histórico: nenhuma conclusão é tirada |

Exemplo da especificação (R$ 899 → 899 → 1.199 → 999, anunciado "de R$ 1.199"): classificado como
**possível promoção enganosa** — habitual R$ 899,00, desconto anunciado 17%, real negativo.
Mudanças de classificação para *ótima oportunidade* ou *possível promoção enganosa* geram eventos
(base das notificações da Fase 8).

## Cupons

| Loja | Fonte | Como funciona |
|---|---|---|
| KaBuM! | [página oficial de cupons](https://www.kabum.com.br/hotsite/cupons/) | Automático, a cada 6 h (junto do monitoramento). A página carrega a lista de uma planilha pública indicada no próprio script da loja; o PRICE WATCH lê o script para achar o endereço e acompanha se a loja mudar. |
| Pichau, Mercado Livre, Amazon | sem fonte pública oficial de códigos acessível | Cadastro manual em **Cupons → Adicionar cupom** (a fonte é obrigatória). |

- Todo cupom começa como **"Não confirmado"**: o PRICE WATCH não testa cupons no carrinho. Depois de
  usar, marque **Funcionou** ou **Não funcionou** (este último o oculta dos produtos).
- **Aplicabilidade** a um produto: *a loja indica este produto* (o link do cupom aponta para ele),
  *provavelmente aplicável* (o cupom é para uma categoria/nome que combina) ou *não confirmada*
  (cupons para "produtos selecionados", mostrados recolhidos). Cupons de outra categoria, com compra
  mínima acima do preço ou cuja condição exclui a categoria do produto são descartados.
- **Preço estimado** = desconto aplicado sobre o preço à vista atual — é estimativa: a loja pode não
  acumular com outros descontos.
- Alertas *cupom disponível* só para cupons que se aplicam (ou provavelmente) a produtos monitorados.

## Integrações com as lojas

O PRICE WATCH lê os **dados estruturados (schema.org / JSON-LD)** que a própria loja publica
na página do produto — o mesmo conteúdo oferecido a buscadores. Regras:

- no máximo 1 requisição a cada 5 s por domínio (`HTTP_MIN_INTERVAL_SECONDS`);
- se a loja responder 403/429 ou mostrar verificação anti-robô, o domínio entra em pausa de
  30 min (`HTTP_BLOCK_COOLDOWN_SECONDS`) e a oferta é marcada "Loja bloqueou" —
  **nenhuma proteção é contornada** e nenhum preço é estimado;
- consultas feitas na tela de cadastro ficam 15 min em cache e são reaproveitadas ao salvar.

Situação verificada em 17/11/2026 (veja também a página **Integrações** do app):

| Loja | Fonte | Situação |
|---|---|---|
| KaBuM! | dados da página (JSON-LD + dados do Next.js) | ✅ automático: preço à vista, a prazo, preço "de", estoque, marca, modelo, imagem, categoria |
| Mercado Livre | **API oficial** (`/items`, `/products`) com app gratuito seu | ⚙️ precisa configurar (abaixo); sem isso a página costuma cair em verificação anti-robô |
| Amazon | dados da página | ⚠️ bloqueia; a PA-API 5 foi aposentada e a Creators API exige conta de Associados com vendas recentes |
| Pichau | dados da página | ⚠️ bloqueia (HTTP 403); sem API pública |

Nas lojas bloqueadas, use **"Registrar preço manualmente"** na página do produto: o preço entra no
histórico identificado como *informado por você* (`source = manual`), nunca como consulta automática.

### Configurar o Mercado Livre (gratuito, sem cartão)

1. Em https://developers.mercadolivre.com.br/devcenter, entre com sua conta e crie um aplicativo.
2. Cadastre uma **URI de redirect** `https` (depois de autorizar, o navegador vai para ela com
   `?code=…` — basta copiar o endereço).
3. Preencha em `backend/.env`:
   ```
   ML_CLIENT_ID=...
   ML_CLIENT_SECRET=...
   ML_REDIRECT_URI=https://... (idêntica à cadastrada)
   ```
4. Reinicie o backend e abra **Integrações** → *Testar credenciais*.
   O app usa primeiro um token de aplicação (`client_credentials`). Se a API negar acesso aos
   anúncios, clique em *Autorizar minha conta*, autorize e cole o endereço de retorno —
   o PRICE WATCH guarda o refresh token localmente e o renova sozinho (PKCE + `state`).

Os tokens ficam só no SQLite local; a API do app nunca os envia ao navegador.

> A integração com a API oficial foi implementada e testada com respostas simuladas; a validação
> com credenciais reais depende do seu app no Mercado Livre (a documentação oficial bloqueia
> acesso automatizado, então os detalhes seguem o fluxo OAuth padrão do Mercado Livre).

A correspondência entre lojas é só uma **sugestão** (marca, modelo, código do fabricante);
quem confirma é você, na página do produto.

## Usar no celular (iPhone e Android)

O celular precisa de um endereço **HTTPS** para instalar o PWA e receber Web Push. Sem hospedagem
paga, a forma recomendada é o **Tailscale** (plano Personal gratuito para uso pessoal, sem cartão):
cria uma rede privada só entre os seus aparelhos e dá ao seu PC um endereço HTTPS válido. O backend
continua escutando apenas em `127.0.0.1` — nada fica exposto na internet ou no Wi-Fi.

1. Instale o Tailscale no PC (https://tailscale.com/download) e no celular (App Store / Google Play)
   e entre com a **mesma conta** nos dois.
2. No painel do Tailscale (admin console → **DNS**), ative **MagicDNS** e **HTTPS Certificates**.
3. No PC, com o backend rodando (`run.py` ou `scripts\iniciar-backend.bat`), publique-o na sua rede
   privada (fica salvo entre reinícios):
   ```powershell
   tailscale serve --bg 5000
   ```
   O comando mostra o endereço, algo como `https://nome-do-pc.algo.ts.net`.
4. No celular, com o Tailscale ligado, abra esse endereço:
   - **iPhone (Safari):** Compartilhar → **Adicionar à Tela de Início**. Abra pelo ícone criado.
   - **Android (Chrome):** menu → **Instalar app**.
5. No app instalado: **Alertas → Ativar neste aparelho** → permita notificações → **Enviar teste**.
   (No iPhone, Web Push exige iOS 16.4+ e o app aberto pela Tela de Início.)

Com o PC desligado, o app no celular ainda abre e mostra os **últimos dados salvos** no aparelho;
consultas e alertas voltam quando o PC ligar. Para desfazer: `tailscale serve --https=443 off`.

Proteção extra (opcional): defina `API_ACCESS_KEY` no `backend/.env`; o app pedirá a chave uma vez
em cada aparelho.

Os ícones do PWA são gerados por `scripts/gerar-icones.py` (Pillow, dependência só de
desenvolvimento): `backend\.venv\Scripts\python scripts\gerar-icones.py`.

## Alertas no celular

O backend local só faz requisições **de saída** para enviar alertas — funciona com o celular em
qualquer lugar, sem hospedagem e sem abrir portas no seu roteador. Configure em **Alertas**.

| Canal | Custo | Como configurar |
|---|---|---|
| **Telegram** (recomendado) | gratuito, sem cartão | No Telegram, `@BotFather` → `/newbot` → copie o token para `TELEGRAM_BOT_TOKEN` no `backend/.env` → reinicie o backend → envie `/start` ao seu bot → **Conectar**. |
| **ntfy** | gratuito, sem conta (servidor público ntfy.sh, com limites) | Instale o app ntfy, escolha um tópico longo e aleatório (o app sugere um), coloque em `NTFY_TOPIC` no `.env`, reinicie e assine o mesmo tópico no app. O nome do tópico funciona como senha. |
| **Web Push** | gratuito, sem conta | Notificação do próprio app instalado: abra o PRICE WATCH por HTTPS (veja "Usar no celular"), instale na tela inicial e, em **Alertas**, toque em **Ativar neste aparelho**. Chaves VAPID geradas localmente em `backend/instance/`. |

Exemplo (preço-alvo atingido):

```
PRICE WATCH — Oportunidade encontrada!

Seu Monitor LG UltraGear 27 está custando R$ 749,90 na KaBuM!.

Preço desejado: R$ 750,00.

O preço-alvo foi atingido!

Toque para conferir a oferta   ← link para a oferta original
```

Controles: tipos de alerta (preço-alvo, queda relevante, menor preço registrado, ótima oportunidade,
cupom disponível, voltou ao estoque, oferta melhor em outra loja — e, opcionais, aumento,
indisponível e possível promoção enganosa), **horário de silêncio** (alertas saem quando acaba),
**máximo por hora**, sem repetir o mesmo alerta em 24 h, alertas com mais de 24 h descartados (nada
de "despejar" o passado ao configurar), até 3 tentativas por canal em caso de falha. Alertas retidos
são reenviados a cada 10 min. Os testes automatizados nunca enviam mensagens reais.
