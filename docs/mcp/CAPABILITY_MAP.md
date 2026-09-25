# Mapa de capacidades: app → MCP

<!-- GERADO por `python -m app.mcp.docs` a partir de `backend/app/mcp/capability_map.py` e do registro. Não edite à mão. -->

Duas visões do mesmo contrato. A primeira parte da **tool**: que regra do app ela aplica, qual peça do código executa, que permissão exige e o que acontece de lado. A segunda parte da **rota REST**: toda rota do app aparece, com a tool que a cobre ou o motivo de não haver uma. O teste `tests/mcp/test_capability_map.py` reprova rota nova sem decisão.

Confirmação: `host` = o cliente pede confirmação por não ser `readOnlyHint` (ChatGPT e Claude fazem isso); `servidor` = token de prévia emitido pelo servidor, de uso único. Autorização efetiva = escopo OAuth ∩ papel no espaço ∩ `access_policy`.

## Por tool

| Tool | Classe | Escopo | Regra do app | Peça (serviço/comando) | Risco | Efeito colateral | Confirmação | Idempotência |
|---|---|---|---|---|---|---|---|---|
| `profile_get` | Leitura | `finance.read` | Identidade do token (ADR 0035) | `User.public_id, today_local` | baixo | nenhum | — | natural |
| `spaces_list` | Leitura | `finance.read` | Membership e papel (ADR 0018) | `WorkspaceMembership` | baixo | nenhum | — | natural |
| `people_list` | Leitura | `finance.read` | Só quem divide espaço com a pessoa | `space_members` | baixo — nomes de membros | nenhum | — | natural |
| `categories_list` | Leitura | `finance.read` | Vocabulário do espaço | `Category, Tag, Merchant` | baixo | nenhum | — | natural |
| `cards_list` | Leitura | `finance.read` | Cartão pessoal (ADR 0021), fatura derivada (0002) | `CreditCardService` | médio — limite e fatura | nenhum | — | natural |
| `accounts_list` | Leitura | `finance.read` | Saldo derivado (ADR 0034) | `AccountBalanceService, ProjectionService` | médio — saldos | nenhum | — | natural |
| `transactions_search` | Leitura | `finance.read` | transaction_scope (ADR 0018), minha parte | `services/transaction_query` | médio — lançamentos | nenhum | — | natural |
| `transactions_get` | Leitura | `finance.read` | get_visible_transaction | `access_policy` | médio | nenhum | — | natural |
| `transactions_show` | Leitura | `finance.read` | A mesma leitura de transactions_get, desenhada no componente | `transactions_get` | médio | nenhum (desenha um componente na conversa) | — | natural |
| `transactions_history` | Leitura | `finance.read` | Histórico de UM lançamento visível (decisão do dono); só campos permitidos, sem IP | `AuditLog (fotos da linha)` | médio — mostra quem mudou | nenhum | — | natural |
| `statements_get` | Leitura | `finance.read` | Fatura cumulativa (ADR 0023) | `CreditCardService.statement_population` | médio | nenhum (não cria fatura) | — | natural |
| `statements_show` | Leitura | `finance.read` | A mesma leitura de statements_get, com a 1ª página de compras | `statements_get` | médio | nenhum (desenha um componente na conversa) | — | natural |
| `reports_summary` | Leitura | `finance.read` | Consumo = minha parte; caixa ≠ competência | `OverviewService, ReportService` | médio | nenhum | — | natural |
| `reports_show` | Leitura | `finance.read` | A mesma leitura de reports_summary, de um mês | `reports_summary` | médio | nenhum (desenha um componente na conversa) | — | natural |
| `budgets_list` | Leitura | `finance.read` | Meta pessoal × da casa | `MonthlyEstimate, ReportService` | baixo | nenhum | — | natural |
| `reports_breakdown` | Leitura | `finance.read` | Mesmos filtros e escopo da busca; minha parte rateada em centavos (0001/0019) | `services/transaction_query.breakdown` | médio | nenhum | — | natural |
| `debts_summary` | Leitura | `finance.read` | Espaços não se compensam (ADR 0031) | `PersonalDebtService` | médio | nenhum | — | natural |
| `payables_list` | Leitura | `finance.read` | A pagar = não liquidado (ADR 0029) | `PayablesService, OverviewService` | médio | nenhum | — | natural |
| `income_list` | Leitura | `finance.read` | Renda pessoal, status derivado | `Income, income_status` | médio | nenhum | — | natural |
| `recurring_list` | Leitura | `finance.read` | shared_or_mine_scope | `RecurringExpense, RecurringIncome` | baixo | nenhum | — | natural |
| `recurring_get` | Leitura | `finance.read` | shared_or_mine_scope; divisão pelo snapshot (0012) | `RecurringService._participants + SplitService` | baixo | nenhum | — | natural |
| `accounts_statement` | Leitura | `finance.read` | Saldo corrente desde a abertura; caixa = mesma origem dos totais (0022/0034) | `AccountBalanceService.statement, OverviewService.get_ledger` | médio — movimentos de caixa | nenhum | — | natural |
| `transfers_list` | Leitura | `finance.read` | Só contas da pessoa | `AccountTransfer` | baixo | nenhum | — | natural |
| `financings_list` | Leitura | `finance.read` | Contrato pessoal (ADR 0021); saldo devedor = principal em aberto | `Financing, AmortizationInstallment` | médio | nenhum | — | natural |
| `financings_installment` | Escrita | `accounts.write` | Reivindicação atômica da parcela; estorno apaga a despesa vinculada | `commands.financing.pay_/unpay_installment` | alto — caixa | lança despesa no espaço se pedido; WS | host | por estado (definir X) |
| `view_show` | Leitura | `finance.read` | A mesma leitura da tool de dados, desenhada (§11) | `o handler da tool de dados` | médio | nenhum (desenha um componente na conversa) | — | natural |
| `transactions_create` | Escrita | `transactions.write` | Divisão em centavos (0001), fatura (0002), parcelas, moeda (0006/0015), liquidação (0029) | `commands.transactions.create_transaction` | alto — cria dívida entre pessoas | WS + auditoria; cria fatura se preciso | host | `idempotency_key` |
| `transactions_update` | Escrita | `transactions.write` | Máquina de estados (0003), trava de paga, vínculo de financiamento | `commands.transactions.update_*` | alto — reescreve valor/divisão | WS + auditoria; reroteia fatura | host | por estado (definir X) |
| `transactions_delete` | Destrutiva | `transactions.write` | Soft delete; paga é imutável; anexos exigem prévia | `commands.transactions.delete_*` | alto | WS + auditoria; blobs de anexo liberados após o commit | host | por estado (definir X) |
| `transactions_restore` | Escrita | `transactions.write` | Mesma permissão do delete | `commands.transactions.restore_transaction` | médio | WS + auditoria | host | por estado (definir X) |
| `transactions_bulk_preview` | Leitura | `finance.read` | Elegibilidade = regras do delete/categorizar | `confirmation.issue` | baixo | grava só o token de confirmação (hash) | — | natural |
| `transactions_bulk_delete` | Destrutiva | `transactions.write` | Conjunto exato da prévia, tudo ou nada | `commands.transactions.delete_transaction ×N` | alto — em massa | WS + auditoria; blobs após o commit | servidor (token) + host | token de uso único |
| `transactions_bulk_categorize` | Escrita | `transactions.write` | Só sem categoria (regra do app) | `commands.transactions.bulk_categorize` | médio — em massa | WS + auditoria | servidor (token) + host | token de uso único |
| `transactions_bulk_update` | Escrita | `transactions.write` | Conjunto exato da prévia, tudo ou nada; trava de paga | `commands.transactions.update_transaction ×N` | médio — em massa | WS + auditoria | host | token de uso único |
| `imports_preview` | Leitura | `finance.read` | Fingerprint (ADR 0008) + heurística | `commands.imports._mark_duplicates` | baixo | nenhum | — | natural |
| `imports_commit` | Escrita | `transactions.write` | Dedup por fingerprint (ADR 0008), trava do espaço | `commands.imports.commit_import` | alto — em lote | WS + auditoria | host | `idempotency_key` |
| `imports_list` | Leitura | `finance.read` | Só os lotes que a própria pessoa importou | `ImportBatch, ImportRow` | baixo | nenhum | — | natural |
| `imports_undo` | Escrita | `transactions.write` | Tudo ou nada, regras da exclusão; token de uso único amarrado ao conjunto (ADR 0036/0037) | `commands.imports.undo_batch, commands.account_imports.undo_account_import` | alto — em lote, apaga recibos | WS + auditoria | host | por estado (definir X) |
| `statements_pay` | Escrita | `accounts.write` | Saldo cumulativo, sem sobrepagamento, UPDATE condicional | `commands.statements.pay_statement` | alto — caixa | fecha a fatura se o ciclo acabou; auditoria | host | `idempotency_key` |
| `transfers_create` | Escrita | `accounts.write` | Moeda da conta = moeda do movimento (0034) | `commands.accounts.create_transfer` | alto — caixa | auditoria | host | `idempotency_key` |
| `accounts_adjust_balance` | Escrita | `accounts.write` | Ajuste datado, não reescreve o passado (0034) | `commands.accounts.adjust_balance` | alto — caixa | auditoria | host | `idempotency_key` |
| `transfers_delete` | Destrutiva | `accounts.write` | Soft delete das duas pernas | `commands.accounts.delete_transfer` | alto — caixa | auditoria | host | por estado (definir X) |
| `statements_reopen` | Destrutiva | `accounts.write` | Estorna os pagamentos (reopen do app); sem pagamento, nada | `commands.statements.reopen_statement` | alto — caixa | a fatura volta um passo; auditoria | host | por estado (definir X) |
| `income_create` | Escrita | `income.write` | Conversão na data do recebimento | `commands.income.create_income` | médio | auditoria | host | `idempotency_key` |
| `income_update` | Escrita | `income.write` | Competência ≠ caixa; cancelada ocupa a vaga | `commands.income.*` | médio | auditoria | host | por estado (definir X) |
| `income_delete` | Destrutiva | `income.write` | Exclusão lógica (a vaga da ocorrência fica) | `commands.income.delete_income` | médio | auditoria | host | por estado (definir X) |
| `income_restore` | Escrita | `income.write` | Desfaz a exclusão lógica | `commands.income.restore_income` | baixo | auditoria | host | por estado (definir X) |
| `settlements_create` | Escrita | `settlements.write` | Direção e teto da dívida (0009/0031), trava do espaço | `commands.settlements.create_settlement` | alto — dívida entre pessoas | WS + auditoria | host | `idempotency_key` |
| `settlements_delete` | Destrutiva | `settlements.write` | Só o autor (ou admin) | `commands.settlements.delete_settlement` | alto | WS + auditoria | host | por estado (definir X) |
| `recurring_create` | Escrita | `planning.write` | Snapshot da divisão (0012), cartão coerente (0032) | `commands.recurring.create_recurring` | médio | materializa ocorrências conforme `materialize`; WS | host | `idempotency_key` |
| `recurring_update` | Escrita | `planning.write` | Pagas congeladas; escopo das não pagas (0012) | `commands.recurring.update_recurring` | médio | reescreve ocorrências não pagas; WS | host | por estado (definir X) |
| `recurring_delete` | Destrutiva | `planning.write` | Lançado continua; `cancel_open_occurrences` cancela os não pagos (ADR 0030) | `commands.recurring.delete_recurring / income.delete_recurring_income` | médio | WS | host | por estado (definir X) |
| `budgets_set` | Escrita | `planning.write` | Upsert por (espaço, dono, categoria, mês) | `commands.planning.create_estimate` | baixo | WS | host | por estado (definir X) |
| `categories_create` | Escrita | `planning.write` | Nome único por espaço; excluída é reativada (categoria, tag ou estabelecimento) | `commands.planning.create_category / create_tag, commands.merchants.create_merchant` | baixo | WS | host | por estado (definir X) |
| `categories_update` | Escrita | `planning.write` | Nome único; tag e estabelecimento excluídos saem dos lançamentos; apelido de um só (0038) | `commands.planning.update_*/delete_*, commands.merchants` | médio — renomeia para todos | WS | host | por estado (definir X) |
| `attachments_upload_link` | Escrita | `transactions.write` | Anexo pelo mesmo comando da tela (tipos, conteúdo real, cota; ADR 0007); link de uso único, 10 min | `commands/attachments.add_attachment` | médio — o link de envio aparece na conversa | emite o link; o curl cria 1 anexo | host | por estado (definir X) |
| `attachments_get` | Leitura | `finance.read` | Anexo herda a visibilidade do lançamento (0018); teto de tamanho | `commands.attachments.read_attachment_bytes` | alto — o conteúdo vai para o provedor do agente | nenhum | — | natural |
| `attachments_delete` | Destrutiva | `transactions.write` | Membro apaga os próprios; admin, qualquer um | `commands.attachments.delete_attachment` | alto — sem desfazer | blob liberado após o commit; WS | host | por estado (definir X) |
| `attachments_add` | Escrita | `transactions.write` | Mesmo comando da tela (tipos, conteúdo real, cota); download SSRF-seguro com hosts permitidos | `services/remote_file + commands.attachments.store_attachment` | médio | cria 1 anexo; WS | host | por estado (definir X) |

