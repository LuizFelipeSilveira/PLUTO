# PLUTO 🪐

Sistema de controle financeiro pessoal com importação automática de extratos e faturas do Nubank, categorização com aprendizado por estabelecimento e dashboard multiusuário.

---

## Visão geral

O PLUTO elimina o lançamento manual de transações. Um cron diário lê os documentos do Nubank que chegam por e-mail, extrai o CSV anexado e importa as transações para o banco, já classificadas quando o estabelecimento é conhecido.

```
Nubank → e-mail do usuário → encaminhamento automático → caixa intermediária
                                                              ↓
                                            Microsoft Graph API (cron diário)
                                                              ↓
                                              FastAPI (/webhook/csv | /webhook/fatura)
                                                              ↓
                                                    PostgreSQL (Supabase)
                                                              ↓
                                                   Dashboard (Streamlit)
```

---

## Arquitetura

| Camada | Tecnologia | Hospedagem |
|---|---|---|
| Backend / API | FastAPI | Vercel (serverless) |
| Banco de dados | PostgreSQL | Supabase |
| Dashboard | Streamlit | Streamlit Community Cloud |
| Leitura de e-mails | Microsoft Graph API | — |
| Agendamento | Vercel Cron | — |

Toda a stack roda em planos gratuitos.

---

## Como funciona a importação

### Origem dos dados

Cada usuário configura o encaminhamento automático dos e-mails do Nubank para uma caixa intermediária. O Gmail preserva o cabeçalho `To:` original no encaminhamento, o que permite identificar de quem é cada documento através do campo `toRecipients` da Graph API — sem depender de parsing do corpo do e-mail.

O mapeamento e-mail → usuário vive na variável `USER_EMAIL_MAP`. Documentos de remetentes não mapeados não são importados nem marcados como lidos: ficam pendentes e são reportados na resposta do cron.

### Dois formatos, duas rotas

**Extrato da conta** (`/webhook/csv`) — colunas `Data`, `Valor`, `Identificador`, `Descrição`. O valor vem com sinal (negativo = saída) e o `Identificador` serve como chave de deduplicação.

**Fatura do cartão** (`/webhook/fatura`) — colunas `date`, `title`, `amount`. Não há identificador, então é gerado um hash SHA-256 a partir de data + título + valor + usuário, com um contador para linhas idênticas dentro do mesmo arquivo.

### Deduplicação

A fatura é **incremental**: durante o ciclo aberto, cada nova versão traz as transações anteriores mais as novas. A deduplicação é feita linha a linha via `external_id` (coluna com constraint `UNIQUE`), o que permite reimportar o mesmo ciclo quantas vezes for necessário sem duplicar nada.

Dois casos exigem tratamento especial:

- **Pix no crédito** gera duas linhas no extrato com o *mesmo* `Identificador` (a entrada vinda do cartão e a saída para o destinatário). Ocorrências repetidas dentro do arquivo recebem um sufixo numérico.
- **Compras idênticas no mesmo dia** (mesma data, valor e estabelecimento) na fatura são distinguidas pelo mesmo mecanismo de contagem.

---

## Categorização

### Entradas (valor positivo)

Classificadas automaticamente por regras, na seguinte ordem de precedência:

1. **Pix no crédito** → Movimentação Interna
2. **Salário** — descrição contém o banco de origem *e* o nome do próprio usuário → Renda
3. **Resgate de investimento** → Movimentação Interna
4. **Transferência de outro usuário do sistema** → Movimentação Interna
5. **Transferência do próprio usuário de outra conta** → Movimentação Interna
6. Demais casos → Renda

Os dados que alimentam essas regras (`full_name`, `salary_bank`) ficam na tabela `user`, não no código — o que permite adicionar usuários sem alterar a lógica.

### Saídas (valor negativo)

Consultam a tabela `establishment_category_map`, que mapeia estabelecimento → categoria. Estabelecimentos desconhecidos entram sem categoria e aparecem na aba **Treinamento** do dashboard.

Ao categorizar manualmente, o sistema grava no mapa a **categoria mais frequente** daquele estabelecimento, não a última escolhida — o que evita que um erro pontual contamine importações futuras. Categorias de entrada (Renda, Movimentação Interna) são excluídas desse cálculo.

A aba **Mapeamentos** lista todos os pares registrados e permite corrigi-los. Correções afetam apenas importações futuras; o histórico permanece intacto.

### Limpeza de descrição

- **Transferências** e **compras no débito** têm o nome do estabelecimento extraído da descrição completa, descartando CPF/CNPJ, banco, agência e conta.
- **Parcelas** (`Loja - Parcela 2/5`) têm o sufixo removido do nome e gravado nas colunas `installment_current` / `installment_total`. Isso mantém o aprendizado funcionando entre meses e permite calcular o valor comprometido em parcelas futuras.
- **Pagamento de fatura** é ignorado: seria contabilizado em duplicidade, já que as compras individuais já vêm pela fatura.

---

## Modelo de dados

```
user
├── id, name
├── full_name      → usado nas regras de classificação de entradas
└── salary_bank    → banco de origem do salário

category
├── id, name

transaction
├── id, user_id, value, establishment, date, category_id
├── external_id                              → chave de deduplicação (UNIQUE)
└── installment_current, installment_total   → parcelamento

establishment_category_map
├── establishment (UNIQUE) → category_id
```

### Categorias

