/**
 * Formatação da área de administração (ADR 0026).
 *
 * Em arquivo próprio porque o `AdminPage.tsx` só pode exportar componentes — a
 * regra `react-refresh/only-export-components` existe para o fast refresh não
 * perder o estado da tela ao editar. E, de todo modo, funções puras testáveis
 * sem montar nada pertencem mesmo aqui.
 */

/** Tamanho em bytes, legível. `null` vira "—", nunca "0 B". */
export function bytes(valor: number | null | undefined): string {
  // `null` é "o motor não sabe responder" (o `pg_database_size` de um banco que
  // não é Postgres, por exemplo). Mostrar "0 B" seria dar uma resposta — e uma
  // resposta errada, que faria parecer que o banco está vazio.
  if (valor == null) return '—';
  if (valor < 1024) return `${valor} B`;
  const unidades = ['KB', 'MB', 'GB', 'TB'];
  let n = valor / 1024;
  let i = 0;
  while (n >= 1024 && i < unidades.length - 1) {
    n /= 1024;
    i += 1;
  }
  return `${n.toFixed(n < 10 ? 1 : 0)} ${unidades[i]}`;
}

/** Instante (com hora) no fuso do navegador. */
export function data(iso: string | null | undefined): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
}

/** Dia de CALENDÁRIO — não passa pelo `Date`.
 *
 * A data da cotação de câmbio é um dia civil, sem hora. `new Date('2026-08-10')`
 * é meia-noite UTC e, em qualquer fuso negativo, é exibida como 09/08: a
 * armadilha que o `parseApiDay` resolve no resto do aplicativo. Aqui a string já
 * vem no formato certo, então recortá-la é mais simples e mais seguro do que
 * construir um `Date` para desconstruí-lo em seguida.
 */
export function dia(iso: string | null | undefined): string {
  if (!iso) return '—';
  const [ano, mes, d] = iso.slice(0, 10).split('-');
  return `${d}/${mes}/${ano}`;
}
