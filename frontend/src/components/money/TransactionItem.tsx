import * as React from 'react';
import { Loader2, Pencil, Trash2 } from 'lucide-react';
import type { TransactionRead } from '@/types/transaction';
import { useAcaoPendente } from '@/hooks/use-acao-pendente';
import { MoneyText } from './MoneyText';
import { CategoryGlyph, type CategoryLike } from './CategoryGlyph';
import { paymentMethodLabel } from '@/lib/payment-methods';
import { StatusPill, settlementPill, txStatusPill } from '@/components/ui/status-pill';
import { formatCurrency } from '@/lib/money';
import { cn } from '@/lib/utils';
import { Avatar } from '@/components/ui/avatar';

/*
 * TransactionItem — linha do extrato (docs/frontend-redesign/05 §3, 06 §2).
 * Glifo de categoria + título + meta (categoria · pagamento · parcela · divisão)
 * + valor com cor/sinal corretos. Ações acessíveis por foco e visíveis no mobile.
 */
interface TransactionItemProps {
  tx: TransactionRead;
  category?: CategoryLike | null;
  memberName?: (userId: number) => string;
  /** Token de cache da foto de cada membro — sem ele, os avatares empilhados
   *  continuam mostrando a inicial. */
  memberAvatar?: (userId: number) => string | null | undefined;
  canWrite?: boolean;
  // `unknown` e não `void`: quem exclui devolve uma promessa, e um retorno
  // tipado como `void` faz o TypeScript ACEITAR a promessa e o chamador
  // descartá-la sem aviso — foi assim que a trava de duplo clique não chegava
  // até aqui.
  onEdit?: (tx: TransactionRead) => unknown;
  onDelete?: (id: number) => unknown;
  /** Clicar na linha abre o detalhe/preview do lançamento. */
  onSelect?: (tx: TransactionRead) => void;
}

