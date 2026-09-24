/** @jsxImportSource preact */
/**
 * Operações em massa: a prévia (o que vai mudar, com o token de confirmação) e o
 * resultado (com Desfazer, quando a ação tem volta).
 *
 * O clique em "Confirmar" é a confirmação humana do fluxo em duas etapas: o token
 * só vale para o conjunto mostrado, e o servidor recusa se algo mudou no meio.
 */
import { useState } from 'preact/hooks';
import type { Bridge } from '../bridge';
import { money, plural, shortDay } from '../format';
import type { Meta, Ref, Resumo } from '../tipos';
import { useAcao } from '../ui/acao';
import { Aviso, Button, Header, Linha, Money } from '../ui/base';
import { IconCheck, IconTag, IconTrash, IconUndo } from '../ui/icons';

const EXECUTA: Record<string, string> = { delete: 'transactions_bulk_delete', categorize: 'transactions_bulk_categorize' };

function tituloDaAcao(acao: string, categoria?: Ref | null, tag?: Ref | null): string {
  switch (acao) {
    case 'delete': return 'Excluir';
    case 'categorize': return `Categorizar como ${categoria?.name ?? '—'}`;
    case 'recategorize': return `Mudar a categoria para ${categoria?.name ?? '—'}`;
    case 'tag': return `Adicionar #${tag?.name ?? '—'}`;
    case 'untag': return `Tirar #${tag?.name ?? '—'}`;
    case 'settle': return 'Marcar como pago';
    default: return acao;
  }
}

function feitoDaMassa(acao: string, n: number): string {
  switch (acao) {
    case 'delete': return `${plural(n, 'lançamento excluído', 'lançamentos excluídos')}.`;
    case 'categorize': case 'recategorize': return `${plural(n, 'lançamento categorizado', 'lançamentos categorizados')}.`;
    case 'tag': return `Tag adicionada em ${plural(n, 'lançamento', 'lançamentos')}.`;
    case 'untag': return `Tag retirada de ${plural(n, 'lançamento', 'lançamentos')}.`;
    case 'settle': return `${plural(n, 'lançamento marcado', 'lançamentos marcados')} como pago.`;
    default: return `${plural(n, 'lançamento alterado', 'lançamentos alterados')}.`;
  }
}

/** Depois de executar: quantos, e Desfazer quando é exclusão (restaura um a um). */
export function ResultadoDeMassa({ dados, meta, bridge }: { dados: Record<string, unknown>; meta: Meta; bridge: Bridge }) {
  const acao = String(dados.action ?? '');
  const n = Number(dados.count ?? 0);
  const [desfeitos, setDesfeitos] = useState(0);
  const [feito, setFeito] = useState(false);
  const exec = useAcao(bridge);
  const alvos = meta.undo_each ?? [];

  async function desfazer() {
    let ok = 0;
    for (const args of alvos) {
      const r = await exec.executar('transactions_restore', args);
      if (!r) break;
      ok += 1;
      setDesfeitos(ok);
    }
    if (ok) void bridge.updateModelContext?.(`O usuário restaurou pelo componente ${ok} dos ${alvos.length} lançamentos excluídos em massa.`);
    if (ok === alvos.length) setFeito(true);
  }

  return (
    <div class="space-y-3">
      <Header icone={acao === 'delete' ? <IconTrash size={18} /> : <IconCheck size={18} />} tom={acao === 'delete' ? 'perigo' : 'ok'}
        titulo={feitoDaMassa(acao, n)}
        subtitulo={[
          Number(dados.skipped ?? 0) > 0 && `${plural(Number(dados.skipped), 'ficou', 'ficaram')} de fora`,
          Number(dados.attachments_removed ?? 0) > 0 && plural(Number(dados.attachments_removed), 'anexo apagado', 'anexos apagados'),
          dados.replayed === true && 'já tinha sido feito',
        ].filter(Boolean).join(' · ') || undefined} />
      {feito && <Aviso>Desfeito: {plural(desfeitos, 'lançamento voltou', 'lançamentos voltaram')}.</Aviso>}
      {!feito && desfeitos > 0 && <Aviso tom="info">{desfeitos} de {alvos.length} restaurados.</Aviso>}
      {exec.erro && <Aviso tom="erro">{exec.erro.mensagem}</Aviso>}
      {alvos.length > 0 && !feito && Number(dados.attachments_removed ?? 0) === 0 && (
        <Button icone={<IconUndo size={14} />} carregando={exec.estado === 'enviando'} onClick={() => void desfazer()}>
          {alvos.length > 1 ? `Desfazer (restaurar ${alvos.length})` : 'Desfazer'}
        </Button>
      )}
    </div>
  );
}