| ID | Nome | Natureza |
|---|---|---|
| 1 | Alimentação | gasto |
| 2 | Transporte | gasto |
| 3 | Lazer | gasto |
| 4 | Saúde e Bem-Estar | gasto |
| 5 | Assinaturas | gasto fixo |
| 6 | Contas Residenciais | gasto fixo |
| 7 | Outros | gasto |
| 8 | Renda | entrada |
| 9 | Investimento | neutro |
| 10 | Movimentação Interna | neutro |
| 11 | Pet | gasto |
| 12 | Casa | gasto |
| 13 | Compras | gasto |

As categorias 8, 9 e 10 são excluídas do total de gastos e dos gráficos de despesa. Investimento e Movimentação Interna representam dinheiro que muda de lugar, não que é consumido.

---

## Dashboard

Três abas:

- **Dashboard** — métricas do mês (renda, total gasto, saldo, investido, projeção, média diária, comprometido em parcelas, gastos fixos), evolução diária empilhada por categoria com linha de acumulado, distribuição por categoria e média de gastos por dia da semana.
- **Treinamento** — categorização de estabelecimentos ainda desconhecidos.
- **Mapeamentos** — revisão e correção do aprendizado.

Filtros de usuário (individual ou conjunto) e de mês, além de um botão para disparar a importação sob demanda em vez de esperar o cron.

O gráfico de média por dia da semana exclui gastos fixos, que distorceriam o resultado por caírem sempre no mesmo dia.

---

## Configuração

### Variáveis de ambiente (Vercel)

| Variável | Descrição |
|---|---|
| `DATABASE_URL` | String de conexão do Supabase (usar a do pooler) |
| `MS_CLIENT_ID` | Application ID do App Registration no Azure |
| `MS_CLIENT_SECRET` | Client secret do mesmo registro |
| `MS_REFRESH_TOKEN` | Token gerado uma única vez via `get_refresh_token.py` |
| `USER_EMAIL_MAP` | `email1:1,email2:2` |
| `CRON_SECRET` | Valor aleatório que protege a rota do cron |

### Secrets (Streamlit Cloud)

```toml
DATABASE_URL = "..."
CRON_SECRET = "..."
```

### Setup do Microsoft Graph

1. Registrar um app no [portal.azure.com](https://portal.azure.com) → Microsoft Entra ID → Registros de aplicativo, com tipo de conta "qualquer diretório organizacional e contas pessoais".
2. Redirect URI (Web): `http://localhost:8080/callback`
3. Permissões **delegadas** do Microsoft Graph: `Mail.Read`, `Mail.ReadWrite`, `offline_access`
4. Gerar um client secret em Certificados e segredos.
5. Rodar `python get_refresh_token.py` localmente e guardar o refresh token retornado.

O refresh token se renova a cada uso — o cron diário mantém a autenticação viva indefinidamente. O **client secret**, porém, expira conforme o prazo escolhido no Azure e precisa ser regerado antes disso.

### Rodando local

```bash
pip install -r requirements.txt

# backend
uvicorn main:app --reload

# dashboard
streamlit run app.py
```

O `.env` local precisa de `DATABASE_URL` e `CRON_SECRET` (e das credenciais MS caso vá gerar um refresh token novo).

---

## API

| Rota | Método | Descrição |
|---|---|---|
| `/cron/check-extrato` | GET | Busca documentos não lidos, identifica tipo e usuário, despacha para a rota correspondente. Requer header `Authorization: Bearer <CRON_SECRET>` |
| `/webhook/csv` | POST | Importa extrato de conta |
| `/webhook/fatura` | POST | Importa fatura de cartão |

Payload das rotas de webhook:

```json
{ "csv_data": "conteúdo do CSV", "recipient": "email@dominio.com" }
```

---

## Decisões de projeto

**Por que Microsoft Graph e não uma ferramenta de automação.** A versão original usava o Make com regex sobre o corpo dos e-mails — frágil a qualquer mudança de layout e com dados financeiros trafegando por um terceiro. A migração para Graph + CSV anexado eliminou o parsing de texto e manteve os dados dentro da própria infraestrutura.

**Por que uma tabela de mapeamento em vez de consultar o histórico.** Consultar o histórico direto funcionaria e seria uma peça a menos. A tabela foi mantida porque dá **visibilidade**: um erro diluído entre centenas de transações é difícil de notar, enquanto uma lista curta de estabelecimentos pode ser revisada de relance e corrigida pontualmente.

**Por que valores sempre positivos.** A convenção do banco é `value` absoluto, com a natureza da transação determinada pela categoria. Isso mantém compatibilidade com transações importadas antes do extrato existir e simplifica a agregação nos gráficos.

**Por que parcelas futuras não são gravadas.** Gravar as parcelas seguintes criaria despesas em meses que ainda não aconteceram e linhas fantasma caso o parcelamento fosse antecipado ou cancelado. A informação está nas colunas de parcelamento; a projeção é calculada na exibição.

---

## Limitações conhecidas

- A importação depende do usuário solicitar o extrato/fatura no app do Nubank. Um ciclo de fatura que feche sem ter sido solicitado não é recuperável automaticamente.
- Compras no crédito só aparecem quando a fatura é importada — não há registro em tempo real.
- O match de estabelecimento é exato. Variações no nome do mesmo comerciante geram entradas separadas no mapa.
- O dashboard é otimizado para desktop; no celular o layout fica denso.
