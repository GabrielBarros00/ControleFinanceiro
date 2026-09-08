import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@/test/utils';
import { OnboardingModal } from '../OnboardingModal';
import { ONBOARDING, ONDE, ROTULOS } from '../../../../e2e-shared/rotulos';

/**
 * Os rótulos do onboarding, conferidos em segundos em vez de em quarenta minutos.
 *
 * ## O episódio que gerou este arquivo
 *
 * Uma rodada de melhorias de texto renomeou "Começar Setup" para "Começar" e
 * "Próximo Passo" para "Próximo". As suítes de `e2e/` foram atualizadas — elas
 * rodam na máquina. As de `e2e-prod/` não: elas só existem no CI, atrás do
 * docker compose, e o resultado foi um job **vermelho por um motivo que não
 * tinha nada a ver com o que ele testa** (sessão atrás do nginx), descoberto
 * quarenta minutos depois do push.
 *
 * O onboarding é o caminho de entrada de TODA suíte de ponta a ponta: ele é
 * atravessado antes de qualquer teste que precise de uma conta. Quebrar um
 * rótulo dele não quebra um teste — quebra a suíte inteira, com uma mensagem
 * que aponta para o lugar errado.
 *
 * Este teste não protege o texto (o texto pode e deve mudar): ele protege o
 * ACOPLAMENTO. Se o rótulo mudar sem que `e2e-shared/rotulos.ts` mude junto, a
 * falha aparece aqui, em segundos, com o nome certo.
 */
vi.mock('@/hooks/use-auth', () => ({
  // `needs_onboarding` é o que abre o diálogo — é o estado do usuário NOVO, que
  // é justamente por onde toda suíte de ponta a ponta entra.
  useAuth: () => ({ user: { id: 1, name: 'Ana Martins', needs_onboarding: true } }),
}));
vi.mock('@/hooks/use-base-currency', () => ({ useBaseCurrency: () => 'BRL' }));

describe('Onboarding — os rótulos que as suítes e2e digitam', () => {
  it('o passo 1 tem o botão que a suíte procura', () => {
    render(<OnboardingModal />);
    expect(screen.getByRole('button', { name: ONBOARDING.comecar })).toBeInTheDocument();
  });

  it('o passo 2 pergunta onde está o dinheiro e quanto há', () => {
    render(<OnboardingModal />);
    fireEvent.click(screen.getByRole('button', { name: ONBOARDING.comecar }));

    expect(screen.getByLabelText(ONBOARDING.ondeEstaODinheiro)).toBeInTheDocument();
    expect(screen.getByLabelText(ONBOARDING.quantoHa)).toBeInTheDocument();
  });

  it('o botão conclui quando há conta e pula quando não há', () => {
    render(<OnboardingModal />);
    fireEvent.click(screen.getByRole('button', { name: ONBOARDING.comecar }));

    // Sem conta: o mesmo botão é a saída. Quem não sabe o número agora não pode
    // ficar preso na porta de entrada.
    expect(screen.getByRole('button', { name: ONBOARDING.pular })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(ONBOARDING.ondeEstaODinheiro), {
      target: { value: 'Nubank' },
    });
    expect(screen.getByRole('button', { name: ONBOARDING.concluir })).toBeInTheDocument();
  });
});

describe('Rótulos registrados x código', () => {
  it('todo texto registrado existe no arquivo em que a suíte vai clicar', async () => {
    const fs = await import('node:fs/promises');
    const path = await import('node:path');
    const raiz = path.resolve(__dirname, '../../../..');

    const registrados: string[] = [
      ...Object.values(ONBOARDING),
      ...Object.values(ROTULOS),
    ];

    const problemas: string[] = [];
    for (const texto of registrados) {
      const arquivo = ONDE[texto];
      if (!arquivo) {
        problemas.push(`"${texto}" não diz em que arquivo mora (ver ONDE)`);
        continue;
      }
      const fonte = await fs.readFile(path.join(raiz, arquivo), 'utf8');
      if (!fonte.includes(texto)) {
        problemas.push(`"${texto}" não existe mais em ${arquivo}`);
      }
    }

    expect(
      problemas,
      'rótulo registrado que sumiu do lugar onde a suíte clica — alguma suíte '
      + 'vai procurá-lo e não achar: ' + problemas.join(' · '),
    ).toEqual([]);
  });
});
