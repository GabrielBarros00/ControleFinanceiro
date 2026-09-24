/** @jsxImportSource preact */
/** Antes → depois e o botão Desfazer, para os resultados de escrita. */
import { useState } from 'preact/hooks';
import type { Bridge } from '../bridge';
import type { Desfazer } from '../tipos';
import { useAcao } from './acao';
import { Aviso, Button } from './base';
import { IconArrowRight, IconUndo } from './icons';

/** Antes → depois de campos simples (texto já formatado). */
export function Mudancas({ linhas }: { linhas: Array<[string, string, string]> }) {
  if (!linhas.length) return null;
  return (
    <ul class="space-y-1.5 rounded-lg bg-subtle p-2.5">
      {linhas.map(([rotulo, antes, depois]) => (
        <li key={rotulo} class="grid grid-cols-[minmax(0,7rem)_1fr] items-baseline gap-2 text-[13px]">
          <span class="truncate text-muted-fg">{rotulo}</span>
          <span class="flex min-w-0 flex-wrap items-center gap-1.5">
            <span class="num text-muted-fg line-through">{antes}</span>
            <IconArrowRight size={12} class="shrink-0 text-muted-fg" />
            <span class="num font-medium">{depois}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

/** O botão Desfazer do `_meta.undo`, para os recibos das escritas desta tela. */
export function BotaoDesfazer({ undo, bridge, feito }: { undo?: Desfazer; bridge: Bridge; feito: string }) {
  const exec = useAcao(bridge);
  const [ok, setOk] = useState(false);
  if (!undo) return null;
  if (ok) return <Aviso>{feito}</Aviso>;
  return (
    <>
      {exec.erro && <Aviso tom="erro">{exec.erro.mensagem}</Aviso>}
      <Button icone={<IconUndo size={14} />} carregando={exec.estado === 'enviando'}
        onClick={async () => { if (await exec.executar(undo.tool, undo.args, `O usuário desfez pelo componente (${undo.tool}).`)) setOk(true); }}>
        {undo.label ?? 'Desfazer'}
      </Button>
    </>
  );
}
