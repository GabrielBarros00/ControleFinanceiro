import { AlertTriangle } from 'lucide-react';
import { formatMoney } from '@/lib/money';
import type { ExcludedWorkspace } from '@/hooks/use-my-settlements';

interface Props {
  workspaces: ExcludedWorkspace[];
  /** Moeda de relatório da pessoa — o destino que não foi possível alcançar. */
  currency: string;
}

/**
 * Espaços que ficaram FORA dos totais por falta de cotação — nomeadas, e com o
 * valor na moeda delas.
 *
 * Par do `ExcludedForeignNotice`, que devolve só uma contagem porque é o que o
 * `/analytics/*` sabe dizer. Aqui a contagem não bastava: a pergunta da tela é
 * "quanto eu devo", e responder "1 espaço ficou de fora" a quem deve USD 90 é
 * quase tão ruim quanto o `R$ 0,00` que a regra do ADR 0006 já proíbe. O grupo
 * daquele espaço continua na tela com os valores certos; o que este aviso explica
 * é por que ele não entrou na soma do topo.
 */
export function ExcludedWorkspacesNotice({ workspaces, currency }: Props) {
  if (!workspaces.length) return null;
  const plural = workspaces.length > 1;
  return (
    <div
      role="status"
      className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning-subtle px-3 py-2 text-xs text-warning"
    >
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <div className="space-y-1">
        <p>
          {plural ? 'Estes espaços ficaram' : 'Este espaço ficou'} fora dos totais em{' '}
          <strong>{currency}</strong> — não há cotação para a moeda{plural ? 's' : ''}{' '}
          {plural ? 'deles' : 'dele'}. {plural ? 'Entram' : 'Entra'} assim que houver.
        </p>
        <ul className="space-y-0.5">
          {workspaces.map((w) => {
            const pagar = Number(w.to_pay);
            const receber = Number(w.to_receive);
            return (
              <li key={w.workspace_id} className="font-semibold">
                {w.workspace_name}:{' '}
                {pagar > 0 && (
                  <span>a pagar {formatMoney(w.to_pay, { currency: w.base_currency })}</span>
                )}
                {pagar > 0 && receber > 0 && ' · '}
                {receber > 0 && (
                  <span>a receber {formatMoney(w.to_receive, { currency: w.base_currency })}</span>
                )}
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
