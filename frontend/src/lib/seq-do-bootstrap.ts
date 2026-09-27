/*
 * O `event_seq` de cada espaço no instante do bootstrap (auditoria 2026-09-26, P2).
 *
 * ## O problema
 *
 * No primeiro `hello` do WebSocket de um espaço, o cliente não sabe se o cache
 * está em dia: uma mutação commitada entre o GET da página e a entrada do socket
 * na sala está contada no `hello.seq` mas não nos dados, e não gera lacuna
 * depois. O remédio antigo era refazer TODAS as consultas em toda carga de página
 * — medido: 14 requisições, e as mesmas 14 de novo meio segundo depois.
 *
 * ## Por que este número resolve
 *
 * O `GET /workspaces/` do bootstrap roda ANTES de qualquer consulta da página: a
 * `ProtectedRoute` só desenha a tela quando a `auth-me` resolve, e a `auth-me`
 * aguarda esta lista (`buscarSessao`). Então o seq lido ali é um LIMITE INFERIOR
 * do que a página viu. No primeiro `hello`:
 *
 * - `hello.seq === seq do bootstrap` → nenhuma mutação entre a lista e agora; o
 *   cache está correlacionado e o resync é desnecessário;
 * - qualquer outro valor (maior: houve mutação; menor: o servidor voltou atrás)
 *   → resync completo, como antes.
 *
 * ## As duas regras que mantêm o número honesto
 *
 * 1. **A primeira leitura vence.** Um seq lido DEPOIS de consultas já feitas não
 *    é limite inferior delas — por isso uma leitura posterior nunca substitui a
 *    anterior.
 * 2. **Só a carga que libera a página registra** (`registrar` = a `auth-me` ainda
 *    sem dado). Se o `/workspaces/` do bootstrap falhar e um refetch posterior
 *    conseguir, o número dele chegaria tarde demais — sem registro, o primeiro
 *    `hello` cai no resync completo, que é o caminho seguro.
 */

const seqs = new Map<number, number>();

export function registrarSeqDoBootstrap(espacos: { id: number; event_seq?: number | null }[]): void {
  for (const { id, event_seq } of espacos) {
    if (typeof event_seq === 'number' && !seqs.has(id)) seqs.set(id, event_seq);
  }
}

export function seqDoBootstrap(workspaceId: number): number | undefined {
  return seqs.get(workspaceId);
}

/** No logout: o próximo usuário registra os dele. */
export function esquecerSeqsDoBootstrap(): void {
  seqs.clear();
}
