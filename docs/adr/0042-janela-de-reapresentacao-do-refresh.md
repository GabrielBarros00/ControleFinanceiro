# ADR 0042 — Reapresentar o refresh logo depois da rotação devolve a sessão vigente; fora da janela, continua sendo roubo

**Status:** aceito (2026-09-29)
**Relacionado:** [0013](0013-sessoes-de-refresh-e-hardening-de-producao.md) (sessões de
refresh com rotação e detecção de reuso)

## Contexto

O ADR 0013 trata **qualquer** reapresentação de um refresh token já girado como
roubo: a família inteira é revogada, e o ladrão e a vítima caem juntos.

Na prática, quem mais reapresentava um token girado era a própria pessoa:

- **Duas renovações com o mesmo cookie.** Na volta do aparelho, o WebSocket
  reconectava com 4401 e chamava `/auth/refresh` por conta própria, ao mesmo tempo
  em que as consultas da tela, com 401, faziam o mesmo pelo interceptor. Com duas
  abas (ou a janela do app instalado e uma aba do navegador), cada uma renovava por
  si. Medido contra o backend: duas renovações com o mesmo cookie, com 0 a 200 ms
  entre elas, terminavam **sempre** em `[200, 401]` e na família revogada, com a
  renovação seguinte do token vencedor também em 401.
- **A resposta que se perde.** O servidor gira e faz commit, a resposta não chega (a
  rede do celular trocou, a requisição estourou o prazo do cliente), e o navegador
  fica com o cookie velho. A próxima renovação é um "reuso".

Nos dois casos a pessoa era deslogada sem ter feito nada, às vezes meia hora depois
(o access token do vencedor ainda valia), e voltava ao app na tela de login.

O frontend passou a fazer uma renovação por vez, na aba e entre abas
(`renovarSessao` em `frontend/src/api/client.ts`, com Web Locks). Isso fecha as
corridas do mesmo navegador rodando o código novo — mas não a resposta perdida, nem
a aba que ainda roda o JS de antes do deploy.

## Decisão

**Um refresh girado há menos de `JANELA_DE_REAPRESENTACAO` (30 s), cuja sucessora
ainda está viva, devolve a sucessora** — um access token novo e um refresh com o
**mesmo `jti`** da sucessora, sem girar de novo. Nada é revogado.

- **Mesmo `jti`, e não um novo:** quem chegou atrasado e quem já tinha a sucessora
  ficam na mesma cadeia. A próxima renovação de qualquer um dos dois segue a rotação
  normal, sem ramificar a família.
- **A sucessora tem de estar viva e ter nascido da rotação** (criada depois da
  revogação do token apresentado). É isso que separa a rotação das outras
  revogações: o logout e a troca/redefinição de senha revogam sem criar sucessora,
  então o token de uma sessão encerrada cai no reuso de sempre — inclusive dentro
  da janela.
- **Fora da janela, nada muda:** reapresentar revoga a família inteira, como no
  ADR 0013.

## Consequências

- O que se perde: um token roubado e usado **nos 30 s seguintes** a uma rotação
  legítima não é detectado naquele instante — ele recebe a mesma sessão da vítima.
  Para continuar dentro, o ladrão teria de renovar sempre a menos de 30 s de cada
  renovação da vítima; a primeira reapresentação fora da janela derruba os dois.
  É a mesma troca que provedores de identidade fazem com a "reuse interval"/"grace
  period" de refresh token, pelo mesmo motivo.
- `rotate_session` (`app/services/session_service.py`) ganha o ramo da janela; a
  rota `/auth/refresh` não muda. Sem migração: a decisão usa `revoked_at` e
  `created_at`, que já existiam.
- Testes: `tests/api/test_session_security.py` cobre a janela (mesmo `jti`, nada
  revogado), o logout dentro dela (401) e o reuso depois dela (família revogada).
