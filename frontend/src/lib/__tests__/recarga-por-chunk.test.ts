import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { JANELA_MS, deveRecarregar, instalarRecargaPorChunk } from '../recarga-por-chunk';

/** O evento que o helper de preload do Vite dispara quando o `import()` falha. */
function falhaDeChunk(): Event {
  return new Event('vite:preloadError', { cancelable: true });
}

describe('recarga única quando o chunk some (C6)', () => {
  let remover: () => void = () => {};

  beforeEach(() => {
    sessionStorage.clear();
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-26T12:00:00Z'));
  });

  afterEach(() => {
    remover();
    vi.useRealTimers();
    sessionStorage.clear();
  });

  it('a primeira falha recarrega e cancela o erro', () => {
    const recarregar = vi.fn();
    remover = instalarRecargaPorChunk(recarregar);

    const evento = falhaDeChunk();
    window.dispatchEvent(evento);

    expect(recarregar).toHaveBeenCalledTimes(1);
    expect(evento.defaultPrevented).toBe(true);
  });

  it('a segunda falha logo depois NÃO recarrega de novo: sem laço, o erro sobe para a tela', () => {
    const recarregar = vi.fn();
    remover = instalarRecargaPorChunk(recarregar);
    window.dispatchEvent(falhaDeChunk());

    // A página "recarregou" e o chunk continua faltando.
    vi.advanceTimersByTime(2_000);
    const segunda = falhaDeChunk();
    window.dispatchEvent(segunda);

    expect(recarregar).toHaveBeenCalledTimes(1);
    expect(segunda.defaultPrevented).toBe(false);
  });

  it('um deploy mais tarde, na mesma aba, recarrega outra vez', () => {
    const recarregar = vi.fn();
    remover = instalarRecargaPorChunk(recarregar);
    window.dispatchEvent(falhaDeChunk());

    vi.advanceTimersByTime(JANELA_MS + 1);
    window.dispatchEvent(falhaDeChunk());

    expect(recarregar).toHaveBeenCalledTimes(2);
  });

  it('sem sessionStorage, não recarrega (não haveria como evitar o laço)', () => {
    const recarregar = vi.fn();
    remover = instalarRecargaPorChunk(recarregar);
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('bloqueado');
    });

    const evento = falhaDeChunk();
    window.dispatchEvent(evento);

    expect(recarregar).not.toHaveBeenCalled();
    expect(evento.defaultPrevented).toBe(false);
    setItem.mockRestore();
  });

  it('deveRecarregar: nunca, ou há mais que a janela', () => {
    expect(deveRecarregar(1_000_000, null)).toBe(true);
    expect(deveRecarregar(1_000_000, Number.NaN)).toBe(true);
    expect(deveRecarregar(1_000_000, 1_000_000 - JANELA_MS)).toBe(false);
    expect(deveRecarregar(1_000_000, 1_000_000 - JANELA_MS - 1)).toBe(true);
  });
});
