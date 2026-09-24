"""O palpite de classificação de uma linha de extrato de conta (ADR 0037).

É só um PALPITE: a tela mostra a sugestão e a pessoa confirma ou troca antes de
importar. Por isso as regras são poucas e conservadoras — errar para "despesa" ou
"renda" (o que cada sinal já diz) é melhor que inventar uma transferência.

- Saiu e o título fala de pagamento de fatura → pagamento de fatura. O cartão é o
  que aparece no título; sem nome, o único cartão da pessoa; senão, fica para ela.
- O título fala de transferência entre contas (transferência, TED, aplicação,
  resgate, "mesma titularidade") E cita outra conta DA PESSOA pelo nome →
  transferência com ela. Só o nome não basta: "PIX ENVIADO FULANO NUBANK" é
  pagamento a alguém que usa o Nubank, não à conta Nubank da pessoa.
- Senão: saiu é despesa, entrou é renda.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

_FATURA = re.compile(r"\b(pagamento|pagto|pgto|pag)\b.*\bfatura\b|\bfatura\b.*\b(pagamento|pagto|pgto|paga)\b")
_ENTRE_CONTAS = re.compile(r"\btransf|\bted\b|\bdoc\b|\baplicacao\b|\bresgate\b|mesma titularidade|entre contas")
#: Palavras que aparecem em nome de conta ou cartão e não identificam nada.
_GENERICAS = {"conta", "cartao", "credito", "debito", "corrente", "banco", "card", "gold", "black", "platinum"}


def _normaliza(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", sem_acento.lower())).strip()


def _palavras_do_nome(nome: str) -> set[str]:
    return {p for p in _normaliza(nome).split() if len(p) >= 3 and p not in _GENERICAS}


def _cita(titulo: str, nome: str) -> bool:
    palavras = set(titulo.split())
    return bool(_palavras_do_nome(nome) & palavras)


@dataclass(frozen=True)
class Sugestao:
    classification: str
    card_id: Optional[int] = None
    counterpart_account_id: Optional[int] = None


def sugerir(
    titulo: str,
    direcao: str,
    outras_contas: Iterable[Tuple[int, str]],
    cartoes: Iterable[Tuple[int, str]],
) -> Sugestao:
    """`outras_contas`: as contas da pessoa, SEM a do extrato; `cartoes`: os dela."""
    t = _normaliza(titulo)
    cartoes = list(cartoes)
    if direcao == "out" and _FATURA.search(t):
        citados = [cid for cid, nome in cartoes if _cita(t, nome)]
        if len(citados) == 1:
            return Sugestao("statement_payment", card_id=citados[0])
        return Sugestao("statement_payment", card_id=cartoes[0][0] if len(cartoes) == 1 else None)
    contas = [cid for cid, nome in outras_contas if _cita(t, nome)] if _ENTRE_CONTAS.search(t) else []
    if len(contas) == 1:
        return Sugestao("transfer", counterpart_account_id=contas[0])
    return Sugestao("expense" if direcao == "out" else "income")
