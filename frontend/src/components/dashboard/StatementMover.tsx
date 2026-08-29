import * as React from 'react';
import { CalendarClock, Loader2 } from 'lucide-react';
import { useStatementTarget } from '@/hooks/use-credit-cards';
import { apiDateToInput, parseApiDay } from '@/lib/date';
import { nativeSelectClass } from '@/components/ui/native-select';
import type { TransactionRead } from '@/types/transaction';

/**
 * "Em qual fatura esta compra entrou?" — a correção DEPOIS de lançada.
 *
 * Esta é a metade que resolve o problema de verdade. No formulário, marcar que a
 * compra vai escorregar é palpite: ninguém sabe, na hora de passar o cartão, se
 * o estabelecimento vai demorar a capturar. Aqui a dúvida já virou fato — a
 * fatura real chegou e não bateu com a da tela —, e por isso é aqui que a
 * escolha tem informação para ser feita.
 *
 * A tela escolhe um MÊS e devolve ao backend o `shift` que veio junto da opção.
 * Nenhuma aritmética de ciclo acontece aqui: ela é do servidor (ADR 0002), e uma
 * segunda implementação no cliente divergiria da primeira na primeira mudança.
 * O `statement_id` continua sendo impossível de mandar — que é o que impedia
 * apontar para a fatura de outro cartão ou de outra pessoa.
 */
export function StatementMover({
  transaction,
  canWrite,
  onMove,
}: {
  transaction: TransactionRead;
  canWrite: boolean;
  onMove: (shift: number) => Promise<unknown>;
}) {
  const shift = transaction.statement_shift ?? 0;
  const dia = apiDateToInput(transaction.transaction_date);
  const { target } = useStatementTarget(transaction.credit_card_id ?? null, dia, shift);
  const [salvando, setSalvando] = React.useState(false);
  const [erro, setErro] = React.useState<string | null>(null);

  if (!transaction.credit_card_id || !target) return null;

  const parcelada = (transaction.installments_of ?? 0) > 1;

  const escolher = async (valor: string) => {
    setErro(null);
    setSalvando(true);
    try {
      await onMove(Number(valor));
    } catch {
      // A mensagem específica (fatura fechada → 409) vem do host via toast; aqui
      // basta não deixar o select parecendo que salvou.
      setErro('Não foi possível mover. A fatura de destino pode estar fechada.');
    } finally {
      setSalvando(false);
    }
  };

  return (
    // `min-w-0`: o `DialogContent` é um GRID, e item de grid nasce com
    // `min-width: auto` — recusa-se a encolher abaixo do próprio conteúdo. As
    // opções deste `<select>` são longas ("Setembro de 2026 — vence 07/10 (pela
    // data da compra)"), e o `min-w-0` de `nativeSelectClass` não basta: quem
    // precisa poder encolher é o ITEM DE GRID, que é esta div.
    //
    // Quem realmente estourava este diálogo era o `DialogHeader` (ver o
    // comentário em `TransactionDetailDialog`), mas isto aqui é a mesma
    // armadilha um nível abaixo, e sem ele o bloco voltaria a estourar assim
    // que a fatura ganhasse um rótulo mais comprido.
    <div className="min-w-0 rounded-lg border border-border bg-accent/30 p-3 text-xs">
      <div className="mb-2 flex items-center gap-1.5 font-semibold text-foreground">
        <CalendarClock className="h-3.5 w-3.5" />
        Fatura
        {salvando && <Loader2 className="h-3 w-3 animate-spin" />}
      </div>
      <label className="block space-y-1.5">
        <span className="text-muted-foreground">
          A fatura real é composta pela data em que o banco PROCESSA a compra —
          perto do fechamento ela pode ter entrado noutro ciclo.
        </span>
        <select
          aria-label="Fatura desta compra"
          className={nativeSelectClass}
          value={String(shift)}
          disabled={!canWrite || salvando}
          onChange={(e) => escolher(e.target.value)}
        >
          {target.options.map((o) => (
            <option
              key={o.shift}
              value={o.shift}
              // Fatura fechada/paga não aceita lançamento novo (ADR 0011). A
              // opção aparece mesmo assim, com o motivo no rótulo: escondê-la
              // deixaria a tela sem explicação para a fatura que a pessoa
              // procura e não acha — e é o caso frequente, porque a divergência
              // costuma ser descoberta com o ciclo já fechado.
              disabled={!o.available && o.shift !== shift}
              className="bg-card"
            >
              {rotuloDaOpcao(o.month, o.due_date, o.shift)}
              {!o.available && (o.status === 'paid' ? ' — paga' : ' — fechada')}
            </option>
          ))}
        </select>
      </label>
      {parcelada && (
        <p className="mt-2 text-muted-foreground">
          Compra parcelada: mover desloca o cronograma inteiro, cada parcela no
          ciclo dela.
        </p>
      )}
      <p className="mt-2 text-muted-foreground">
        A despesa continua sendo de{' '}
        <span className="font-medium text-foreground">
          {mesLongo(transaction.billing_month ?? dia.slice(0, 7))}
        </span>
        : muda a fatura, não o mês do gasto.
      </p>
      {erro && (
        <p role="alert" className="mt-2 font-medium text-destructive">{erro}</p>
      )}
    </div>
  );
}

function rotuloDaOpcao(month: string, dueDate: string, shift: number): string {
  // parseApiDay: `due_date` é um DIA de calendário serializado como datetime à
  // meia-noite — `parseApiDate` o atrasaria em um dia em fuso negativo.
  const vence = parseApiDay(dueDate).toLocaleDateString('pt-BR', {
    day: '2-digit',
    month: '2-digit',
  });
  const sufixo = shift === 0 ? ' (pela data da compra)' : '';
  return `${mesLongo(month)} — vence ${vence}${sufixo}`;
}

function mesLongo(month: string): string {
  const [y, m] = month.split('-').map(Number);
  if (!y || !m) return month;
  const rotulo = new Date(y, m - 1, 1).toLocaleDateString('pt-BR', {
    month: 'long',
    year: 'numeric',
  });
  return rotulo.charAt(0).toUpperCase() + rotulo.slice(1);
}
