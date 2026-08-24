import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ScopeSwitcher } from '../ScopeSwitcher';
import { rotuloDeEspaco } from '../nav-items';

/*
 * "De quem é este espaço" — o dado que a API mandava e nenhuma tela lia.
 *
 * `WorkspaceRead` devolve `owner_name`/`owner_user_id` desde que o seletor
 * existe, e o seletor mostrava só "3 pessoas". Quem participa de dois espaços de
 * nome parecido ("Casa", "Casa da praia") não tinha como saber qual é o da Ana.
 */

const espacos = [
  { id: 7, name: 'Casa da Praia', member_count: 3, owner_user_id: 9, owner_name: 'Ana Souza' },
  { id: 8, name: 'Meu canto', member_count: 1, owner_user_id: 1, owner_name: 'Bruno Lima' },
  // Resposta antiga em cache, ou espaço sem membership `owner`: o rótulo NÃO
  // pode virar "De undefined" — cai no formato de antes.
  { id: 9, name: 'Herdado', member_count: 2 },
];

vi.mock('@/hooks/use-workspaces', () => ({
  useWorkspaces: () => ({
    workspaces: espacos,
    currentWorkspace: espacos[0],
    switchWorkspace: vi.fn(),
  }),
}));

vi.mock('@/stores', () => ({
  // O usuário logado é o Bruno (id 1), que é dono do espaço 8.
  useAuthStore: (seletor: (s: unknown) => unknown) => seletor({ user: { id: 1, name: 'Bruno Lima' } }),
}));

vi.mock('@/components/workspace/WorkspaceCreateDialog', () => ({
  WorkspaceCreateDialog: () => null,
}));

function renderEm(rota: string) {
  return render(
    <MemoryRouter initialEntries={[rota]}>
      <Routes>
        <Route path="/w/:workspaceId/*" element={<ScopeSwitcher />} />
        <Route path="*" element={<ScopeSwitcher />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe('rotuloDeEspaco', () => {
  it('compõe dono e número de pessoas', () => {
    expect(rotuloDeEspaco(espacos[0], 1)).toBe('De Ana Souza · 3 pessoas');
  });

  it('diz "De você" em vez de repetir o nome de quem está logado', () => {
    expect(rotuloDeEspaco(espacos[1], 1)).toBe('De você · só você');
  });

  it('sem owner_name cai no rótulo de membros — nunca "De undefined"', () => {
    expect(rotuloDeEspaco(espacos[2], 1)).toBe('2 pessoas');
    expect(rotuloDeEspaco({ member_count: 1 }, 1)).toBe('Só você');
    expect(rotuloDeEspaco(undefined, 1)).toBeUndefined();
  });

  it('sem usuário conhecido, o dono ainda aparece pelo nome', () => {
    // Durante a checagem de sessão o `user` da store é `null`; o rótulo não pode
    // sumir por causa disso.
    expect(rotuloDeEspaco(espacos[1], null)).toBe('De Bruno Lima · só você');
  });
});

describe('ScopeSwitcher', () => {
  it('mostra o dono no botão do espaço atual', () => {
    renderEm('/w/7/transactions');
    expect(screen.getByText('Casa da Praia')).toBeInTheDocument();
    expect(screen.getByText('De Ana Souza · 3 pessoas')).toBeInTheDocument();
  });

  it('na camada pessoal continua dizendo o que aquilo é', () => {
    renderEm('/overview');
    expect(screen.getByText('Pessoal')).toBeInTheDocument();
    expect(screen.getByText('Só você vê')).toBeInTheDocument();
  });
});
