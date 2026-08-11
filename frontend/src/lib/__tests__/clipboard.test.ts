import { describe, expect, it, vi, afterEach } from 'vitest';

import { copiarTexto } from '../clipboard';

/*
 * O botão "Copiar link" mentia num deploy sem HTTPS.
 *
 * `navigator.clipboard` não existe fora de contexto seguro — e o "Cenário B" do
 * SETUP.md é exatamente isso: `http://192.168.x.x` numa rede local. Todo botão
 * de copiar do sistema não fazia nada e dizia que tinha feito; num dos casos
 * estourava `TypeError` na cara do usuário. O que estes testes fixam é o
 * contrato que a tela usa: **devolver se copiou de verdade**.
 */

function comClipboard(impl: unknown) {
  Object.defineProperty(navigator, 'clipboard', {
    value: impl, configurable: true, writable: true,
  });
}

afterEach(() => {
  comClipboard(undefined);
  vi.unstubAllGlobals();
});

describe('copiarTexto', () => {
  it('usa a API moderna quando ela existe', async () => {
    const writeText = vi.fn(async () => undefined);
    comClipboard({ writeText });

    expect(await copiarTexto('http://x/register?invite=tok')).toBe(true);
    expect(writeText).toHaveBeenCalledWith('http://x/register?invite=tok');
  });

  it('recua para execCommand quando não há contexto seguro', async () => {
    comClipboard(undefined);
    const execCommand = vi.fn(() => true);
    document.execCommand = execCommand as unknown as typeof document.execCommand;

    expect(await copiarTexto('link')).toBe(true);
    expect(execCommand).toHaveBeenCalledWith('copy');
    // O textarea temporário não pode ficar na página.
    expect(document.querySelectorAll('textarea')).toHaveLength(0);
  });

  it('recua também quando a API existe e REJEITA (aba sem foco)', async () => {
    comClipboard({ writeText: vi.fn(async () => { throw new Error('sem foco'); }) });
    document.execCommand = vi.fn(() => true) as unknown as typeof document.execCommand;

    expect(await copiarTexto('link')).toBe(true);
  });

  it('devolve false quando nem o recuo funciona — e não lança', async () => {
    comClipboard(undefined);
    document.execCommand = vi.fn(() => false) as unknown as typeof document.execCommand;

    expect(await copiarTexto('link')).toBe(false);
  });

  it('não lança quando o recuo estoura', async () => {
    comClipboard(undefined);
    document.execCommand = vi.fn(() => {
      throw new Error('obsoleto neste navegador');
    }) as unknown as typeof document.execCommand;

    expect(await copiarTexto('link')).toBe(false);
  });
});
