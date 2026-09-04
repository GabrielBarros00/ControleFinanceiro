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

  it('o passo 2 tem o campo de salário e o botão de avançar', () => {
    render(<OnboardingModal />);
    fireEvent.click(screen.getByRole('button', { name: ONBOARDING.comecar }));

    const salario = screen.getByLabelText(ONBOARDING.salario);
    expect(salario).toBeInTheDocument();

    // "Próximo" só aparece com salário preenchido — sem ele o botão é
    // "Pular por enquanto". A suíte preenche antes de clicar, e o teste
    // reproduz essa ordem em vez de assumir que o botão está sempre lá.
    fireEvent.change(salario, { target: { value: '5000,00' } });
    expect(screen.getByRole('button', { name: ONBOARDING.proximo })).toBeInTheDocument();
  });

  it('o passo 3 tem a saída sem cadastrar cartão', () => {
    render(<OnboardingModal />);
    fireEvent.click(screen.getByRole('button', { name: ONBOARDING.comecar }));
    const salario = screen.getByLabelText(ONBOARDING.salario);
    fireEvent.change(salario, { target: { value: '5000,00' } });
    fireEvent.click(screen.getByRole('button', { name: ONBOARDING.proximo }));

    expect(screen.getByRole('button', { name: ONBOARDING.pular })).toBeInTheDocument();
  });
});

/**
 * A varredura: todo rótulo registrado ainda existe em algum lugar de `src/`.
 *
 * O teste acima renderiza o onboarding de verdade, e é o mais forte — mas ele
 * só cobre o onboarding. O `e2e-prod` também procurava "Sair da Conta", que
 * virou "Sair da conta" na mesma rodada, e essa falha ficou **escondida atrás
 * da primeira**: dois rótulos podres no mesmo arquivo, um encobrindo o outro,
 * cada um custando uma rodada de CI para aparecer.
 *
 * Esta varredura é grosseira de propósito — ela só pergunta "este texto ainda
 * existe no código?". Não prova que o botão está na tela certa nem que ele está
 * visível; prova que ninguém o renomeou sem passar por aqui. É barata o
 * bastante para rodar sempre, e pega exatamente a classe de erro que custou
 * duas rodadas de CI nesta sessão.
 */
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
