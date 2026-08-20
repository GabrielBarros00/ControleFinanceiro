import { PageHeader } from '@/components/layout/PageHeader';
import { PeriodPicker } from '@/components/layout/PeriodPicker';
import { PayablesList } from '@/components/payables/PayablesList';
import { useMyPayables } from '@/hooks/use-payables';
import { useMonthParam } from '@/hooks/use-month-param';

/**
 * Contas a pagar da PESSOA (ADR 0029).
 *
 * O que ainda não saiu do caixa, somando todos os espaços dela: boleto, Pix,
 * dinheiro, transferência — o que se marca como pago. Fatura de cartão e parcela
 * de financiamento **não** entram: são outro prazo e têm botão próprio em
 * Compromissos, e repeti-las aqui pediria o mesmo dinheiro duas vezes.
 *
 * É o complemento exato do "Saiu" do Seu mês: aquele soma o que já saiu, este
 * lista o que ainda vai sair. Os dois nascem da mesma consulta, com o filtro de
 * `settled_at` invertido.
 */
export function PayablesPage() {
  const [month, setMonth] = useMonthParam();
  const { payables, isLoading, isError, refetch } = useMyPayables(month);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Contas a pagar"
        subtitle="O que ainda não saiu do seu caixa, em todos os seus espaços."
        period={<PeriodPicker value={month} onChange={setMonth} />}
      />
      <PayablesList
        payables={payables}
        isLoading={isLoading}
        isError={isError}
        onRetry={() => refetch()}
        // A camada pessoal mistura casas: sem o nome do espaço na linha, duas
        // contas de "Aluguel" ficariam indistinguíveis.
        showWorkspace
      />
    </div>
  );
}
