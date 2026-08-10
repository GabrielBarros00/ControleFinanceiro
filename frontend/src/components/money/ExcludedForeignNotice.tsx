import { AlertTriangle } from 'lucide-react';

interface ExcludedForeignNoticeProps {
  /** `excluded_foreign_count` devolvido por /analytics/summary e /analytics/forecast */
  count?: number | null;
  baseCurrency: string;
}

/**
 * Aviso de lançamentos fora da moeda-base.
 *
 * O backend calcula `excluded_foreign_count` em `report_service` e
 * `forecast_service` — duas queries por requisição — justamente para o usuário
 * "saber que sumiram de propósito". Nenhuma tela lia o campo: os totais
 * excluíam lançamentos em silêncio e a explicação nunca chegava.
 */
export function ExcludedForeignNotice({ count, baseCurrency }: ExcludedForeignNoticeProps) {
  if (!count) return null;
  const plural = count > 1;
  return (
    // Tokens do tema (`text-warning` sobre `bg-warning-subtle`) no lugar do par
    // amber cru: aquele dava 2,9:1 no tema claro e reprovava o AA do WCAG. E o
    // token vale para todo aviso do app de uma vez, em vez de cada componente
    // escolher o seu amarelo — que era como dez lugares acabaram com contrastes
    // diferentes, todos abaixo do mínimo.
    <div
      role="status"
      className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning-subtle px-3 py-2 text-xs text-warning"
    >
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      {/* A frase dizia que os valores "somem de novo quando houver cotação" —
          o oposto do que acontece. Eles estão fora AGORA; a cotação é o que os
          traz de volta para dentro do total. */}
      <span>
        {count} lançamento{plural ? 's' : ''} em moeda diferente de{' '}
        <strong>{baseCurrency}</strong> {plural ? 'ficaram' : 'ficou'} fora destes
        totais — {plural ? 'entram' : 'entra'} assim que houver cotação para a data.
      </span>
    </div>
  );
}
