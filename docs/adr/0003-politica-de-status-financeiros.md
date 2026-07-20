# Política de status financeiros e imutabilidade de despesa paga

Sem uma política central, dívidas/relatórios/previsão somavam qualquer status. Decidimos:

| Status | Realizado (dívidas/relatórios) | Previsão | Editável |
|---|---|---|---|
| draft | não | não | sim |
| pending | não | sim | sim |
| confirmed | sim | sim | sim |
| paid | sim | sim | somente após reabrir |
| cancelled | não | não | não |

Transições válidas: draft→pending→confirmed→paid, qualquer→cancelled, paid→confirmed (reabertura auditada). Cada transição grava seu timestamp (`confirmed_at`/`paid_at`/`cancelled_at`) e toda edição atualiza `updated_at`. Despesa paga é imutável até ser reaberta.
