import { afterEach, describe, expect, it } from 'vitest';
import { esquecerSeqsDoBootstrap, registrarSeqDoBootstrap, seqDoBootstrap } from '../seq-do-bootstrap';

describe('seq do bootstrap (P2)', () => {
  afterEach(() => esquecerSeqsDoBootstrap());

  it('guarda o seq de cada espaço', () => {
    registrarSeqDoBootstrap([{ id: 1, event_seq: 7 }, { id: 2, event_seq: 0 }]);
    expect(seqDoBootstrap(1)).toBe(7);
    expect(seqDoBootstrap(2)).toBe(0);
    expect(seqDoBootstrap(3)).toBeUndefined();
  });

  it('a primeira leitura vence: um seq mais novo não é limite inferior das consultas já feitas', () => {
    registrarSeqDoBootstrap([{ id: 1, event_seq: 7 }]);
    registrarSeqDoBootstrap([{ id: 1, event_seq: 12 }, { id: 2, event_seq: 4 }]);
    expect(seqDoBootstrap(1)).toBe(7);
    // Espaço que apareceu depois (convite aceito, espaço criado) entra normalmente.
    expect(seqDoBootstrap(2)).toBe(4);
  });

  it('resposta sem o campo (servidor antigo) não registra nada — cai no resync completo', () => {
    registrarSeqDoBootstrap([{ id: 1 }, { id: 2, event_seq: null }]);
    expect(seqDoBootstrap(1)).toBeUndefined();
    expect(seqDoBootstrap(2)).toBeUndefined();
  });

  it('o logout esquece', () => {
    registrarSeqDoBootstrap([{ id: 1, event_seq: 7 }]);
    esquecerSeqsDoBootstrap();
    expect(seqDoBootstrap(1)).toBeUndefined();
  });
});
