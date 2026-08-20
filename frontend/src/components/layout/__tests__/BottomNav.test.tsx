import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { BottomNav } from '../BottomNav';
import { mobilePrimaryPaths, navFlat } from '../nav-items';

/*
 * A barra mobile — e o FAB que lançava despesa na casa errada.
 *
 * Dois defeitos que a auditoria externa encontrou e que nenhum teste pegava,
 * porque a suíte de acessibilidade só roda em viewport desktop, onde a barra
 * inteira está escondida por `md:hidden`:
 *
 * 1. O FAB "Nova despesa" aparecia em TODA rota, inclusive `/overview`. Fora de
 *    `/w/:id` o diálogo usava o último workspace do `localStorage`, sem dizer
 *    qual — e o ADR 0020 define a visão global como somente leitura justamente
 *    para isso não acontecer.
 * 2. `mobilePrimaryPaths` apontava para `/w/:id/cards`, que deixou de existir no
 *    ADR 0021 (virou `/me/cards`). A `BottomNav` casa por igualdade e descarta em
 *    silêncio o que não encontra: o terceiro slot sumia da barra.
 */

const setOpen = vi.fn();

vi.mock('@/stores', () => ({
  useNewTxStore: (seletor: (s: unknown) => unknown) => seletor({ setOpen }),
  useUIStore: (seletor: (s: unknown) => unknown) =>
    // O "último workspace visitado" está preenchido de propósito: é ele que
    // fazia o FAB parecer utilizável fora de `/w/:id`.
    seletor({ currentWorkspaceId: 42 }),
  // Quem está logado, só para o rótulo do espaço dizer "De você" quando for o
  // caso. Aqui é OUTRA pessoa (id 1 ≠ dono 9), então sai o nome do dono.
  useAuthStore: (seletor: (s: unknown) => unknown) =>
    seletor({ user: { id: 1, name: 'Bruno' } }),
}));

vi.mock('@/hooks/use-auth', () => ({
  useAuth: () => ({ logout: vi.fn().mockResolvedValue(undefined) }),
}));

// A gaveta "Mais" passou a montar as SEÇÕES da navegação (era uma grade achatada
// que não dizia o que era pessoal e o que era do espaço), e para isso lê o papel
// de plataforma e o nome do espaço atual. Os dois hooks são react-query, que sem
// `QueryClientProvider` lança — mockar é mais barato que embrulhar o teste, que
// não tem nada a ver com busca de dados.
vi.mock('@/hooks/use-admin', () => ({
  useIsPlatformAdmin: () => false,
}));

vi.mock('@/hooks/use-workspaces', () => ({
  useWorkspaces: () => ({
    workspaces: [
      // O fixture tinha só id/nome/contagem, e por isso nada aqui pegava o dono
      // sumido da interface: a API mandava `owner_name` desde sempre e nenhuma
      // tela lia. Agora ele faz parte do contrato que os testes exercem.
      { id: 7, name: 'Casa da Praia', member_count: 3, owner_user_id: 9, owner_name: 'Ana Souza' },
    ],
    currentWorkspace: null,
    switchWorkspace: vi.fn(),
  }),
}));

function renderEm(rota: string) {
  return render(
    <MemoryRouter initialEntries={[rota]}>
      <Routes>
        <Route path="/w/:workspaceId/*" element={<BottomNav />} />
        <Route path="*" element={<BottomNav />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => setOpen.mockClear());

describe('BottomNav — o FAB só existe dentro de um workspace', () => {
  it('não oferece "Nova despesa" na visão global', () => {
    renderEm('/overview');
    expect(screen.queryByLabelText('Nova despesa')).not.toBeInTheDocument();
  });

  it.each(['/me/cards', '/me/income', '/me/settings'])(
    'não oferece "Nova despesa" em %s',
    (rota) => {
      renderEm(rota);
      expect(screen.queryByLabelText('Nova despesa')).not.toBeInTheDocument();
    },
  );

  it('oferece "Nova despesa" dentro de /w/:id', () => {
    renderEm('/w/7/transactions');
    expect(screen.getByLabelText('Nova despesa')).toBeInTheDocument();
  });

  it('o workspace guardado no navegador NÃO habilita o FAB', () => {
    // `useWorkspaceId` cai no `localStorage` fora de `/w/:id` — é por isso que o
    // FAB precisa do hook estrito, e não daquele.
    renderEm('/overview');
    expect(screen.queryByLabelText('Nova despesa')).not.toBeInTheDocument();
  });
});

describe('mobilePrimaryPaths', () => {
  it('só aponta para rotas que existem na navegação', () => {
    for (const workspaceId of [null, 7]) {
      const existentes = new Set(navFlat(workspaceId).map((i) => i.to));
      for (const caminho of mobilePrimaryPaths(workspaceId)) {
        expect(existentes, `slot órfão: ${caminho}`).toContain(caminho);
      }
    }
  });

  it('cartões apontam para a rota pessoal, não para a do workspace', () => {
    expect(mobilePrimaryPaths(7)).toContain('/me/cards');
    expect(mobilePrimaryPaths(7)).not.toContain('/w/7/cards');
  });

  it('todos os slots viram item visível na barra', () => {
    renderEm('/w/7/transactions');
    // Um slot que não casa é descartado em silêncio — este é o teste que
    // teria pego o `/w/:id/cards` órfão.
    for (const caminho of mobilePrimaryPaths(7)) {
      const item = navFlat(7).find((i) => i.to === caminho)!;
      expect(screen.getAllByText(item.label).length).toBeGreaterThan(0);
    }
  });
});
