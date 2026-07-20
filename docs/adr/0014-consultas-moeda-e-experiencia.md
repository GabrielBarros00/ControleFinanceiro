# Consultas financeiras, moeda-base por workspace e experiência

Fechamento da Onda 5: os números tinham float e meses de 30 dias, a moeda-base era fixa em BRL no código, a auditoria não era consultável por workspace, e o frontend não tratava erros nem eventos de acerto/anexo.

## Decisões

**Moeda-base por workspace (ADR 0006).** `Workspace.base_currency` substitui a constante fixa. `workspace_base_currency(session, ws_id)` é a fonte única usada por dívidas, relatórios, forecast e faturas — a MESMA moeda em todas as agregações. Transações em outra moeda seguem fora dos totais até existir **taxa histórica congelada** (deliberadamente adiada: subsistema à parte; recusar mistura já protege as somas).

**Relatórios íntegros (REL-001).** Sem `float()` (perdia centavos) — tudo em `Decimal`. Histórico de 6 meses por **mês de calendário** (`add_months`), não `days=30`. A distribuição por categoria ganha a fatia **"Sem categoria" = total − categorizado**, então transação sem item ou item sem categoria não some mais do gráfico.

**Forecast com renda (INC-001).** A projeção passa a devolver a renda do mês e a sobra projetada (renda − gasto projetado). Corrige também o dedup da frequência **diária** (deduplica por data, como a semanal).

**Orçamento por categoria (BUD-001).** `MonthlyEstimate.category_id` (FK) é a referência real; o campo `category` (texto) fica como rótulo legado. Estimativa excluída já ficava fora do forecast.

**Auditoria por workspace (AUD-001).** `AuditLog.workspace_id` é preenchido pelos listeners a partir do alvo; `GET /workspaces/{id}/audit` consulta a trilha (admin/owner).

**Tags reativáveis (TAG-001).** Criar com nome de tag excluída **reativa** a antiga — o nome não fica bloqueado para sempre (mesmo padrão de `PaymentAccount`).

**Frontend.** `keysForEvent` central ganha `settlement`/`attachment`/`payment_account` (RT-001). Reports e Débitos têm **estado de erro explícito** (ERR-001) — falha não vira "tudo zero". `useWorkspaceRole` esconde/desabilita ações que o backend recusaria (RBAC-FE-001); o servidor continua sendo a autoridade. Rotas pesadas já usam `React.lazy` (ReportsPage é um chunk à parte).

## Consequências

- Migração `b8e3f105c7a9`: `workspace.base_currency`, `auditlog.workspace_id`, `monthlyestimate.category_id`.
- Adiado: taxa de câmbio histórica congelada por transação.
