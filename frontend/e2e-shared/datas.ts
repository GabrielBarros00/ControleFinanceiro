/**
 * Dia CIVIL local em `YYYY-MM-DD`.
 *
 * `new Date().toISOString().slice(0, 10)` é a armadilha: `toISOString()` é UTC,
 * e às 21h em UTC-3 ele já devolve o dia SEGUINTE. Um teste que escreve "hoje"
 * num campo de data e depois confere "hoje" passa de manhã e falha à noite —
 * foi exatamente o que aconteceu com três testes desta sessão, dois deles
 * escritos na mesma hora em que o relógio virou.
 *
 * O app inteiro já distingue instante de dia civil (`todayLocalISO`,
 * `parseApiDay`); as suítes precisavam da mesma distinção.
 */
export function diaLocal(offsetEmDias = 0): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetEmDias);
  const mes = String(d.getMonth() + 1).padStart(2, '0');
  const dia = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${mes}-${dia}`;
}
