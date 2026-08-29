import { PageHeader } from '@/components/layout/PageHeader';
import { PeriodPicker } from '@/components/layout/PeriodPicker';
import { PayablesList } from '@/components/payables/PayablesList';
import { useWorkspacePayables } from '@/hooks/use-payables';
import { useMonthParam } from '@/hooks/use-month-param';

/**
 * Contas a pagar DESTE espaço (ADR 0029).
 *
 * Par de `/me/payables`, e a pergunta é outra: lá é "o que EU tenho a pagar,
 * somando minhas casas"; aqui é "o que esta casa tem em aberto". As duas saem do
 * mesmo serviço, então não têm como discordar sobre o que conta como pendência.
 *
 * O recorte segue o acesso financeiro (ADR 0018): um membro `involved_only` vê o
 * que o envolve, não a casa inteira.
 */
export function WorkspacePayablesPage() {
  const [month, setMonth] = useMonthParam();
  const { payables, isLoading, isError, refetch } = useWorkspacePayables(month);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Contas a pagar"
        subtitle="Contas deste espaço que ainda não foram pagas."
        scope="workspace"
        period={<PeriodPicker value={month} onChange={setMonth} />}
      />
      <PayablesList
        payables={payables}
        isLoading={isLoading}
        isError={isError}
        onRetry={() => refetch()}
        // O total daqui é a conta CHEIA de cada despesa, somando os pagadores
        // dela (ver `_por_lancamento`) — não o que sai do meu bolso. As duas
        // telas mostravam o mesmo rótulo sobre números de donos diferentes.
        escopo="espaco"
      />
    </div>
  );
}
