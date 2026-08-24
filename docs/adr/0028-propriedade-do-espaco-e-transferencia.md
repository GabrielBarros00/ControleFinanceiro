# ADR 0028 — O dono do espaço é a membership `owner`; a propriedade se transfere

**Status:** aceito (2026-08-18)
**Relacionado:** [0018](0018-privacidade-papel-e-acesso-financeiro.md) (papel × acesso financeiro),
[0026](0026-papel-de-plataforma-e-cadastro-por-convite.md) (`platform_role` opera o site e não toca o workspace),
[0020](0020-visao-global-e-quatro-numeros.md) (workspace na URL)

## Contexto

Havia **duas respostas diferentes** para "de quem é este espaço", e nada as
mantinha sincronizadas:

- `Workspace.created_by_user_id` — a coluna que `GET /workspaces/` usava para
  preencher `owner_user_id`/`owner_name`, ou seja, a que a interface mostraria;
- `WorkspaceMembership.role == owner` — a que **autoriza**: excluir o espaço
  (`require_role(WorkspaceRole.owner)`), ser imune a rebaixamento e a remoção.

Elas coincidiam por construção no instante da criação e por mais nenhum motivo.
Não divergiam na prática só porque **não havia como mover a propriedade**: a API
recusa promover a `owner` (400), recusa alterar o papel de quem já é (403),
recusa removê-lo (403) e recusa que ele saia (400). A propriedade era um estado
terminal.

O custo disso apareceu do lado do administrador de plataforma. `PATCH
/admin/users/{id}` com `is_active=false` e `DELETE /admin/users/{id}` não
consultavam workspace nenhum — `admin.py` sequer importava `Workspace`.
Desativar o dono produzia um espaço **permanentemente indelével**: a única conta
que poderia apagá-lo não consegue mais autenticar (`auth.py` recusa conta
inativa), ninguém pode herdar o papel, e os dados continuam vivos para os demais
membros sem que exista uma pessoa responsável por eles.

Somava-se a isso um `member_count` que contava toda linha de
`WorkspaceMembership`, inclusive de conta desativada ou soft-deletada. O número
que a interface usa para dizer "3 pessoas" contava fantasmas.

## Decisão

### 1. A fonte do dono é a membership, não quem criou

`owner_user_id`/`owner_name` passam a ser derivados da membership com
`role == owner`. É a **mesma fonte que autoriza**, então o rótulo na tela não
pode mais divergir de quem de fato manda no espaço.

`Workspace.created_by_user_id` permanece — mas com o significado estreito de
**registro histórico de quem criou**. Não é lido para autorizar nem para exibir,
e a transferência de propriedade não o reescreve: quem criou continua tendo
criado.

### 2. `member_count` conta apenas membros ativos

A contagem filtra `User.is_active` e `User.deleted_at`. O campo existe para
responder "quantas pessoas estão nisto comigo", e conta desativada não é uma
delas.

O **dono** é exceção deliberada na exibição: se ele estiver inativo, o nome
continua saindo em `owner_name` (a pergunta "de quem é" tem resposta mesmo
assim), mas ele não entra na contagem.

### 3. A propriedade se transfere, num ato só e auditado

```
POST /workspaces/{workspace_id}/members/{user_id}/transfer-ownership
     require_role(WorkspaceRole.owner)
```

Numa transação: o alvo vira `owner` com `financial_access=full_workspace`, e o
antigo dono vira `admin` — não perde o espaço, perde o poder terminal sobre ele.
O alvo precisa ser membro **ativo e não excluído**; transferir para uma conta
inativa recriaria exatamente o problema que esta rota existe para resolver.

Publica `member.updated`, que já está em `FULL_RESYNC_TYPES` no cliente: mudar
quem manda muda o que o servidor devolve em consulta, e resincronizar por
inteiro é a resposta certa. Grava `AuditLog` com antes/depois dos dois papéis —
é a mudança de poder mais consequente que existe dentro de um espaço.

### 4. O administrador de plataforma não pode criar um espaço órfão

`PATCH /admin/users/{id}` com `is_active=false` e `DELETE /admin/users/{id}`
respondem **409** quando o alvo é dono de algum espaço vivo, listando os nomes e
apontando a transferência como saída.

É o mesmo formato da trava que já impede desativar a própria conta
(`admin.py`): recusar com o caminho escrito na mensagem, em vez de executar e
deixar o sistema num estado sem volta. E vale nos **dois** pontos de entrada —
um portão com um só ponto de chamada guardado é um portão aberto.

Isto **não** dá ao administrador de plataforma qualquer visão financeira sobre o
espaço, e não move a propriedade em nome de ninguém: ele fica sabendo que existe
um bloqueio e quem precisa agir. O ADR 0026 continua valendo por inteiro —
`platform_role` opera o site, não as casas.

## Consequências

- Um espaço nunca fica sem dono capaz de agir. O caminho "a pessoa saiu"
  passa a ter resposta: transfere e depois desativa.
- `member_count` pode **diminuir** sem que ninguém saia, quando um membro é
  desativado pelo administrador. É o comportamento correto, mas é uma mudança
  visível de número.
- O antigo dono vira `admin`, não é expulso. Sair do espaço continua exigindo
  que ele não seja mais o dono — só que agora existe como fazê-lo.
- Fica de fora: **múltiplos donos** por espaço. A regra "um dono, e o papel não
  se promove" continua; a transferência move o papel, não o duplica. Se um dia
  fizer falta, é outro ADR.
- Fica de fora: transferência **automática** ao desativar. Escolher herdeiro em
  nome de outra pessoa é decisão de negócio disfarçada de rotina de manutenção;
  o 409 devolve a escolha a quem é dela.