## Por rota REST

187 rotas.

| Rota | Funcionalidade | Tool(s) | Observação |
|---|---|---|---|
| `GET /` | Raiz do backend | **não exposta** | Infraestrutura (saúde, raiz). |
| `GET /api/v1/health` | Saúde | **não exposta** | Infraestrutura (saúde, raiz). |
| `GET /api/v1/admin/audit` | Admin: trilha | **não exposta** | Administração da plataforma (ADR 0026): operador do site, nunca um agente. |
| `GET /api/v1/admin/health` | Admin: saúde | **não exposta** | Administração da plataforma (ADR 0026): operador do site, nunca um agente. |
| `GET /api/v1/admin/overview` | Admin: visão geral | **não exposta** | Administração da plataforma (ADR 0026): operador do site, nunca um agente. |
| `GET /api/v1/admin/registration-invites` | Admin: convites de cadastro | **não exposta** | Administração da plataforma (ADR 0026): operador do site, nunca um agente. |
| `POST /api/v1/admin/registration-invites` | Admin: emitir convite de cadastro | **não exposta** | Administração da plataforma (ADR 0026): operador do site, nunca um agente. |
| `DELETE /api/v1/admin/registration-invites/{invite_id}` | Admin: revogar convite | **não exposta** | Administração da plataforma (ADR 0026): operador do site, nunca um agente. |
| `GET /api/v1/admin/settings` | Admin: configurações | **não exposta** | Administração da plataforma (ADR 0026): operador do site, nunca um agente. |
| `PUT /api/v1/admin/settings` | Admin: alterar configurações | **não exposta** | Administração da plataforma (ADR 0026): operador do site, nunca um agente. |
| `POST /api/v1/admin/settings/test-email` | Admin: testar e-mail | **não exposta** | Administração da plataforma (ADR 0026): operador do site, nunca um agente. |
| `GET /api/v1/admin/users` | Admin: usuários | **não exposta** | Administração da plataforma (ADR 0026): operador do site, nunca um agente. |
| `DELETE /api/v1/admin/users/{user_id}` | Admin: excluir usuário | **não exposta** | Administração da plataforma (ADR 0026): operador do site, nunca um agente. |
| `PATCH /api/v1/admin/users/{user_id}` | Admin: alterar usuário | **não exposta** | Administração da plataforma (ADR 0026): operador do site, nunca um agente. |
| `POST /api/v1/admin/users/{user_id}/revoke-sessions` | Admin: encerrar sessões (revoga também os agentes) | **não exposta** | Administração da plataforma (ADR 0026): operador do site, nunca um agente. |
| `POST /api/v1/auth/change-password` | Trocar senha (revoga os agentes conectados) | **não exposta** | Credencial e sessão (senha, cadastro, Google, refresh): nada disso passa por agente. |
| `POST /api/v1/auth/forgot-password` | Esqueci a senha | **não exposta** | Credencial e sessão (senha, cadastro, Google, refresh): nada disso passa por agente. |
| `GET /api/v1/auth/google/callback` | Login Google (retorno) | **não exposta** | Credencial e sessão (senha, cadastro, Google, refresh): nada disso passa por agente. |
| `GET /api/v1/auth/google/login` | Login Google (início) | **não exposta** | Credencial e sessão (senha, cadastro, Google, refresh): nada disso passa por agente. |
| `POST /api/v1/auth/login` | Login | **não exposta** | Credencial e sessão (senha, cadastro, Google, refresh): nada disso passa por agente. |
| `POST /api/v1/auth/logout` | Logout | **não exposta** | Credencial e sessão (senha, cadastro, Google, refresh): nada disso passa por agente. |
| `GET /api/v1/auth/me` | Perfil da conta | `profile_get` | O agente recebe id opaco, nome, e-mail, fuso e 'hoje' — nunca o id interno. |
| `PATCH /api/v1/auth/me` | Editar perfil | **não exposta** | Recurso de interface do app (notificações, push, avatar, preferências), sem sentido para um agente. |
| `DELETE /api/v1/auth/me/avatar` | Remover foto | **não exposta** | Recurso de interface do app (notificações, push, avatar, preferências), sem sentido para um agente. |
| `PUT /api/v1/auth/me/avatar` | Enviar foto | **não exposta** | Recurso de interface do app (notificações, push, avatar, preferências), sem sentido para um agente. |
| `POST /api/v1/auth/onboarding` | Primeiros passos | **não exposta** | Recurso de interface do app (notificações, push, avatar, preferências), sem sentido para um agente. |
| `POST /api/v1/auth/refresh` | Renovar sessão | **não exposta** | Credencial e sessão (senha, cadastro, Google, refresh): nada disso passa por agente. |
| `POST /api/v1/auth/register` | Cadastro | **não exposta** | Credencial e sessão (senha, cadastro, Google, refresh): nada disso passa por agente. |
| `GET /api/v1/auth/registration-policy` | Política de cadastro | **não exposta** | Credencial e sessão (senha, cadastro, Google, refresh): nada disso passa por agente. |
| `POST /api/v1/auth/reset-password` | Redefinir senha (revoga os agentes) | **não exposta** | Credencial e sessão (senha, cadastro, Google, refresh): nada disso passa por agente. |
| `GET /api/v1/auth/users/{user_id}/avatar` | Foto de usuário | **não exposta** | Recurso de interface do app (notificações, push, avatar, preferências), sem sentido para um agente. |
| `POST /api/v1/invites/accept/{token}` | Aceitar convite | **não exposta** | Quem participa de um espaço e com que papel muda quem vê o dinheiro de outras pessoas: decisão humana, no app. |
| `POST /api/v1/invites/decline/{token}` | Recusar convite | **não exposta** | Quem participa de um espaço e com que papel muda quem vê o dinheiro de outras pessoas: decisão humana, no app. |
| `GET /api/v1/invites/info/{token}` | Dados do convite | **não exposta** | Quem participa de um espaço e com que papel muda quem vê o dinheiro de outras pessoas: decisão humana, no app. |
| `GET /api/v1/workspaces/{workspace_id}/invites` | Convites do espaço | **não exposta** | Quem participa de um espaço e com que papel muda quem vê o dinheiro de outras pessoas: decisão humana, no app. |
| `POST /api/v1/workspaces/{workspace_id}/invites` | Convidar por e-mail | **não exposta** | Quem participa de um espaço e com que papel muda quem vê o dinheiro de outras pessoas: decisão humana, no app. |
| `POST /api/v1/workspaces/{workspace_id}/invites/link` | Link de convite | **não exposta** | Quem participa de um espaço e com que papel muda quem vê o dinheiro de outras pessoas: decisão humana, no app. |
| `DELETE /api/v1/workspaces/{workspace_id}/invites/{invite_id}` | Revogar convite | **não exposta** | Quem participa de um espaço e com que papel muda quem vê o dinheiro de outras pessoas: decisão humana, no app. |
| `POST /api/v1/workspaces/{workspace_id}/leave` | Sair do espaço | **não exposta** | Quem participa de um espaço e com que papel muda quem vê o dinheiro de outras pessoas: decisão humana, no app. |
| `GET /api/v1/workspaces/{workspace_id}/members` | Membros do espaço | `people_list` |  |
| `DELETE /api/v1/workspaces/{workspace_id}/members/{user_id}` | Remover membro | **não exposta** | Quem participa de um espaço e com que papel muda quem vê o dinheiro de outras pessoas: decisão humana, no app. |
| `PATCH /api/v1/workspaces/{workspace_id}/members/{user_id}` | Mudar papel/acesso | **não exposta** | Quem participa de um espaço e com que papel muda quem vê o dinheiro de outras pessoas: decisão humana, no app. |
| `POST /api/v1/workspaces/{workspace_id}/members/{user_id}/transfer-ownership` | Transferir propriedade | **não exposta** | Quem participa de um espaço e com que papel muda quem vê o dinheiro de outras pessoas: decisão humana, no app. |
| `GET /api/v1/me/activity` | Feed de atividade | `transactions_search` | O agente consulta o que mudou pela busca, com filtros. |
| `GET /api/v1/me/ai-integrations` | Integrações com IA (status e conexões) | **não exposta** | Tela da própria integração com IA — alcançável só pela sessão do app, nunca por token de agente. |
| `GET /api/v1/me/ai-integrations/activity` | Integrações com IA (atividade) | **não exposta** | Tela da própria integração com IA — alcançável só pela sessão do app, nunca por token de agente. |
| `DELETE /api/v1/me/ai-integrations/connections/{grant_id}` | Desconectar agente | **não exposta** | Tela da própria integração com IA — alcançável só pela sessão do app, nunca por token de agente. |
| `GET /api/v1/me/balance` | Saldo e projeção | `accounts_list` |  |
| `GET /api/v1/me/commitments` | Compromissos futuros | `payables_list` |  |
| `GET /api/v1/me/credit-cards` | Cartões | `cards_list` |  |
| `POST /api/v1/me/credit-cards` | Cadastrar cartão | **não exposta** | Cadastro de cartão/conta é raro, tem efeitos em fatura e saldo, e é feito uma vez no app. |
| `DELETE /api/v1/me/credit-cards/{card_id}` | Excluir cartão | **não exposta** | Cadastro de cartão/conta é raro, tem efeitos em fatura e saldo, e é feito uma vez no app. |
| `PUT /api/v1/me/credit-cards/{card_id}` | Editar cartão | **não exposta** | Cadastro de cartão/conta é raro, tem efeitos em fatura e saldo, e é feito uma vez no app. |
| `GET /api/v1/me/credit-cards/{card_id}/statement-for` | Fatura de destino de uma data | `cards_list`, `transactions_create` | O agente não escolhe fatura: o servidor deriva ao criar (ADR 0002). |
| `GET /api/v1/me/credit-cards/{card_id}/statements` | Faturas do cartão | `statements_get` |  |
| `GET /api/v1/me/credit-cards/{card_id}/statements/{statement_id}` | Detalhe da fatura | `statements_get`, `statements_show` |  |
| `POST /api/v1/me/credit-cards/{card_id}/statements/{statement_id}/close` | Fechar fatura | `statements_pay` | Só fechada junto com o pagamento, e só com o ciclo já encerrado. |
| `POST /api/v1/me/credit-cards/{card_id}/statements/{statement_id}/pay` | Pagar fatura | `statements_pay` |  |
| `POST /api/v1/me/credit-cards/{card_id}/statements/{statement_id}/reopen` | Reabrir fatura | `statements_reopen` | Só quando há pagamento a estornar: repetir a chamada não anda mais um passo. |
| `GET /api/v1/me/debts` | Dívidas (todas as casas) | `debts_summary` |  |
| `GET /api/v1/me/debts/by-month` | Dívidas por mês | `debts_summary` |  |
| `GET /api/v1/me/debts/monthly` | Dívidas do mês | `debts_summary` |  |
| `GET /api/v1/me/financing` | Financiamentos | `financings_list`, `payables_list` | Financiamento é contrato com cronograma e quitação: cadastrar, editar, quitar ou excluir fica no app (decisão do dono). O agente lê tudo (financings_list) e paga/desfaz parcela (financings_installment). |
| `POST /api/v1/me/financing` | Cadastrar financiamento | **não exposta** | Financiamento é contrato com cronograma e quitação: cadastrar, editar, quitar ou excluir fica no app (decisão do dono). O agente lê tudo (financings_list) e paga/desfaz parcela (financings_installment). |
| `DELETE /api/v1/me/financing/{financing_id}` | Excluir financiamento | **não exposta** | Financiamento é contrato com cronograma e quitação: cadastrar, editar, quitar ou excluir fica no app (decisão do dono). O agente lê tudo (financings_list) e paga/desfaz parcela (financings_installment). |
| `GET /api/v1/me/financing/{financing_id}` | Detalhe do financiamento | `financings_list` | Financiamento é contrato com cronograma e quitação: cadastrar, editar, quitar ou excluir fica no app (decisão do dono). O agente lê tudo (financings_list) e paga/desfaz parcela (financings_installment). |
| `PUT /api/v1/me/financing/{financing_id}` | Editar financiamento | **não exposta** | Financiamento é contrato com cronograma e quitação: cadastrar, editar, quitar ou excluir fica no app (decisão do dono). O agente lê tudo (financings_list) e paga/desfaz parcela (financings_installment). |
| `POST /api/v1/me/financing/{financing_id}/early-settlement` | Quitação antecipada | **não exposta** | Financiamento é contrato com cronograma e quitação: cadastrar, editar, quitar ou excluir fica no app (decisão do dono). O agente lê tudo (financings_list) e paga/desfaz parcela (financings_installment). |
| `POST /api/v1/me/financing/{financing_id}/installments/settle-past` | Quitar parcelas passadas | **não exposta** | Financiamento é contrato com cronograma e quitação: cadastrar, editar, quitar ou excluir fica no app (decisão do dono). O agente lê tudo (financings_list) e paga/desfaz parcela (financings_installment). |
| `POST /api/v1/me/financing/{financing_id}/installments/{installment_number}/pay` | Pagar parcela | `financings_installment` | action=pay |
| `POST /api/v1/me/financing/{financing_id}/installments/{installment_number}/unpay` | Desfazer pagamento de parcela | `financings_installment` | action=unpay |
| `GET /api/v1/me/financing/{financing_id}/schedule` | Cronograma | `financings_list` | Cronograma paginado com `financing`. |
| `GET /api/v1/me/income` | Rendas | `income_list` |  |
| `POST /api/v1/me/income` | Registrar renda | `income_create` |  |
| `DELETE /api/v1/me/income/{income_id}` | Excluir renda | `income_delete`, `income_restore` | Exclusão lógica; income_restore desfaz (o app ainda não tem o botão). |
| `PUT /api/v1/me/income/{income_id}` | Editar renda | `income_update` |  |
| `POST /api/v1/me/income/{income_id}/cancel` | Cancelar renda | `income_update` |  |
| `POST /api/v1/me/income/{income_id}/receive` | Confirmar recebimento | `income_update` |  |
| `POST /api/v1/me/income/{income_id}/unreceive` | Desfazer recebimento | `income_update` |  |
| `GET /api/v1/me/ledger` | Extrato global | `accounts_statement` | Sem `account`: o caixa do mês, as mesmas linhas da tela. |
| `GET /api/v1/me/notification-preferences` | Preferências de aviso | **não exposta** | Recurso de interface do app (notificações, push, avatar, preferências), sem sentido para um agente. |
| `PUT /api/v1/me/notification-preferences` | Alterar preferências de aviso | **não exposta** | Recurso de interface do app (notificações, push, avatar, preferências), sem sentido para um agente. |
| `GET /api/v1/me/overview` | Visão do mês | `reports_summary`, `reports_show` |  |
| `GET /api/v1/me/payables` | Contas a pagar | `payables_list` |  |
| `GET /api/v1/me/payment-accounts` | Contas de pagamento | `accounts_list` |  |
| `POST /api/v1/me/payment-accounts` | Cadastrar conta | **não exposta** | Cadastro de cartão/conta é raro, tem efeitos em fatura e saldo, e é feito uma vez no app. |
| `DELETE /api/v1/me/payment-accounts/{account_id}` | Excluir conta | **não exposta** | Cadastro de cartão/conta é raro, tem efeitos em fatura e saldo, e é feito uma vez no app. |
| `PUT /api/v1/me/payment-accounts/{account_id}` | Editar conta | **não exposta** | Cadastro de cartão/conta é raro, tem efeitos em fatura e saldo, e é feito uma vez no app. |
| `POST /api/v1/me/payment-accounts/{account_id}/adjustment` | Conciliar saldo | `accounts_adjust_balance` |  |
| `PUT /api/v1/me/payment-accounts/{account_id}/opening-balance` | Saldo inicial | **não exposta** | Cadastro de cartão/conta é raro, tem efeitos em fatura e saldo, e é feito uma vez no app. |
| `GET /api/v1/me/payment-accounts/{account_id}/statement` | Extrato da conta | `accounts_statement` | Com saldo corrente linha a linha. |
| `GET /api/v1/me/push/config` | Push: configuração | **não exposta** | Recurso de interface do app (notificações, push, avatar, preferências), sem sentido para um agente. |
| `DELETE /api/v1/me/push/subscriptions` | Push: cancelar | **não exposta** | Recurso de interface do app (notificações, push, avatar, preferências), sem sentido para um agente. |
| `POST /api/v1/me/push/subscriptions` | Push: assinar | **não exposta** | Recurso de interface do app (notificações, push, avatar, preferências), sem sentido para um agente. |
| `GET /api/v1/me/recurring-income` | Rendas recorrentes | `recurring_list` |  |
| `POST /api/v1/me/recurring-income` | Criar renda recorrente | `recurring_create` | kind=income |
| `POST /api/v1/me/recurring-income/generate` | Gerar ocorrências de renda | **não exposta** | Materialização é do cron horário; leitura do agente nunca escreve. |
| `DELETE /api/v1/me/recurring-income/{recurring_id}` | Excluir renda recorrente | `recurring_delete` | kind=income |
| `PUT /api/v1/me/recurring-income/{recurring_id}` | Editar renda recorrente | `recurring_update` | kind=income |
| `GET /api/v1/me/registration-invites` | Meus convites de cadastro | **não exposta** | Quem participa de um espaço e com que papel muda quem vê o dinheiro de outras pessoas: decisão humana, no app. |
| `POST /api/v1/me/registration-invites` | Convidar alguém para o site | **não exposta** | Quem participa de um espaço e com que papel muda quem vê o dinheiro de outras pessoas: decisão humana, no app. |
| `PATCH /api/v1/me/report-currency` | Moeda de relatório | **não exposta** | Recurso de interface do app (notificações, push, avatar, preferências), sem sentido para um agente. |
| `GET /api/v1/me/reports` | Relatórios pessoais | `reports_summary`, `reports_breakdown`, `budgets_list` |  |
| `GET /api/v1/me/search` | Busca global | `transactions_search` |  |
| `GET /api/v1/me/settlements` | Acertos (todas as casas) | `debts_summary` |  |
| `PUT /api/v1/me/settlements/{settlement_id}/account` | Conta do credor num acerto | **não exposta** | Operação rara e destrutiva, sem pedido real de uso por agente; fica no app, com a confirmação da tela. |
| `GET /api/v1/me/transfers` | Transferências | `transfers_list` |  |
| `POST /api/v1/me/imports/parse` | Ler extrato de conta | `imports_preview` | Com `account`: o agente extrai as linhas com o sentido; o app confere duplicatas e sugere a classificação. |
| `POST /api/v1/me/imports/commit` | Importar extrato de conta | `imports_commit` | Com `account`: mesmo comando (commit_account_statement). |
| `GET /api/v1/me/imports` | Importações de extrato | `imports_list` | Os lotes de extrato entram na mesma lista. |
| `GET /api/v1/me/imports/{batch_id}` | Linhas de uma importação de extrato | `imports_list` | imports_list com batch_id. |
| `POST /api/v1/me/imports/{batch_id}/undo` | Desfazer importação de extrato | `imports_undo` | Mesmo comando (undo_account_import): exclui despesa, renda e transferência e estorna o pagamento de fatura. |
| `POST /api/v1/me/transfers` | Transferir entre contas | `transfers_create` |  |
| `DELETE /api/v1/me/transfers/{transfer_id}` | Excluir transferência | `transfers_delete` |  |
| `GET /api/v1/notifications` | Notificações | **não exposta** | Recurso de interface do app (notificações, push, avatar, preferências), sem sentido para um agente. |
| `POST /api/v1/notifications/read-all` | Marcar todas como lidas | **não exposta** | Recurso de interface do app (notificações, push, avatar, preferências), sem sentido para um agente. |
| `POST /api/v1/notifications/{notification_id}/read` | Marcar como lida | **não exposta** | Recurso de interface do app (notificações, push, avatar, preferências), sem sentido para um agente. |
| `GET /api/v1/oauth/consent` | Consentimento: detalhes do pedido | **não exposta** | Tela da própria integração com IA — alcançável só pela sessão do app, nunca por token de agente. |
| `POST /api/v1/oauth/consent/approve` | Consentimento: autorizar | **não exposta** | Tela da própria integração com IA — alcançável só pela sessão do app, nunca por token de agente. |
| `POST /api/v1/oauth/consent/deny` | Consentimento: negar | **não exposta** | Tela da própria integração com IA — alcançável só pela sessão do app, nunca por token de agente. |
| `POST /api/v1/mcp/uploads` | Envio de anexo pelo link do MCP | `attachments_upload_link` | O destino do link de uso único: sem cookie, autorizado pelo token no cabeçalho. |
| `GET /api/v1/workspaces/` | Espaços | `spaces_list` |  |
| `POST /api/v1/workspaces/` | Criar espaço | **não exposta** | Criar/excluir espaço ou trocar a moeda-base reescreve a visão de todos os membros: raro e amplo demais para um agente. |
| `DELETE /api/v1/workspaces/{workspace_id}` | Excluir espaço | **não exposta** | Criar/excluir espaço ou trocar a moeda-base reescreve a visão de todos os membros: raro e amplo demais para um agente. |
| `GET /api/v1/workspaces/{workspace_id}` | Detalhe do espaço | `spaces_list` |  |
| `PUT /api/v1/workspaces/{workspace_id}` | Editar espaço | **não exposta** | Criar/excluir espaço ou trocar a moeda-base reescreve a visão de todos os membros: raro e amplo demais para um agente. |
| `GET /api/v1/workspaces/{workspace_id}/base-currency/preview` | Prévia de troca de moeda-base | **não exposta** | Criar/excluir espaço ou trocar a moeda-base reescreve a visão de todos os membros: raro e amplo demais para um agente. |
| `GET /api/v1/workspaces/{workspace_id}/audit` | Auditoria do espaço | `transactions_history` | O espaço inteiro segue só no app (admin). O agente vê o histórico de UM lançamento que a pessoa já vê (decisão do dono). |
| `GET /api/v1/workspaces/{workspace_id}/analytics/estimates` | Metas do mês | `budgets_list` |  |
| `POST /api/v1/workspaces/{workspace_id}/analytics/estimates` | Definir meta | `budgets_set` |  |
| `DELETE /api/v1/workspaces/{workspace_id}/analytics/estimates/{estimate_id}` | Excluir meta | `budgets_set` | Zerar a meta (amount=0) em vez de apagar. |
| `PUT /api/v1/workspaces/{workspace_id}/analytics/estimates/{estimate_id}` | Editar meta | `budgets_set` |  |
| `GET /api/v1/workspaces/{workspace_id}/analytics/exchange-rate` | Cotação isolada | `transactions_create` | A conversão acontece dentro da criação (PTAX + IOF), não como consulta solta. |
| `GET /api/v1/workspaces/{workspace_id}/analytics/forecast` | Previsão | `reports_summary`, `payables_list` |  |
| `GET /api/v1/workspaces/{workspace_id}/analytics/reports` | Relatórios do espaço | `reports_summary`, `reports_breakdown` |  |
| `GET /api/v1/workspaces/{workspace_id}/analytics/summary` | Resumo do espaço | `reports_summary` |  |
| `GET /api/v1/workspaces/{workspace_id}/categories` | Categorias | `categories_list` |  |
| `POST /api/v1/workspaces/{workspace_id}/categories` | Criar categoria | `categories_create` |  |
| `DELETE /api/v1/workspaces/{workspace_id}/categories/{category_id}` | Excluir categoria | `categories_update` | delete=true |
| `PUT /api/v1/workspaces/{workspace_id}/categories/{category_id}` | Editar categoria | `categories_update` |  |
| `GET /api/v1/workspaces/{workspace_id}/tags` | Tags | `categories_list` |  |
| `POST /api/v1/workspaces/{workspace_id}/tags` | Criar tag | `categories_create` | kind=tag |
| `DELETE /api/v1/workspaces/{workspace_id}/tags/{tag_id}` | Excluir tag | `categories_update` | kind=tag, delete=true |
| `PUT /api/v1/workspaces/{workspace_id}/tags/{tag_id}` | Editar tag | `categories_update` | kind=tag |
| `GET /api/v1/workspaces/{workspace_id}/merchants` | Estabelecimentos | `categories_list` |  |
| `POST /api/v1/workspaces/{workspace_id}/merchants` | Criar estabelecimento | `categories_create` | kind=merchant |
| `PUT /api/v1/workspaces/{workspace_id}/merchants/{merchant_id}` | Editar estabelecimento | `categories_update` | kind=merchant |
| `DELETE /api/v1/workspaces/{workspace_id}/merchants/{merchant_id}` | Excluir estabelecimento | `categories_update` | kind=merchant, delete=true |
| `POST /api/v1/workspaces/{workspace_id}/merchants/{merchant_id}/merge` | Mesclar estabelecimentos | `categories_update` | kind=merchant, merge_into |
| `GET /api/v1/workspaces/{workspace_id}/merchants/spending` | Gasto por estabelecimento | `reports_breakdown` | group_by=merchant |
| `GET /api/v1/workspaces/{workspace_id}/debts` | Quem deve a quem (acumulado) | `debts_summary` |  |
| `GET /api/v1/workspaces/{workspace_id}/debts/by-month` | Dívidas por mês | `debts_summary` |  |
| `GET /api/v1/workspaces/{workspace_id}/debts/monthly` | Ledger do mês | `debts_summary` |  |
| `GET /api/v1/workspaces/{workspace_id}/settlements` | Acertos | `debts_summary` |  |
| `POST /api/v1/workspaces/{workspace_id}/settlements` | Registrar acerto | `settlements_create` |  |
| `DELETE /api/v1/workspaces/{workspace_id}/settlements/{settlement_id}` | Desfazer acerto | `settlements_delete` |  |
| `GET /api/v1/workspaces/{workspace_id}/payables` | Contas a pagar do espaço | `payables_list` |  |
| `POST /api/v1/workspaces/{workspace_id}/payables/settle` | Quitar contas em lote | `transactions_update` | Marcar como paga é por lançamento (settled=true). |
| `GET /api/v1/workspaces/{workspace_id}/recurring` | Recorrências | `recurring_list` |  |
| `POST /api/v1/workspaces/{workspace_id}/recurring` | Criar recorrência | `recurring_create` |  |
| `POST /api/v1/workspaces/{workspace_id}/recurring/generate` | Gerar ocorrências | **não exposta** | Materialização é do cron horário; leitura do agente nunca escreve. |
| `DELETE /api/v1/workspaces/{workspace_id}/recurring/{recurring_id}` | Excluir recorrência | `recurring_delete`, `recurring_update` | Pausar é recurring_update active=false; excluir de vez, recurring_delete. |
| `GET /api/v1/workspaces/{workspace_id}/recurring/{recurring_id}` | Detalhe da recorrência | `recurring_get` |  |
| `PUT /api/v1/workspaces/{workspace_id}/recurring/{recurring_id}` | Editar recorrência | `recurring_update` | Sem o fluxo de revisão por ocorrência (ADR 0030): usa o escopo none\|future\|all. |
| `POST /api/v1/workspaces/{workspace_id}/recurring/{recurring_id}/preview` | Prévia da revisão | **não exposta** | Revisão ocorrência a ocorrência é interação de tela; o agente usa apply_to. |
| `POST /api/v1/workspaces/{workspace_id}/imports/parse` | Ler CSV | `imports_preview` | O agente extrai as linhas do extrato (PDF, foto, texto); o app confere duplicatas. |
| `POST /api/v1/workspaces/{workspace_id}/imports/commit` | Importar lote | `imports_commit`, `imports_list` | Os lotes feitos (e desfazer um) em imports_list + transactions_bulk_preview com import_batch_id. |
| `GET /api/v1/workspaces/{workspace_id}/imports` | Histórico de importações | `imports_list` | Só os lotes da própria pessoa, como no app. |
| `GET /api/v1/workspaces/{workspace_id}/imports/{batch_id}` | Linhas de uma importação | `imports_list` | imports_list com batch_id. |
| `POST /api/v1/workspaces/{workspace_id}/imports/{batch_id}/undo` | Desfazer importação | `imports_undo` | Mesmo comando (undo_batch), em duas etapas: a prévia mostra o que sai e os recibos, o token executa. |
| `GET /api/v1/workspaces/{workspace_id}/transactions/` | Lançamentos do espaço | `transactions_search`, `view_show` | view_show(view=transactions) desenha a lista paginada. |
| `POST /api/v1/workspaces/{workspace_id}/transactions/` | Criar lançamento | `transactions_create` |  |
| `POST /api/v1/workspaces/{workspace_id}/transactions/bulk` | Criar em lote | `imports_commit`, `transactions_create` | Lote pela importação (com dedup) ou uma criação por despesa (com idempotency_key). |
| `POST /api/v1/workspaces/{workspace_id}/transactions/bulk-categorize` | Categorizar em lote | `transactions_bulk_preview`, `transactions_bulk_categorize`, `transactions_bulk_update` | Recategorizar, tag e marcar como pago em lote: transactions_bulk_update, pela mesma prévia. |
| `POST /api/v1/workspaces/{workspace_id}/transactions/preview` | Prévia da divisão | `transactions_create` | A saída da criação já traz a divisão calculada. |
| `DELETE /api/v1/workspaces/{workspace_id}/transactions/{transaction_id}` | Excluir lançamento | `transactions_delete`, `transactions_bulk_preview`, `transactions_bulk_delete` |  |
| `GET /api/v1/workspaces/{workspace_id}/transactions/{transaction_id}` | Ver lançamento | `transactions_get`, `transactions_show` |  |
| `PUT /api/v1/workspaces/{workspace_id}/transactions/{transaction_id}` | Editar lançamento | `transactions_update` |  |
| `GET /api/v1/workspaces/{workspace_id}/transactions/{transaction_id}/attachments` | Anexos do lançamento | `transactions_get` | `files` traz os metadados de cada anexo. |
| `POST /api/v1/workspaces/{workspace_id}/transactions/{transaction_id}/attachments` | Enviar anexo | `attachments_upload_link`, `attachments_add` | No ChatGPT, o arquivo que a pessoa pôs na conversa chega por `openai/fileParams` e o servidor o baixa (attachments_add, hosts permitidos em MCP_FILE_URL_HOSTS). Pelo terminal: attachments_upload_link. |
| `DELETE /api/v1/workspaces/{workspace_id}/attachments/{attachment_id}` | Excluir anexo | `attachments_delete` | Anexos: o agente lê o conteúdo (attachments_get) e apaga (attachments_delete). |
| `GET /api/v1/workspaces/{workspace_id}/attachments/{attachment_id}` | Baixar anexo | `attachments_get` | Imagem ou PDF entregue ao modelo até MCP_ATTACHMENT_TO_MODEL_MAX_BYTES. |
| `DELETE /api/v1/workspaces/{workspace_id}/transactions/{transaction_id}/installment-group` | Excluir compra parcelada | `transactions_delete` | scope=purchase |
| `GET /api/v1/workspaces/{workspace_id}/transactions/{transaction_id}/installment-group` | Compra parcelada inteira | `transactions_search`, `transactions_get` |  |
| `PUT /api/v1/workspaces/{workspace_id}/transactions/{transaction_id}/installment-group` | Editar compra parcelada | `transactions_update` | scope=purchase |
| `POST /api/v1/workspaces/{workspace_id}/transactions/{transaction_id}/installment-group/cancel` | Cancelar parcelas em aberto | `transactions_update` | status=cancelled por parcela |
| `POST /api/v1/workspaces/{workspace_id}/transactions/{transaction_id}/restore` | Desfazer exclusão | `transactions_restore` |  |
