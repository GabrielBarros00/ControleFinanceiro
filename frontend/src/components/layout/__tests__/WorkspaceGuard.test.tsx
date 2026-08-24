import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { WorkspaceGuard } from '../WorkspaceGuard';

/*
 * O porteiro de `/w/:id` — e a diferença entre "não é seu" e "não deu para saber".
 *
 * O guard decidia com `workspaces.length` e nada mais. Como `useWorkspaces`
 * devolve `listQuery.data ?? []`, uma falha de rede chegava aqui exatamente igual
 * a uma resposta legítima vazia: o backend piscava, a lista vinha `[]`, e a pessoa
 * era EJETADA do espaço em que estava para `/overview` — com `replace`, então nem
 * o botão "voltar" desfazia. Nenhum teste cobria o arquivo.
 *
 * O `isLoading` já existia e funcionava; o que faltava era o terceiro estado.
 */

const setCurrentWorkspaceId = vi.fn();
const refetch = vi.fn();

let estado: {
  workspaces: { id: number; name: string }[];
  isLoading: boolean;
  isError: boolean;
};

vi.mock('@/hooks/use-workspaces', () => ({
  useWorkspaces: () => ({ ...estado, refetch }),
}));

vi.mock('@/stores', () => ({
  useUIStore: (seletor: (s: unknown) => unknown) => seletor({ setCurrentWorkspaceId }),
}));

function renderGuard(rota = '/w/7/transactions') {
  return render(
    <MemoryRouter initialEntries={[rota]}>
      <Routes>
        <Route path="/w/:workspaceId" element={<WorkspaceGuard />}>
          <Route path="transactions" element={<p>Extrato do espaço</p>} />
        </Route>
        <Route path="/overview" element={<p>Visão pessoal</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  setCurrentWorkspaceId.mockClear();
  refetch.mockClear();
  estado = { workspaces: [{ id: 7, name: 'Casa da Praia' }], isLoading: false, isError: false };
});

describe('WorkspaceGuard', () => {
  it('deixa passar quem participa do espaço da URL', () => {
    renderGuard();
    expect(screen.getByText('Extrato do espaço')).toBeInTheDocument();
    expect(setCurrentWorkspaceId).toHaveBeenCalledWith(7);
  });

  it('manda para a visão pessoal quem NÃO participa', () => {
    estado.workspaces = [{ id: 3, name: 'Outra' }];
    renderGuard();
    expect(screen.getByText('Visão pessoal')).toBeInTheDocument();
  });

  it('espera a lista carregar antes de decidir', () => {
    // Decidir com a lista vazia no primeiro render mandaria TODO MUNDO para
    // /overview, mesmo com acesso legítimo.
    estado = { workspaces: [], isLoading: true, isError: false };
    renderGuard();
    expect(screen.queryByText('Visão pessoal')).not.toBeInTheDocument();
    expect(screen.queryByText('Extrato do espaço')).not.toBeInTheDocument();
  });

  it('em caso de ERRO mostra a falha com retry, sem redirecionar', () => {
    // Este é o caso que não existia: `data` fica `undefined`, o hook devolve `[]`,
    // e antes disso o guard lia isso como "você não é membro".
    estado = { workspaces: [], isLoading: false, isError: true };
    renderGuard();

    expect(screen.queryByText('Visão pessoal')).not.toBeInTheDocument();
    expect(screen.getByText(/Não foi possível carregar seus espaços/i)).toBeInTheDocument();
    screen.getByRole('button', { name: /tentar novamente/i }).click();
    expect(refetch).toHaveBeenCalled();
  });

  it('id inválido na URL não vira erro nem carrega outro espaço', () => {
    // Mascarar um link quebrado carregando dados de outro espaço é pior que a
    // tela vazia — mesma regra de `useWorkspaceId`.
    renderGuard('/w/abc/transactions');
    expect(screen.getByText('Visão pessoal')).toBeInTheDocument();
  });
});
