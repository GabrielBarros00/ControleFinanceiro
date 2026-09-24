/** @jsxImportSource preact */
/**
 * Listas: paginação pelo `next_cursor` e a linha de lançamento que expande.
 *
 * "Carregar mais" chama a MESMA tool de dados, com o cursor que ela devolveu; a
 * lista cresce ali mesmo, sem desenhar outro componente na conversa. Expandir uma
 * linha busca o lançamento inteiro (`transactions_get`) só quando a pessoa pede.
 */
import { useState } from 'preact/hooks';
import type { Bridge } from '../bridge';
import { money } from '../format';
import type { Formulario, Lancamento, Resumo } from '../tipos';
import { LancamentoView } from '../views/Lancamento';
import { erroDe } from './acao';
import { Aviso, Badge, Button, Dia, Esqueleto, Linha, Money } from './base';

export function CarregarMais({ pagina, total, mostrados }: {
  pagina: { temMais: boolean; carregando: boolean; erro: string | null; mais: () => Promise<void> }; total?: number; mostrados: number;
}) {
  return (
    <>
      {pagina.erro && <Aviso tom="erro">{pagina.erro}</Aviso>}
      {pagina.temMais && (
        <div class="flex items-center justify-between gap-2 pt-2">
          <span class="text-[12px] text-muted-fg">{total ? `${mostrados} de ${total}` : `${mostrados} mostrados`}</span>
          <Button variante="ghost" carregando={pagina.carregando} onClick={() => void pagina.mais()}>Carregar mais</Button>
        </div>
      )}
    </>
  );
}

/** Um lançamento resumido que abre o detalhe (e o editor) na própria lista. */
export function LinhaDeLancamento({ r, bridge, forms, selecionavel, marcado, aoMarcar, semCartao }: {
  r: Resumo; bridge: Bridge; forms?: Record<string, Formulario>; semCartao?: boolean;
  selecionavel?: boolean; marcado?: boolean; aoMarcar?: (id: number, sim: boolean) => void;
}) {
  const [aberta, setAberta] = useState(false);
  const [detalhe, setDetalhe] = useState<{ dados: Record<string, unknown> } | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const dividido = r.my_share !== r.amount;

  async function abrir() {
    setAberta(!aberta);
    if (detalhe || aberta) return;
    const res = await bridge.callTool('transactions_get', { transaction_id: r.id }).catch(() => null);
    if (!res || res.isError) {
      setErro(res ? erroDe(res).mensagem : 'Não foi possível abrir.');
      return;
    }
    setDetalhe({ dados: (res.structuredContent ?? {}) as Record<string, unknown> });
  }

  const form = r.space ? forms?.[String(r.space.id)] : undefined;
  const tx = detalhe?.dados.transaction as Lancamento | undefined;
  return (
    <li class="list-none">
      <div class="flex items-center gap-1">
        {selecionavel && (
          <input type="checkbox" class="size-4 shrink-0 accent-accent" checked={marcado} aria-label={`Selecionar ${r.title}`}
            onChange={(e) => aoMarcar?.(r.id, (e.target as HTMLInputElement).checked)} />
        )}
        <ul class="min-w-0 flex-1">
          <Linha
            esquerda={<Dia data={r.date} />}
            titulo={r.title}
            riscada={r.status === 'cancelled'}
            detalhe={[r.category ?? 'Sem categoria', !semCartao && r.card, r.installment && `parcela ${r.installment}`, r.space?.name].filter(Boolean).join(' · ')}
            direita={
              <>
                <Money valor={r.statement_amount ?? r.amount} moeda={r.currency} class="text-[14px] font-medium" />
                {dividido && <span class="block text-[11px] text-muted-fg">sua parte {money(r.my_share, r.currency)}</span>}
                {!r.card && !r.settled && r.status !== 'cancelled' && <span class="block"><Badge tom="aviso">a pagar</Badge></span>}
              </>
            }
            onClick={() => void abrir()} expandida={aberta}
          >
            {erro ? <Aviso tom="erro">{erro}</Aviso>
              : !detalhe ? <Esqueleto linhas={2} />
              : tx ? (
                <LancamentoView dados={detalhe.dados} bridge={bridge} embutido
                  meta={{ view: 'transaction', mode: 'read', can_edit: Boolean(form), form, app_url: tx.app_url }} />
              ) : null}
          </Linha>
        </ul>
      </div>
    </li>
  );
}
