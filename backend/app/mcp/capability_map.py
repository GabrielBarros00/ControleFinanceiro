"""Mapa de capacidades: TODA rota REST do app → a tool MCP que a cobre, ou o motivo de não cobrir.

É a fonte do `docs/mcp/CAPABILITY_MAP.md` (gerado por `app.mcp.docs`) e tem
denominador: `tests/mcp/test_capability_map.py` falha se uma rota nova aparece
no OpenAPI sem entrar aqui, se uma entrada daqui não existe mais, ou se uma
tool do registro não é citada. Funcionalidade nova no app obriga a decidir, no
mesmo PR, se o agente a alcança — e a escrever por quê.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Rota:
    capacidade: str
    tools: tuple[str, ...] = ()
    #: Por que NÃO há tool (quando `tools` é vazio) ou o que a tool faz diferente.
    nota: str = ""


# Motivos recorrentes de NÃO exposição ------------------------------------------------
ADMIN = "Administração da plataforma (ADR 0026): operador do site, nunca um agente."
CREDENCIAL = "Credencial e sessão (senha, cadastro, Google, refresh): nada disso passa por agente."
PESSOAS = "Quem participa de um espaço e com que papel muda quem vê o dinheiro de outras pessoas: decisão humana, no app."
ESPACO = "Criar/excluir espaço ou trocar a moeda-base reescreve a visão de todos os membros: raro e amplo demais para um agente."
CADASTRO = "Cadastro de cartão/conta é raro, tem efeitos em fatura e saldo, e é feito uma vez no app."
FINANCIAMENTO = "Financiamento é contrato com cronograma e quitação; o agente só lê as parcelas (payables_list)."
ANEXO = "Arquivo binário: o agente não lê nem apaga anexos."
#: O envio sim, pelos agentes de terminal: link de uso único + curl (app/mcp/uploads.py).
ANEXO_ENVIO = (
    "Pelo terminal: `attachments_upload_link` emite um link de uso único e o arquivo vai do disco "
    "direto para o app (curl), pelo mesmo comando da tela. Nos apps de chat na web, pela tela."
)
INTERFACE = "Recurso de interface do app (notificações, push, avatar, preferências), sem sentido para um agente."
INFRA = "Infraestrutura (saúde, raiz)."
PROPRIA = "Tela da própria integração com IA — alcançável só pela sessão do app, nunca por token de agente."
RARO = "Operação rara e destrutiva, sem pedido real de uso por agente; fica no app, com a confirmação da tela."

API = "/api/v1"
W = f"{API}/workspaces/{{workspace_id}}"

ROTAS: dict[str, Rota] = {
    # --- Infra e raiz -------------------------------------------------------------
    "GET /": Rota("Raiz do backend", nota=INFRA),
    f"GET {API}/health": Rota("Saúde", nota=INFRA),

    # --- Administração ------------------------------------------------------------
    f"GET {API}/admin/audit": Rota("Admin: trilha", nota=ADMIN),
    f"GET {API}/admin/health": Rota("Admin: saúde", nota=ADMIN),
    f"GET {API}/admin/overview": Rota("Admin: visão geral", nota=ADMIN),
    f"GET {API}/admin/registration-invites": Rota("Admin: convites de cadastro", nota=ADMIN),
    f"POST {API}/admin/registration-invites": Rota("Admin: emitir convite de cadastro", nota=ADMIN),
    f"DELETE {API}/admin/registration-invites/{{invite_id}}": Rota("Admin: revogar convite", nota=ADMIN),
    f"GET {API}/admin/settings": Rota("Admin: configurações", nota=ADMIN),
    f"PUT {API}/admin/settings": Rota("Admin: alterar configurações", nota=ADMIN),
    f"POST {API}/admin/settings/test-email": Rota("Admin: testar e-mail", nota=ADMIN),
    f"GET {API}/admin/users": Rota("Admin: usuários", nota=ADMIN),
    f"DELETE {API}/admin/users/{{user_id}}": Rota("Admin: excluir usuário", nota=ADMIN),
    f"PATCH {API}/admin/users/{{user_id}}": Rota("Admin: alterar usuário", nota=ADMIN),
    f"POST {API}/admin/users/{{user_id}}/revoke-sessions": Rota("Admin: encerrar sessões (revoga também os agentes)", nota=ADMIN),

    # --- Conta e sessão -------------------------------------------------------------
    f"POST {API}/auth/change-password": Rota("Trocar senha (revoga os agentes conectados)", nota=CREDENCIAL),
    f"POST {API}/auth/forgot-password": Rota("Esqueci a senha", nota=CREDENCIAL),
    f"GET {API}/auth/google/callback": Rota("Login Google (retorno)", nota=CREDENCIAL),
    f"GET {API}/auth/google/login": Rota("Login Google (início)", nota=CREDENCIAL),
    f"POST {API}/auth/login": Rota("Login", nota=CREDENCIAL),
    f"POST {API}/auth/logout": Rota("Logout", nota=CREDENCIAL),
    f"GET {API}/auth/me": Rota("Perfil da conta", ("profile_get",), "O agente recebe id opaco, nome, e-mail, fuso e 'hoje' — nunca o id interno."),
    f"PATCH {API}/auth/me": Rota("Editar perfil", nota=INTERFACE),
    f"DELETE {API}/auth/me/avatar": Rota("Remover foto", nota=INTERFACE),
    f"PUT {API}/auth/me/avatar": Rota("Enviar foto", nota=INTERFACE),
    f"POST {API}/auth/onboarding": Rota("Primeiros passos", nota=INTERFACE),
    f"POST {API}/auth/refresh": Rota("Renovar sessão", nota=CREDENCIAL),
    f"POST {API}/auth/register": Rota("Cadastro", nota=CREDENCIAL),
    f"GET {API}/auth/registration-policy": Rota("Política de cadastro", nota=CREDENCIAL),
    f"POST {API}/auth/reset-password": Rota("Redefinir senha (revoga os agentes)", nota=CREDENCIAL),
    f"GET {API}/auth/users/{{user_id}}/avatar": Rota("Foto de usuário", nota=INTERFACE),

    # --- Convites de espaço ---------------------------------------------------------
    f"POST {API}/invites/accept/{{token}}": Rota("Aceitar convite", nota=PESSOAS),
    f"POST {API}/invites/decline/{{token}}": Rota("Recusar convite", nota=PESSOAS),
    f"GET {API}/invites/info/{{token}}": Rota("Dados do convite", nota=PESSOAS),
    f"GET {W}/invites": Rota("Convites do espaço", nota=PESSOAS),
    f"POST {W}/invites": Rota("Convidar por e-mail", nota=PESSOAS),
    f"POST {W}/invites/link": Rota("Link de convite", nota=PESSOAS),
    f"DELETE {W}/invites/{{invite_id}}": Rota("Revogar convite", nota=PESSOAS),
    f"POST {W}/leave": Rota("Sair do espaço", nota=PESSOAS),
    f"GET {W}/members": Rota("Membros do espaço", ("people_list",)),
    f"DELETE {W}/members/{{user_id}}": Rota("Remover membro", nota=PESSOAS),
    f"PATCH {W}/members/{{user_id}}": Rota("Mudar papel/acesso", nota=PESSOAS),
    f"POST {W}/members/{{user_id}}/transfer-ownership": Rota("Transferir propriedade", nota=PESSOAS),

    # --- Camada pessoal -------------------------------------------------------------
    f"GET {API}/me/activity": Rota("Feed de atividade", ("transactions_search",), "O agente consulta o que mudou pela busca, com filtros."),
    f"GET {API}/me/ai-integrations": Rota("Integrações com IA (status e conexões)", nota=PROPRIA),
    f"GET {API}/me/ai-integrations/activity": Rota("Integrações com IA (atividade)", nota=PROPRIA),
    f"DELETE {API}/me/ai-integrations/connections/{{grant_id}}": Rota("Desconectar agente", nota=PROPRIA),
    f"GET {API}/me/balance": Rota("Saldo e projeção", ("accounts_list",)),
    f"GET {API}/me/commitments": Rota("Compromissos futuros", ("payables_list",)),
    f"GET {API}/me/credit-cards": Rota("Cartões", ("cards_list",)),
    f"POST {API}/me/credit-cards": Rota("Cadastrar cartão", nota=CADASTRO),
    f"DELETE {API}/me/credit-cards/{{card_id}}": Rota("Excluir cartão", nota=CADASTRO),
    f"PUT {API}/me/credit-cards/{{card_id}}": Rota("Editar cartão", nota=CADASTRO),
    f"GET {API}/me/credit-cards/{{card_id}}/statement-for": Rota("Fatura de destino de uma data", ("cards_list", "transactions_create"),
                                                                  "O agente não escolhe fatura: o servidor deriva ao criar (ADR 0002)."),
    f"GET {API}/me/credit-cards/{{card_id}}/statements": Rota("Faturas do cartão", ("statements_get",)),
    f"GET {API}/me/credit-cards/{{card_id}}/statements/{{statement_id}}": Rota("Detalhe da fatura", ("statements_get", "statements_show")),
    f"POST {API}/me/credit-cards/{{card_id}}/statements/{{statement_id}}/close": Rota(
        "Fechar fatura", ("statements_pay",), "Só fechada junto com o pagamento, e só com o ciclo já encerrado."),
    f"POST {API}/me/credit-cards/{{card_id}}/statements/{{statement_id}}/pay": Rota("Pagar fatura", ("statements_pay",)),
    f"POST {API}/me/credit-cards/{{card_id}}/statements/{{statement_id}}/reopen": Rota("Reabrir fatura", nota=RARO),
    f"GET {API}/me/debts": Rota("Dívidas (todas as casas)", ("debts_summary",)),
    f"GET {API}/me/debts/by-month": Rota("Dívidas por mês", ("debts_summary",)),
    f"GET {API}/me/debts/monthly": Rota("Dívidas do mês", ("debts_summary",)),
    f"GET {API}/me/financing": Rota("Financiamentos", ("payables_list",), FINANCIAMENTO),
    f"POST {API}/me/financing": Rota("Cadastrar financiamento", nota=FINANCIAMENTO),
    f"DELETE {API}/me/financing/{{financing_id}}": Rota("Excluir financiamento", nota=FINANCIAMENTO),
    f"GET {API}/me/financing/{{financing_id}}": Rota("Detalhe do financiamento", ("payables_list",), FINANCIAMENTO),
    f"PUT {API}/me/financing/{{financing_id}}": Rota("Editar financiamento", nota=FINANCIAMENTO),
    f"POST {API}/me/financing/{{financing_id}}/early-settlement": Rota("Quitação antecipada", nota=FINANCIAMENTO),
    f"POST {API}/me/financing/{{financing_id}}/installments/settle-past": Rota("Quitar parcelas passadas", nota=FINANCIAMENTO),
    f"POST {API}/me/financing/{{financing_id}}/installments/{{installment_number}}/pay": Rota("Pagar parcela", nota=FINANCIAMENTO),
    f"POST {API}/me/financing/{{financing_id}}/installments/{{installment_number}}/unpay": Rota("Desfazer pagamento de parcela", nota=FINANCIAMENTO),
    f"GET {API}/me/financing/{{financing_id}}/schedule": Rota("Cronograma", ("payables_list",), FINANCIAMENTO),
    f"GET {API}/me/income": Rota("Rendas", ("income_list",)),
    f"POST {API}/me/income": Rota("Registrar renda", ("income_create",)),
    f"DELETE {API}/me/income/{{income_id}}": Rota("Excluir renda", ("income_update",), "O agente cancela (status=cancelled), não apaga."),
    f"PUT {API}/me/income/{{income_id}}": Rota("Editar renda", ("income_update",)),
    f"POST {API}/me/income/{{income_id}}/cancel": Rota("Cancelar renda", ("income_update",)),
    f"POST {API}/me/income/{{income_id}}/receive": Rota("Confirmar recebimento", ("income_update",)),
    f"POST {API}/me/income/{{income_id}}/unreceive": Rota("Desfazer recebimento", ("income_update",)),
    f"GET {API}/me/ledger": Rota("Extrato global", ("transactions_search", "accounts_list")),
    f"GET {API}/me/notification-preferences": Rota("Preferências de aviso", nota=INTERFACE),
    f"PUT {API}/me/notification-preferences": Rota("Alterar preferências de aviso", nota=INTERFACE),
    f"GET {API}/me/overview": Rota("Visão do mês", ("reports_summary", "reports_show")),
    f"GET {API}/me/payables": Rota("Contas a pagar", ("payables_list",)),
    f"GET {API}/me/payment-accounts": Rota("Contas de pagamento", ("accounts_list",)),
    f"POST {API}/me/payment-accounts": Rota("Cadastrar conta", nota=CADASTRO),
    f"DELETE {API}/me/payment-accounts/{{account_id}}": Rota("Excluir conta", nota=CADASTRO),
    f"PUT {API}/me/payment-accounts/{{account_id}}": Rota("Editar conta", nota=CADASTRO),
    f"POST {API}/me/payment-accounts/{{account_id}}/adjustment": Rota("Conciliar saldo", ("accounts_adjust_balance",)),
    f"PUT {API}/me/payment-accounts/{{account_id}}/opening-balance": Rota("Saldo inicial", nota=CADASTRO),
    f"GET {API}/me/payment-accounts/{{account_id}}/statement": Rota("Extrato da conta", ("accounts_list", "transactions_search")),
    f"GET {API}/me/push/config": Rota("Push: configuração", nota=INTERFACE),
    f"DELETE {API}/me/push/subscriptions": Rota("Push: cancelar", nota=INTERFACE),
    f"POST {API}/me/push/subscriptions": Rota("Push: assinar", nota=INTERFACE),
    f"GET {API}/me/recurring-income": Rota("Rendas recorrentes", ("recurring_list",)),
    f"POST {API}/me/recurring-income": Rota("Criar renda recorrente", nota="Renda recorrente (salário) é cadastrada uma vez no app; o agente registra rendas avulsas (income_create)."),
    f"POST {API}/me/recurring-income/generate": Rota("Gerar ocorrências de renda", nota="Materialização é do cron horário; leitura do agente nunca escreve."),
    f"DELETE {API}/me/recurring-income/{{recurring_id}}": Rota("Excluir renda recorrente", nota=RARO),
    f"PUT {API}/me/recurring-income/{{recurring_id}}": Rota("Editar renda recorrente", nota="Fica no app (mesmo motivo da criação)."),
    f"GET {API}/me/registration-invites": Rota("Meus convites de cadastro", nota=PESSOAS),
    f"POST {API}/me/registration-invites": Rota("Convidar alguém para o site", nota=PESSOAS),
    f"PATCH {API}/me/report-currency": Rota("Moeda de relatório", nota=INTERFACE),
    f"GET {API}/me/reports": Rota("Relatórios pessoais", ("reports_summary", "budgets_list")),
    f"GET {API}/me/search": Rota("Busca global", ("transactions_search",)),
    f"GET {API}/me/settlements": Rota("Acertos (todas as casas)", ("debts_summary",)),
    f"PUT {API}/me/settlements/{{settlement_id}}/account": Rota("Conta do credor num acerto", nota=RARO),
    f"GET {API}/me/transfers": Rota("Transferências", ("accounts_list",)),
    f"POST {API}/me/transfers": Rota("Transferir entre contas", ("transfers_create",)),
    f"DELETE {API}/me/transfers/{{transfer_id}}": Rota("Excluir transferência", nota=RARO),

    # --- Notificações -------------------------------------------------------------------
    f"GET {API}/notifications": Rota("Notificações", nota=INTERFACE),
    f"POST {API}/notifications/read-all": Rota("Marcar todas como lidas", nota=INTERFACE),
    f"POST {API}/notifications/{{notification_id}}/read": Rota("Marcar como lida", nota=INTERFACE),

    # --- Consentimento OAuth (tela do app) ------------------------------------------------
    f"GET {API}/oauth/consent": Rota("Consentimento: detalhes do pedido", nota=PROPRIA),
    f"POST {API}/oauth/consent/approve": Rota("Consentimento: autorizar", nota=PROPRIA),
    f"POST {API}/oauth/consent/deny": Rota("Consentimento: negar", nota=PROPRIA),
    f"POST {API}/mcp/uploads": Rota(
        "Envio de anexo pelo link do MCP", ("attachments_upload_link",),
        "O destino do link de uso único: sem cookie, autorizado pelo token no cabeçalho.",
    ),

    # --- Espaços --------------------------------------------------------------------------
    f"GET {API}/workspaces/": Rota("Espaços", ("spaces_list",)),
    f"POST {API}/workspaces/": Rota("Criar espaço", nota=ESPACO),
    f"DELETE {W}": Rota("Excluir espaço", nota=ESPACO),
    f"GET {W}": Rota("Detalhe do espaço", ("spaces_list",)),
    f"PUT {W}": Rota("Editar espaço", nota=ESPACO),
    f"GET {W}/base-currency/preview": Rota("Prévia de troca de moeda-base", nota=ESPACO),
    f"GET {W}/audit": Rota("Auditoria do espaço", nota="Trilha é sensível (admin do espaço) e mostra ações de outros membros; o agente vê a própria atividade na tela de Integrações."),

    # --- Planejamento e relatórios ------------------------------------------------------
    f"GET {W}/analytics/estimates": Rota("Metas do mês", ("budgets_list",)),
    f"POST {W}/analytics/estimates": Rota("Definir meta", ("budgets_set",)),
    f"DELETE {W}/analytics/estimates/{{estimate_id}}": Rota("Excluir meta", ("budgets_set",), "Zerar a meta (amount=0) em vez de apagar."),
    f"PUT {W}/analytics/estimates/{{estimate_id}}": Rota("Editar meta", ("budgets_set",)),
    f"GET {W}/analytics/exchange-rate": Rota("Cotação isolada", ("transactions_create",), "A conversão acontece dentro da criação (PTAX + IOF), não como consulta solta."),
    f"GET {W}/analytics/forecast": Rota("Previsão", ("reports_summary", "payables_list")),
    f"GET {W}/analytics/reports": Rota("Relatórios do espaço", ("reports_summary",)),
    f"GET {W}/analytics/summary": Rota("Resumo do espaço", ("reports_summary",)),
    f"GET {W}/categories": Rota("Categorias", ("categories_list",)),
    f"POST {W}/categories": Rota("Criar categoria", ("categories_create",)),
    f"DELETE {W}/categories/{{category_id}}": Rota("Excluir categoria", nota=RARO),
    f"PUT {W}/categories/{{category_id}}": Rota("Editar categoria", nota=RARO),
    f"GET {W}/tags": Rota("Tags", ("categories_list",)),
    f"POST {W}/tags": Rota("Criar tag", nota="Tags são vocabulário da casa, criadas no app; o agente usa as existentes."),
    f"DELETE {W}/tags/{{tag_id}}": Rota("Excluir tag", nota=RARO),
    f"PUT {W}/tags/{{tag_id}}": Rota("Editar tag", nota=RARO),

    # --- Dívidas e acertos ----------------------------------------------------------------
    f"GET {W}/debts": Rota("Quem deve a quem (acumulado)", ("debts_summary",)),
    f"GET {W}/debts/by-month": Rota("Dívidas por mês", ("debts_summary",)),
    f"GET {W}/debts/monthly": Rota("Ledger do mês", ("debts_summary",)),
    f"GET {W}/settlements": Rota("Acertos", ("debts_summary",)),
    f"POST {W}/settlements": Rota("Registrar acerto", ("settlements_create",)),
    f"DELETE {W}/settlements/{{settlement_id}}": Rota("Desfazer acerto", ("settlements_delete",)),

    # --- Contas a pagar ------------------------------------------------------------------
    f"GET {W}/payables": Rota("Contas a pagar do espaço", ("payables_list",)),
    f"POST {W}/payables/settle": Rota("Quitar contas em lote", ("transactions_update",), "Marcar como paga é por lançamento (settled=true)."),

    # --- Recorrências --------------------------------------------------------------------
    f"GET {W}/recurring": Rota("Recorrências", ("recurring_list",)),
    f"POST {W}/recurring": Rota("Criar recorrência", ("recurring_create",)),
    f"POST {W}/recurring/generate": Rota("Gerar ocorrências", nota="Materialização é do cron horário; leitura do agente nunca escreve."),
    f"DELETE {W}/recurring/{{recurring_id}}": Rota("Excluir recorrência", ("recurring_update",), "O agente pausa (active=false); excluir fica no app."),
    f"GET {W}/recurring/{{recurring_id}}": Rota("Detalhe da recorrência", ("recurring_list",)),
    f"PUT {W}/recurring/{{recurring_id}}": Rota("Editar recorrência", ("recurring_update",), "Sem o fluxo de revisão por ocorrência (ADR 0030): usa o escopo none|future|all."),
    f"POST {W}/recurring/{{recurring_id}}/preview": Rota("Prévia da revisão", nota="Revisão ocorrência a ocorrência é interação de tela; o agente usa apply_to."),

    # --- Importação ----------------------------------------------------------------------
    f"POST {W}/imports/parse": Rota("Ler CSV", ("imports_preview",), "O agente extrai as linhas do extrato (PDF, foto, texto); o app confere duplicatas."),
    f"POST {W}/imports/commit": Rota("Importar lote", ("imports_commit",)),

    # --- Lançamentos ---------------------------------------------------------------------
    f"GET {W}/transactions/": Rota("Lançamentos do espaço", ("transactions_search",)),
    f"POST {W}/transactions/": Rota("Criar lançamento", ("transactions_create",)),
    f"POST {W}/transactions/bulk": Rota("Criar em lote", ("imports_commit", "transactions_create"),
                                        "Lote pela importação (com dedup) ou uma criação por despesa (com idempotency_key)."),
    f"POST {W}/transactions/bulk-categorize": Rota("Categorizar em lote", ("transactions_bulk_preview", "transactions_bulk_categorize")),
    f"POST {W}/transactions/preview": Rota("Prévia da divisão", ("transactions_create",), "A saída da criação já traz a divisão calculada."),
    f"DELETE {W}/transactions/{{transaction_id}}": Rota("Excluir lançamento", ("transactions_delete", "transactions_bulk_preview", "transactions_bulk_delete")),
    f"GET {W}/transactions/{{transaction_id}}": Rota("Ver lançamento", ("transactions_get", "transactions_show")),
    f"PUT {W}/transactions/{{transaction_id}}": Rota("Editar lançamento", ("transactions_update",)),
    f"GET {W}/transactions/{{transaction_id}}/attachments": Rota("Anexos do lançamento", ("transactions_get",), "O agente vê só a contagem de anexos. " + ANEXO),
    f"POST {W}/transactions/{{transaction_id}}/attachments": Rota("Enviar anexo", ("attachments_upload_link",), ANEXO_ENVIO),
    f"DELETE {W}/attachments/{{attachment_id}}": Rota("Excluir anexo", nota=ANEXO),
    f"GET {W}/attachments/{{attachment_id}}": Rota("Baixar anexo", nota=ANEXO),
    f"DELETE {W}/transactions/{{transaction_id}}/installment-group": Rota("Excluir compra parcelada", ("transactions_delete",), "scope=purchase"),
    f"GET {W}/transactions/{{transaction_id}}/installment-group": Rota("Compra parcelada inteira", ("transactions_search", "transactions_get")),
    f"PUT {W}/transactions/{{transaction_id}}/installment-group": Rota("Editar compra parcelada", ("transactions_update",), "scope=purchase"),
    f"POST {W}/transactions/{{transaction_id}}/installment-group/cancel": Rota("Cancelar parcelas em aberto", ("transactions_update",), "status=cancelled por parcela"),
    f"POST {W}/transactions/{{transaction_id}}/restore": Rota("Desfazer exclusão", ("transactions_restore",)),
}


@dataclass(frozen=True)
class Ficha:
    """A linha de uma tool no mapa: regra de negócio, peça do app, risco e efeitos."""

    regra: str
    peca: str
    risco: str
    efeito: str
    extras: tuple[str, ...] = field(default_factory=tuple)


# Para o CAPABILITY_MAP.md: o que cada tool REALMENTE toca. Classe, escopo,
# annotations e idempotência saem do próprio `ToolSpec` (fonte única).
FICHAS: dict[str, Ficha] = {
    "profile_get": Ficha("Identidade do token (ADR 0035)", "User.public_id, today_local", "baixo", "nenhum"),
    "spaces_list": Ficha("Membership e papel (ADR 0018)", "WorkspaceMembership", "baixo", "nenhum"),
    "people_list": Ficha("Só quem divide espaço com a pessoa", "space_members", "baixo — nomes de membros", "nenhum"),
    "categories_list": Ficha("Vocabulário do espaço", "Category, Tag", "baixo", "nenhum"),
    "cards_list": Ficha("Cartão pessoal (ADR 0021), fatura derivada (0002)", "CreditCardService", "médio — limite e fatura", "nenhum"),
    "accounts_list": Ficha("Saldo derivado (ADR 0034)", "AccountBalanceService, ProjectionService", "médio — saldos", "nenhum"),
    "transactions_search": Ficha("transaction_scope (ADR 0018), minha parte", "services/transaction_query", "médio — lançamentos", "nenhum"),
    "transactions_get": Ficha("get_visible_transaction", "access_policy", "médio", "nenhum"),
    "statements_get": Ficha("Fatura cumulativa (ADR 0023)", "CreditCardService.statement_population", "médio", "nenhum (não cria fatura)"),
    "reports_summary": Ficha("Consumo = minha parte; caixa ≠ competência", "OverviewService, ReportService", "médio", "nenhum"),
    "transactions_show": Ficha("A mesma leitura de transactions_get, desenhada no componente", "transactions_get", "médio", "nenhum (desenha um componente na conversa)"),
    "statements_show": Ficha("A mesma leitura de statements_get, com a 1ª página de compras", "statements_get", "médio", "nenhum (desenha um componente na conversa)"),
    "reports_show": Ficha("A mesma leitura de reports_summary, de um mês", "reports_summary", "médio", "nenhum (desenha um componente na conversa)"),
    "attachments_upload_link": Ficha(
        "Anexo pelo mesmo comando da tela (tipos, conteúdo real, cota; ADR 0007); link de uso único, 10 min",
        "commands/attachments.add_attachment", "médio — o link de envio aparece na conversa",
        "emite o link; o curl cria 1 anexo",
    ),
    "budgets_list": Ficha("Meta pessoal × da casa", "MonthlyEstimate, ReportService", "baixo", "nenhum"),
    "debts_summary": Ficha("Espaços não se compensam (ADR 0031)", "PersonalDebtService", "médio", "nenhum"),
    "payables_list": Ficha("A pagar = não liquidado (ADR 0029)", "PayablesService, OverviewService", "médio", "nenhum"),
    "income_list": Ficha("Renda pessoal, status derivado", "Income, income_status", "médio", "nenhum"),
    "recurring_list": Ficha("shared_or_mine_scope", "RecurringExpense, RecurringIncome", "baixo", "nenhum"),
    "transactions_bulk_preview": Ficha("Elegibilidade = regras do delete/categorizar", "confirmation.issue", "baixo", "grava só o token de confirmação (hash)"),
    "imports_preview": Ficha("Fingerprint (ADR 0008) + heurística", "commands.imports._mark_duplicates", "baixo", "nenhum"),
    "transactions_create": Ficha("Divisão em centavos (0001), fatura (0002), parcelas, moeda (0006/0015), liquidação (0029)",
                                 "commands.transactions.create_transaction", "alto — cria dívida entre pessoas", "WS + auditoria; cria fatura se preciso"),
    "transactions_update": Ficha("Máquina de estados (0003), trava de paga, vínculo de financiamento", "commands.transactions.update_*",
                                 "alto — reescreve valor/divisão", "WS + auditoria; reroteia fatura"),
    "transactions_delete": Ficha("Soft delete; paga é imutável; anexos exigem prévia", "commands.transactions.delete_*",
                                 "alto", "WS + auditoria; blobs de anexo liberados após o commit"),
    "transactions_restore": Ficha("Mesma permissão do delete", "commands.transactions.restore_transaction", "médio", "WS + auditoria"),
    "transactions_bulk_delete": Ficha("Conjunto exato da prévia, tudo ou nada", "commands.transactions.delete_transaction ×N",
                                      "alto — em massa", "WS + auditoria; blobs após o commit"),
    "transactions_bulk_categorize": Ficha("Só sem categoria (regra do app)", "commands.transactions.bulk_categorize", "médio — em massa", "WS + auditoria"),
    "imports_commit": Ficha("Dedup por fingerprint (ADR 0008), trava do espaço", "commands.imports.commit_import", "alto — em lote", "WS + auditoria"),
    "statements_pay": Ficha("Saldo cumulativo, sem sobrepagamento, UPDATE condicional", "commands.statements.pay_statement",
                            "alto — caixa", "fecha a fatura se o ciclo acabou; auditoria"),
    "transfers_create": Ficha("Moeda da conta = moeda do movimento (0034)", "commands.accounts.create_transfer", "alto — caixa", "auditoria"),
    "accounts_adjust_balance": Ficha("Ajuste datado, não reescreve o passado (0034)", "commands.accounts.adjust_balance", "alto — caixa", "auditoria"),
    "income_create": Ficha("Conversão na data do recebimento", "commands.income.create_income", "médio", "auditoria"),
    "income_update": Ficha("Competência ≠ caixa; cancelada ocupa a vaga", "commands.income.*", "médio", "auditoria"),
    "settlements_create": Ficha("Direção e teto da dívida (0009/0031), trava do espaço", "commands.settlements.create_settlement",
                                "alto — dívida entre pessoas", "WS + auditoria"),
    "settlements_delete": Ficha("Só o autor (ou admin)", "commands.settlements.delete_settlement", "alto", "WS + auditoria"),
    "recurring_create": Ficha("Snapshot da divisão (0012), cartão coerente (0032)", "commands.recurring.create_recurring", "médio",
                              "materializa ocorrências conforme `materialize`; WS"),
    "recurring_update": Ficha("Pagas congeladas; escopo das não pagas (0012)", "commands.recurring.update_recurring", "médio", "reescreve ocorrências não pagas; WS"),
    "budgets_set": Ficha("Upsert por (espaço, dono, categoria, mês)", "commands.planning.create_estimate", "baixo", "WS"),
    "categories_create": Ficha("Nome único por espaço; excluída é reativada", "commands.planning.create_category", "baixo", "WS"),
}
