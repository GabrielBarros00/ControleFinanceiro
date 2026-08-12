"""Serialização de operações cujo teto é uma SOMA sobre várias linhas.

Existe porque a mesma forma de defeito apareceu em quatro lugares diferentes: um
`SELECT` que agrega (dívida líquida, bytes usados, fingerprints já importados,
superadmins restantes), um `if` que decide, e um `INSERT` que executa — com nada
segurando o intervalo entre a leitura e a escrita. Sequencialmente todos estavam
certos; sob concorrência, N requisições liam o mesmo estado e passavam todas.

**Por que um `UPDATE` que não muda nada.** É o mesmo mecanismo do
`CreditCardService.pay_statement`, e a escolha é deliberada:

- `SELECT ... FOR UPDATE` seria mais direto e é o que a leitura sugere, mas o
  dialeto SQLite o ignora **em silêncio** — a proteção sumiria em dev e no leg
  SQLite do CI, sobrando só no Postgres. Um mecanismo de segurança que só existe
  num dos ambientes é pior do que um explícito.
- `INSERT ... SELECT` com a validação no `WHERE` não serve: sob snapshot
  isolation a subconsulta não enxerga a escrita não commitada da concorrente.
- Um `UPDATE` condicional sobre a própria linha alvo resolve CONTADOR (o `WHERE`
  vira o teto), mas não uma invariante que depende de várias linhas — a condição
  seria avaliada contra o snapshot commitado, onde o outro registro ainda conta.

Via Core de propósito: não passa pelos mapper events, então não gera `AuditLog`
espúrio — o mesmo cuidado que o `publish_event` já tomava.

**O preço, assumido.** A trava é da linha do workspace e vale até o commit (ADR
0010: um commit por request). Duas escritas simultâneas no MESMO workspace
passam a se enfileirar; em workspaces diferentes, nada muda. Para um app de
família — onde acerto, importação e upload são operações manuais e raras — isso
é invisível, e é o preço de o teto ser verdadeiro.
"""
from datetime import datetime, UTC

from sqlalchemy import update
from sqlmodel import Session

from app.models.user import User
from app.models.workspace import Workspace


def trava_workspace(session: Session, workspace_id: int) -> None:
    """Serializa as escritas deste workspace até o fim da transação.

    Chame ANTES de ler o agregado que vai decidir — a trava só vale se for a
    PRIMEIRA escrita da operação. Depois da leitura já não adianta: a
    concorrente leu o mesmo estado antes de qualquer uma das duas escrever.
    """
    session.execute(
        update(Workspace)
        .where(Workspace.id == workspace_id)
        .values(updated_at=datetime.now(UTC))
    )


def trava_usuario(session: Session, user_id: int) -> None:
    """Serializa as operações contadas POR PESSOA (a cota de convites).

    Mesmo mecanismo e mesma regra do `trava_workspace`: antes da leitura que
    decide. A linha é a do próprio autor porque o teto é dele — dois autores
    diferentes não têm por que esperar um ao outro.
    """
    session.execute(
        update(User).where(User.id == user_id).values(updated_at=datetime.now(UTC))
    )
