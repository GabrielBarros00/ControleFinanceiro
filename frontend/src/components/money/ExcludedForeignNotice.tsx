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
    <div
      role="status"
      className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-600 dark:text-amber-400"
    >
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span>
        {count} lançamento{plural ? 's' : ''} em moeda diferente de{' '}
        <strong>{baseCurrency}</strong> {plural ? 'ficaram' : 'ficou'} fora destes
        totais — some{plural ? 'm' : ''} de novo quando houver cotação para a data.
      </span>
    </div>
  );
}
