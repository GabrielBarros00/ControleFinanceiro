import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import type { AxiosAdapter } from 'axios';
import { delay, http, HttpResponse } from 'msw';
import { server } from '@/test/setup';
import {
  apiClient,
  PRAZO_DE_ARQUIVO_MS,
  PRAZO_PADRAO_MS,
  registerQueryClient,
  renovarSessao,
} from '@/api/client';
import { ehFalhaDeInfraestrutura } from '@/hooks/use-auth';
import { useAuthStore } from '@/stores';

const API = 'http://localhost:8000/api/v1';

/*
 * O cliente HTTP na volta do aparelho.
 *
 * O relato: "passo um tempo sem entrar, volto, e a tela fica preta, como se
 * tentasse carregar — só com F5". Reproduzido no build de produção: a primeira
 * leva de requisições saía por uma conexão morta e, sem prazo, o `/auth/me` da
 * carga nunca terminava. Na mesma investigação apareceram mais dois defeitos da
 * renovação de sessão, cobertos aqui também.
 */

/** Adaptador que devolve a configuração FINAL — depois dos interceptores. */
const ecoaConfig: AxiosAdapter = async (config) => ({
  data: config, status: 200, statusText: 'OK', headers: {}, config,
});

describe('prazo das requisições', () => {
  it('toda requisição sai com prazo', () => {
    expect(apiClient.defaults.timeout).toBe(PRAZO_PADRAO_MS);
  });

  it('envio e download de arquivo ganham prazo maior', async () => {
    const form = new FormData();
    form.append('file', new Blob(['x']), 'nota.jpg');
    const envio = await apiClient.post('/eco', form, { adapter: ecoaConfig });
    expect(envio.data.timeout).toBe(PRAZO_DE_ARQUIVO_MS);

    const download = await apiClient.get('/eco', { adapter: ecoaConfig, responseType: 'blob' });
    expect(download.data.timeout).toBe(PRAZO_DE_ARQUIVO_MS);

    const comum = await apiClient.get('/eco', { adapter: ecoaConfig });
    expect(comum.data.timeout).toBe(PRAZO_PADRAO_MS);
  });

  it('a requisição que nunca responde vira falha de rede — e a tela sabe o que fazer com ela', async () => {
    server.use(http.get(`${API}/pendurada`, async () => {
      await delay('infinite');
      return HttpResponse.json({});
    }));

    // Adaptador `fetch`: o XHR que o MSW simula no jsdom ignora `timeout` (no
    // navegador ele é nativo — conferido no Chromium, no build de produção).
    const erro = await apiClient
      .get('/pendurada', { timeout: 50, adapter: 'fetch' })
      .catch((e: unknown) => e);

    expect(erro).toMatchObject({ code: expect.stringMatching(/ECONNABORTED|ETIMEDOUT/) });
    expect(erro).not.toHaveProperty('response.status');
    // É o que liga o `retry` da sessão e a tela "Sem conexão com o servidor",
    // em vez do "Carregando sua sessão…" eterno.
    expect(ehFalhaDeInfraestrutura(erro)).toBe(true);
  });
});

describe('renovação da sessão', () => {
  let queryClient: QueryClient;
  let renovacoes: number;

  beforeEach(() => {
    queryClient = new QueryClient();
    registerQueryClient(queryClient);
    renovacoes = 0;
    useAuthStore.getState().setUser({ id: 1, name: 'Ana', email: 'ana@example.com' });
    queryClient.setQueryData(['auth-me'], { id: 1, name: 'Ana', email: 'ana@example.com' });
    queryClient.setQueryData(['transactions', 1], { items: [{ id: 7 }] });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    useAuthStore.getState().logout();
  });

  /** Rota que responde 401 até a sessão ser renovada. */
  const expiraAteRenovar = (respostaDaRenovacao: () => Response | Promise<Response>) => {
    let renovada = false;
    server.use(
      http.get(`${API}/protegida`, () =>
        renovada ? HttpResponse.json({ ok: true }) : new HttpResponse(null, { status: 401 })),
      http.post(`${API}/auth/refresh`, async () => {
        renovacoes += 1;
        const resposta = await respostaDaRenovacao();
        if (resposta.status === 200) renovada = true;
        return resposta;
      }),
    );
  };

  it('uma renovação só para as consultas E para o WebSocket que venceram juntos', async () => {
    /*
     * O backend lê a segunda renovação com o mesmo cookie como roubo e revoga
     * a sessão (ADR 0013). Na volta do aparelho, o 4401 do WebSocket chamava
     * `/auth/refresh` por conta própria, junto com as consultas da tela.
     */
    expiraAteRenovar(async () => {
      await delay(30);
      return HttpResponse.json({ message: 'ok' });
    });

    const resultados = await Promise.all([
      apiClient.get('/protegida'),
      apiClient.get('/protegida'),
      renovarSessao(), // o caminho do WebSocket
      apiClient.get('/protegida'),
    ]);

    expect(renovacoes).toBe(1);
    expect(resultados[0].data).toEqual({ ok: true });
  });

  it('entre abas, a renovação passa pela trava do navegador', async () => {
    const request = vi.fn((_nome: string, tarefa: () => Promise<unknown>) => tarefa());
    vi.stubGlobal('navigator', { ...navigator, locks: { request } });
    expiraAteRenovar(() => HttpResponse.json({ message: 'ok' }));

    await apiClient.get('/protegida');

    expect(request).toHaveBeenCalledTimes(1);
    expect(request.mock.calls[0][0]).toBe('cf-renovar-sessao');
    expect(renovacoes).toBe(1);
  });

  it('falha de rede na renovação NÃO desloga: devolve a falha, e a sessão e o cache ficam', async () => {
    /*
     * Reproduzido com um 502 na renovação (o túnel durante um deploy, a rede do
     * celular voltando): a pessoa, com sessão válida, caía em "Bem-vindo, entre
     * com suas credenciais".
     */
    expiraAteRenovar(() => new HttpResponse('<h1>502 Bad Gateway</h1>', { status: 502 }));

    const erro = await apiClient.get('/protegida').catch((e: unknown) => e);

    // A consulta vê a falha de infraestrutura (e tenta de novo), não um 401
    expect(erro).toMatchObject({ response: { status: 502 } });
    expect(ehFalhaDeInfraestrutura(erro)).toBe(true);
    expect(useAuthStore.getState().isAuthenticated).toBe(true);
    expect(queryClient.getQueryData(['auth-me'])).toMatchObject({ id: 1 });
    expect(queryClient.getQueryData(['transactions', 1])).toEqual({ items: [{ id: 7 }] });
  });

  it('renovação recusada encerra a sessão: auth-me nula e o cache do usuário descartado', async () => {
    expiraAteRenovar(() => new HttpResponse(null, { status: 401 }));

    const erro = await apiClient.get('/protegida').catch((e: unknown) => e);

    expect(erro).toMatchObject({ response: { status: 401 } });
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
    expect(queryClient.getQueryData(['auth-me'])).toBeNull();
    expect(queryClient.getQueryData(['transactions', 1])).toBeUndefined();
  });
});
