/**
 * Ações pelo componente: chamar uma tool, mostrar "salvando…", traduzir o erro e
 * contar ao modelo o que a pessoa fez.
 *
 * O servidor decide tudo (permissão, versão, trava de paga): o componente só
 * chama a MESMA tool que o assistente chamaria e mostra a resposta. Depois de uma
 * ação que deu certo, `updateModelContext` conta ao modelo o que mudou — sem isso
 * ele continuaria falando do estado de antes da edição.
 */
import { useState } from 'preact/hooks';
import type { Bridge, ToolResultLike } from '../bridge';

export interface ErroDeTool {
  mensagem: string;
  codigo?: string;
  detalhes?: Record<string, unknown>;
}

/** O envelope `{error:{code,message,details}}` que vai no texto do resultado com erro. */
export function erroDe(r: ToolResultLike): ErroDeTool {
  const texto = r.content?.find((c) => c.type === 'text')?.text ?? '';
  const [primeira, ...resto] = texto.split('\n');
  try {
    const corpo = JSON.parse(resto.join('\n').trim()) as { error?: { code?: string; message?: string; details?: Record<string, unknown> } };
    return { mensagem: corpo.error?.message ?? primeira, codigo: corpo.error?.code, detalhes: corpo.error?.details };
  } catch {
    return { mensagem: primeira || 'A operação foi recusada.' };
  }
}

export type Estado = 'parado' | 'enviando' | 'feito' | 'erro';

export function useAcao(bridge: Bridge) {
  const [estado, setEstado] = useState<Estado>('parado');
  const [erro, setErro] = useState<ErroDeTool | null>(null);

  async function executar(
    tool: string, args: Record<string, unknown>, contexto?: string,
  ): Promise<Record<string, unknown> | null> {
    setEstado('enviando');
    setErro(null);
    try {
      const r = await bridge.callTool(tool, args);
      if (r.isError) {
        setErro(erroDe(r));
        setEstado('erro');
        return null;
      }
      setEstado('feito');
      if (contexto) void bridge.updateModelContext?.(contexto);
      return (r.structuredContent ?? {}) as Record<string, unknown>;
    } catch (e) {
      setErro({ mensagem: e instanceof Error ? e.message : 'Não foi possível concluir.' });
      setEstado('erro');
      return null;
    }
  }

  return { estado, erro, executar, limpar: () => { setEstado('parado'); setErro(null); } };
}

/** Uma chave de idempotência nova por clique (retry do host não duplica). */
export function novaChave(): string {
  const c = globalThis.crypto as Crypto | undefined;
  if (c?.randomUUID) return c.randomUUID();
  return `w-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