export function TransactionItem({
  tx,
  category,
  memberName,
  memberAvatar,
  // Fail-CLOSED: o default era `true`, então qualquer ledger renderizado sem a
  // prop mostrava editar/excluir habilitados para um viewer (era o caso do
  // Início). Esquecer de passar agora desabilita — o erro seguro.
  canWrite = false,
  onEdit,
  onDelete,
  onSelect,
}: TransactionItemProps) {
  // Por LINHA, e não por lista: excluir uma transação não pode congelar o botão
  // das outras. `stopPropagation` primeiro — a linha inteira abre o detalhe no
  // clique, e sem isso excluir abriria o detalhe do que acabou de sumir.
  const { disparar: excluir, pendente: excluindo } = useAcaoPendente(
    (evento: React.MouseEvent) => {
      evento.stopPropagation();
      return onDelete?.(tx.id);
    },
  );

  const amount = parseFloat(tx.total_amount);
  const kind = amount < 0 ? 'income' : 'expense';
  const splits = tx.splits ?? [];
  const isSplit = splits.length > 1;

  // Pendente/paga/cancelada precisam se explicar na linha: a recorrência do fim
  // do mês nasce `pending` e fica FORA dos totais — sem a pílula o extrato
  // pareceria não bater com o saldo do topo.
  const status = txStatusPill(tx.status);
  // Eixo do CAIXA, ao lado do de competência (ADR 0029): a conta pode estar
  // confirmada e dividida e ainda não ter sido paga. Sem a pílula, ela some do
  // "Saiu" do mês sem nada na linha que explique por quê.
  const liquidacao = settlementPill(tx.settled_at, tx.credit_card_id);

  const meta: string[] = [];
  if (category?.name) meta.push(category.name);
  // O travessão é o "não informado" do `paymentMethodLabel`, e sozinho ele não
  // informa nada: numa lista de lançamentos sem forma de pagamento preenchida,
  // eram oito linhas seguidas exibindo um "—" solitário debaixo do título. Só
  // entra quando acompanha alguma coisa.
  const formaDePagamento = paymentMethodLabel(tx.payment_method, tx.credit_card_id);
  if (formaDePagamento !== '—' || meta.length > 0) meta.push(formaDePagamento);
  if (tx.installments_of && tx.installments_of > 1) {
    meta.push(`${tx.installment_no}/${tx.installments_of}`);
  }
  // Lançamento estrangeiro: mostra o valor original ao lado do total em BRL
  if (tx.original_currency && tx.original_amount) {
    meta.push(formatCurrency(parseFloat(tx.original_amount), tx.original_currency));
  }

  return (
    /*
      A LINHA não é mais um botão; o título é.

      Antes, a linha inteira era `role="button" tabIndex={0}` com os botões de
      editar e excluir dentro dela — controles interativos aninhados, que o axe
      reprova (`nested-interactive`, 15 nós nesta tela) e que um leitor de tela
      anuncia como um botão só chamado "Faxina Pendente A pagar −R$ 220,00",
      sem deixar claro o que há dentro.

      O padrão aqui é o "stretched link", que o próprio projeto já usa no quadro
      de Caixa da `OverviewPage` (e documenta lá): quem é acionável é um controle
      de verdade — o título —, e ele ESTENDE a própria área de clique sobre a
      linha com `after:absolute after:inset-0`. Os botões de ação sobem para
      `relative z-10` e continuam clicáveis por cima dessa área.

      Ganho de lambuja: o nome acessível do controle passa a ser o título da
      despesa, e não a linha inteira lida em voz alta.
    */
    <div
      // Âncora estável para o E2E: o extrato deixou de ser <table> no redesign,
      // então não há mais role="row" para localizar a linha
      data-testid="ledger-row"
      className={cn(
        'group relative flex items-center gap-3 rounded-lg px-2 py-2.5 transition-colors hover:bg-muted',
        onSelect && 'cursor-pointer focus-within:bg-muted',
      )}
    >
      <CategoryGlyph category={category} />

      {/*
        Título SOZINHO na primeira linha; pílulas e meta descem para a segunda.
        Esta é a correção do pior defeito que a auditoria de UX encontrou.

        Antes, título e pílulas dividiam a mesma linha. O título tem `truncate`
        (ou seja, `overflow: hidden`), e isso ZERA a largura mínima automática de
        um item flex — ele podia ceder até desaparecer. As pílulas não cediam.
        Resultado medido no extrato: a 390px, **14 de 15 títulos com 0px de
        largura**; a 360px, o maior tinha 61px. A tela mais usada do produto, no
        aparelho para o qual ele virou PWA, não dizia que despesa era cada linha
        — e havia um botão de excluir ao lado de cada uma.

        Nada disso estourava a página, então o portão de rolagem horizontal a
        360px passava folgado. Quem mede agora é `e2e/larguras.spec.ts`.

        Uma linha só para os dois tamanhos, de propósito: manter o layout antigo
        no desktop significaria dois caminhos para a mesma linha, e o desktop
        também melhora com o título ocupando a largura toda.
      */}
      <div className="min-w-0 flex-1">
        {onSelect ? (
          <button
            type="button"
            onClick={() => onSelect(tx)}
            className="block w-full truncate rounded-sm text-left text-sm font-medium text-foreground after:absolute after:inset-0 after:rounded-lg after:content-[''] focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
          >
            {tx.title}
          </button>
        ) : (
          <p className="truncate text-sm font-medium text-foreground">{tx.title}</p>
        )}
        {/* `flex-wrap`: numa tela estreita as duas pílulas mais a meta não cabem
            em 200px, e sem quebra voltaríamos a espremer alguém. */}
        {(meta.length > 0 || status || liquidacao) && (
          <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
            {meta.length > 0 && (
              <p className="min-w-0 truncate text-xs text-muted-foreground">{meta.join(' · ')}</p>
            )}
            {status && <StatusPill tone={status.tone}>{status.label}</StatusPill>}
            {liquidacao && <StatusPill tone={liquidacao.tone}>{liquidacao.label}</StatusPill>}
          </div>
        )}
      </div>

      {isSplit && memberName && (
        <div className="hidden items-center -space-x-1.5 sm:flex" aria-hidden>
          {splits.slice(0, 3).map((s) => (
            <Avatar
              key={s.id}
              name={memberName(s.user_id)}
              userId={s.user_id}
              version={memberAvatar?.(s.user_id)}
              size="xs"
              title={memberName(s.user_id)}
              className="border border-card"
            />
          ))}
          {splits.length > 3 && (
            <span className="flex h-6 w-6 items-center justify-center rounded-full border border-card bg-muted text-[10px] font-semibold text-muted-foreground">
              +{splits.length - 3}
            </span>
          )}
        </div>
      )}

      <MoneyText value={amount} kind={kind} currency={tx.currency} className="shrink-0 font-semibold" />

      {(onEdit || onDelete) && (
        // `relative z-10`: a área de clique estendida do título cobre a linha
        // inteira (ver o comentário no topo), e sem subir no empilhamento estes
        // botões ficariam POR BAIXO dela — clicar em excluir abriria o detalhe.
        <div
          className={cn(
            'relative z-10 flex shrink-0 items-center gap-0.5 transition-opacity',
            'sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100',
          )}
        >
          {onEdit && (
            <button
              type="button"
              aria-label="Editar transação"
              disabled={!canWrite}
              onClick={(e) => { e.stopPropagation(); onEdit(tx); }}
              // 40×40 no celular (era 28×28 com `p-1.5`): editar e excluir são
              // as ações mais tocadas do extrato, ficam coladas uma na outra e
              // ao lado do valor. No desktop, onde só aparecem no hover e o
              // ponteiro é preciso, seguem compactas.
              className="flex h-10 w-10 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-brand-subtle hover:text-brand disabled:pointer-events-none disabled:opacity-40 sm:h-7 sm:w-7"
            >
              <Pencil className="h-4 w-4" />
            </button>
          )}
          {onDelete && (
            <button
              type="button"
              aria-label="Excluir transação"
              disabled={!canWrite || excluindo}
              aria-busy={excluindo || undefined}
              onClick={excluir}
              className="flex h-10 w-10 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive disabled:pointer-events-none disabled:opacity-40 sm:h-7 sm:w-7"
            >
              {excluindo ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
