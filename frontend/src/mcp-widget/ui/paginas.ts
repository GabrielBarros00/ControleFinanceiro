/**
 * Páginas de uma lista: a primeira veio no resultado, as próximas pelo
 * `next_cursor`, chamando a MESMA tool de dados — sem desenhar outro componente.
 */
import { useState } from 'preact/hooks';
import type { Bridge } from '../bridge';
import { erroDe } from './acao';

export interface Consulta { tool: string; args: Record<string, unknown> }

export function usePaginas<T>(bridge: Bridge, consulta: Consulta | undefined, iniciais: T[], cursor: string | null | undefined, chave: string) {
  const [itens, setItens] = useState<T[]>(iniciais);
  const [proximo, setProximo] = useState<string | null>(cursor ?? null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function mais() {
    if (!consulta || !proximo) return;
    setCarregando(true);
    setErro(null);
    try {
      const r = await bridge.callTool(consulta.tool, { ...consulta.args, cursor: proximo });
      if (r.isError) throw new Error(erroDe(r).mensagem);
      const d = (r.structuredContent ?? {}) as Record<string, unknown>;
      setItens((atuais) => [...atuais, ...((d[chave] as T[] | undefined) ?? [])]);
      setProximo((d.next_cursor as string | null | undefined) ?? null);
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Não foi possível carregar.');
    } finally {
      setCarregando(false);
    }
  }

  function trocar(novos: T[], novoCursor?: string | null) {
    setItens(novos);
    setProximo(novoCursor ?? null);
  }

  return { itens, temMais: Boolean(consulta && proximo), carregando, erro, mais, trocar };
}
