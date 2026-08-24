import { renderHook, act, waitFor } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';

/*
 * A oferta de instalar o app — e o defeito que ela tinha.
 *
 * O caso central é o PRIMEIRO teste: o `beforeinstallprompt` disparado ANTES de
 * qualquer componente renderizar. É o que acontece de verdade — o Chrome o
 * dispara uma vez, cedo, ainda em `/login`, e não o repete em navegação de SPA.
 * Enquanto a captura vivia dentro do hook, o evento chegava a um mundo sem
 * ninguém escutando e o botão "Instalar" nunca mais aparecia; o único percurso
 * em que ele funcionava era dar F5 estando em `/settings`.
 *
 * Medido: comentando a chamada de `iniciarCapturaDeInstalacao()` em `main.tsx`
 * (que é o equivalente exato de voltar a capturar só na montagem), este teste
 * falha com `'indisponivel'` em vez de `'disponivel'`. Os outros três continuam
 * passando — é este que segura a regressão.
 *
 * ## Por que `resetModules` + import dinâmico
 *
 * O store é um singleton de módulo, de propósito (é o que permite sobreviver às
 * trocas de rota). Sem zerar o registro de módulos entre os casos, o evento
 * capturado num teste apareceria no seguinte. A alternativa seria um
 * `__resetParaTestes()` exportado do código de produção — uma porta que só
 * existe para o teste, e que o código de verdade poderia chamar por engano.
 */

/** O evento do Chromium, montado à mão: o jsdom não tem esta classe. */
function eventoDeInstalacao() {
  const evento = new Event('beforeinstallprompt') as Event & {
    prompt: ReturnType<typeof vi.fn>;
    userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
  };
  evento.prompt = vi.fn().mockResolvedValue(undefined);
  evento.userChoice = Promise.resolve({ outcome: 'accepted' as const });
  return evento;
}

/** Zera o registro e devolve os dois módulos da MESMA geração. */
async function carregar() {
  const install = await import('@/lib/install');
  const hook = await import('../use-install-prompt');
  install.iniciarCapturaDeInstalacao();
  return { install, useInstallPrompt: hook.useInstallPrompt };
}

beforeEach(() => {
  vi.resetModules();
  vi.unstubAllGlobals();
});

describe('useInstallPrompt', () => {
  it('enxerga o evento que chegou ANTES de o componente montar', async () => {
    const { useInstallPrompt } = await carregar();

    // A ordem é o teste: o evento primeiro, o render depois.
    window.dispatchEvent(eventoDeInstalacao());

    const { result } = renderHook(() => useInstallPrompt());
    expect(result.current.estado).toBe('disponivel');
  });

  it('sem evento e fora do iOS, não há o que oferecer', async () => {
    const { useInstallPrompt } = await carregar();
    const { result } = renderHook(() => useInstallPrompt());
    expect(result.current.estado).toBe('indisponivel');
  });

  it('`appinstalled` apaga a oferta e passa a afirmar que o app existe', async () => {
    const { useInstallPrompt } = await carregar();
    window.dispatchEvent(eventoDeInstalacao());

    const { result } = renderHook(() => useInstallPrompt());
    expect(result.current.estado).toBe('disponivel');

    act(() => {
      window.dispatchEvent(new Event('appinstalled'));
    });

    // `indisponivel`, e não `instalado`: quem instalou a partir de uma aba
    // CONTINUA numa aba. `estado` fala da janela; `appDetectado`, do aparelho.
    expect(result.current.estado).toBe('indisponivel');
    expect(result.current.appDetectado).toBe(true);
  });

  it('o evento é de uso único: o segundo clique não reabre o diálogo', async () => {
    const { useInstallPrompt } = await carregar();
    const evento = eventoDeInstalacao();
    window.dispatchEvent(evento);

    const { result } = renderHook(() => useInstallPrompt());

    await act(async () => {
      expect(await result.current.instalar()).toBe(true);
    });
    expect(evento.prompt).toHaveBeenCalledTimes(1);

    await act(async () => {
      expect(await result.current.instalar()).toBe(false);
    });
    expect(evento.prompt).toHaveBeenCalledTimes(1);
    expect(result.current.estado).toBe('indisponivel');
  });

  it('navegador sem `getInstalledRelatedApps` responde "não sei", não "não"', async () => {
    // O jsdom não implementa a API — é exatamente o cenário do iPhone e do
    // Firefox. Confundir `null` com `false` faria o diagnóstico de
    // Configurações AFIRMAR que o app não está instalado onde ele não tem como
    // saber.
    expect('getInstalledRelatedApps' in navigator).toBe(false);

    const { useInstallPrompt } = await carregar();
    const { result } = renderHook(() => useInstallPrompt());
    expect(result.current.appDetectado).toBeNull();
  });

  it('com a API disponível, um WebAPK instalado é detectado', async () => {
    vi.stubGlobal('navigator', {
      ...window.navigator,
      userAgent: window.navigator.userAgent,
      maxTouchPoints: 0,
      getInstalledRelatedApps: vi.fn().mockResolvedValue([{ platform: 'webapp', url: '/' }]),
    });

    const { useInstallPrompt } = await carregar();
    const { result } = renderHook(() => useInstallPrompt());

    // A consulta é assíncrona: nasce `null` e vira `true` quando resolve.
    await waitFor(() => expect(result.current.appDetectado).toBe(true));
  });
});