/** A prévia: o que entra, o que fica de fora e por quê, e o botão que confirma. */
export function PreviaDeMassa({ dados, meta, bridge, aoConcluir }: {
  dados: Record<string, unknown>; meta: Meta; bridge: Bridge; aoConcluir?: (resultado: Record<string, unknown>) => void;
}) {
  const acao = String(dados.action ?? '');
  const token = dados.confirmation_token as string | null;
  const totais = (dados.totals as Array<{ currency: string; amount: string }> | undefined) ?? [];
  const amostra = (dados.sample as Resumo[] | undefined) ?? [];
  const fora = (dados.ineligible as Array<{ id: number; title: string; reason: string }> | undefined) ?? [];
  const anexos = Number(dados.attachments ?? 0);
  const n = Number(dados.count ?? 0);
  const excluir = acao === 'delete';
  const exec = useAcao(bridge);
  const [resultado, setResultado] = useState<Record<string, unknown> | null>(null);

  async function confirmar() {
    if (!token) return;
    const r = await exec.executar(EXECUTA[acao] ?? 'transactions_bulk_update', { confirmation_token: token },
      `O usuário confirmou no componente: ${tituloDaAcao(acao, dados.category as Ref, dados.tag as Ref).toLowerCase()} em ${n} lançamentos.`);
    if (!r) return;
    if (aoConcluir) aoConcluir(r);
    else setResultado(r);
  }

  if (resultado) {
    const ids = (resultado.transaction_ids as number[] | undefined) ?? [];
    return <ResultadoDeMassa dados={resultado} bridge={bridge}
      meta={{ ...meta, undo_each: resultado.action === 'delete' ? ids.map((i) => ({ transaction_id: i })) : [] }} />;
  }

  return (
    <div class="space-y-3">
      <Header icone={excluir ? <IconTrash size={18} /> : <IconTag size={18} />} tom={excluir ? 'perigo' : 'destaque'}
        titulo={`${tituloDaAcao(acao, dados.category as Ref, dados.tag as Ref)} · ${plural(n, 'lançamento', 'lançamentos')}`}
        subtitulo={<span class="num">{totais.map((t) => money(t.amount, t.currency)).join(' + ') || 'nada'}</span>} />
      {anexos > 0 && <Aviso tom="erro">{plural(anexos, 'anexo será apagado', 'anexos serão apagados')} para sempre: isso não tem Desfazer.</Aviso>}
      {amostra.length > 0 && (
        <ul>
          {amostra.map((b) => (
            <Linha key={b.id} titulo={b.title} detalhe={[shortDay(b.date), b.space?.name].filter(Boolean).join(' · ')}
              direita={<Money valor={b.amount} moeda={b.currency} />} />
          ))}
          {n > amostra.length && <li class="list-none pt-1 text-[12px] text-muted-fg">e mais {n - amostra.length}</li>}
        </ul>
      )}
      {fora.length > 0 && (
        <details class="text-[12px] text-muted-fg">
          <summary class="cursor-pointer">{plural(Number(dados.ineligible_count ?? fora.length), 'ficou de fora', 'ficaram de fora')}</summary>
          <ul class="mt-1 space-y-0.5">{fora.map((f) => <li key={f.id}>{f.title}: {f.reason}</li>)}</ul>
        </details>
      )}
      {exec.erro && <Aviso tom="erro">{exec.erro.mensagem}</Aviso>}
      {token && n > 0 && (
        <Button variante={excluir ? 'danger' : 'primary'} class="w-full" carregando={exec.estado === 'enviando'} onClick={() => void confirmar()}>
          {excluir ? `Confirmar exclusão de ${n}` : `Confirmar (${n})`}
        </Button>
      )}
    </div>
  );
}
