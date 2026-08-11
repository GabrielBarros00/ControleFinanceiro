import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { ConfirmProvider } from '@/components/ui/confirm';
import { AdminPage } from '../AdminPage';
import { bytes, dia } from '../formatters';

/*
 * A tela de administração (ADR 0026).
 *
 * O assunto que sustenta tudo: a tela mostra CONTAGEM e ESPAÇO, nunca dinheiro
 * de terceiro. O resto — formatação de bytes, dia de calendário, quem pode
 * mexer no papel de quem — é o que faria a tela mentir de formas mais discretas.
 */

const souSuperadmin = { valor: true };
const dadosDeUsuarios = {
  total: 2,
  limit: 50,
  offset: 0,
  items: [
    {
      id: 1, name: 'Dona do Site', email: 'dona@example.com', is_active: true,
      platform_role: 'superadmin' as const, created_at: '2026-01-01T12:00:00Z',
      deleted_at: null, needs_onboarding: false, last_login_at: '2026-08-10T15:00:00Z',
      workspaces: 2, lancamentos: 40, anexos_bytes: 1_048_576,
    },
    {
      id: 2, name: 'Pessoa Comum', email: 'comum@example.com', is_active: false,
      platform_role: 'user' as const, created_at: '2026-02-01T12:00:00Z',
      deleted_at: null, needs_onboarding: false, last_login_at: null,
      workspaces: 1, lancamentos: 3, anexos_bytes: 0,
    },
  ],
};

vi.mock('@/hooks/use-admin', () => ({
  useIsSuperadmin: () => souSuperadmin.valor,
  useIsPlatformAdmin: () => true,
  useAdminOverview: () => ({
    data: {
      usuarios_total: 3, usuarios_ativos: 2, usuarios_novos_30d: 1,
      workspaces: 4, lancamentos: 128, anexos_bytes: 2_621_440, anexos_qtd: 7,
      convites_pendentes: 1, sessoes_vivas: 2, banco_bytes: null,
    },
    isLoading: false, isError: false, refetch: vi.fn(),
  }),
  useAdminSaude: () => ({
    data: {
      cambio_ultima_data: '2026-08-10', cambio_cotacoes: 42, banco_bytes: 10_485_760,
      anexos_bytes: 2_621_440, sessoes_expiradas_pendentes_de_expurgo: 5,
      auditoria_linhas: 900, auditoria_mais_antiga: '2026-01-01T00:00:00Z',
    },
    isLoading: false,
  }),
  useAdminUsers: () => ({
    data: dadosDeUsuarios, isLoading: false, isError: false, refetch: vi.fn(),
    patch: { mutateAsync: vi.fn(), isPending: false },
    revogarSessoes: { mutateAsync: vi.fn(), isPending: false },
    remover: { mutateAsync: vi.fn(), isPending: false },
  }),
  useAdminSettings: () => ({
    data: {
      valores: {
        registration_mode: 'invite_only', who_can_invite: 'all_users',
        invite_expiry_days: 7, user_invite_quota_per_month: 5,
        attachment_quota_bytes: 209_715_200, upload_max_bytes: 5_242_880,
        import_max_rows: 5000, rate_limit_auth_per_minute: 20,
        rate_limit_account_per_minute: 10, maintenance_mode: false,
      },
      chaves: [
        { nome: 'registration_mode', descricao: '', origem_ambiente: 'REGISTRATION_MODE', sobrescrito: true },
        { nome: 'attachment_quota_bytes', descricao: '', origem_ambiente: 'ATTACHMENT_QUOTA_BYTES', sobrescrito: false },
        { nome: 'import_max_rows', descricao: '', origem_ambiente: 'IMPORT_MAX_ROWS', sobrescrito: false },
      ],
      limite_nginx_bytes: 6 * 1024 * 1024,
    },
    isLoading: false,
    salvar: { mutateAsync: vi.fn(), isPending: false },
    testarEmail: { mutateAsync: vi.fn(), isPending: false },
  }),
  useRegistrationInvites: () => ({
    data: [
      {
        id: 1, email: 'convidada@example.com', token: 'tok1', status: 'pending' as const,
        expires_at: '2026-09-01T12:00:00Z', max_uses: null, uses: 0,
        created_by_user_id: 1, accepted_by_user_id: null,
        created_at: '2026-08-01T12:00:00Z', link: 'http://x/register?invite=tok1',
      },
      {
        id: 2, email: null, token: 'tok2', status: 'accepted' as const,
        expires_at: '2026-09-01T12:00:00Z', max_uses: 3, uses: 3,
        created_by_user_id: 1, accepted_by_user_id: 2,
        created_at: '2026-08-02T12:00:00Z', link: 'http://x/register?invite=tok2',
      },
    ],
    isLoading: false,
    criar: { mutateAsync: vi.fn(), isPending: false },
    revogar: { mutateAsync: vi.fn(), isPending: false },
  }),
  useAdminAudit: () => ({
    data: [{
      id: 9, action: 'update', resource_type: 'User', resource_id: 2,
      user_id: 1, workspace_id: null, ip_address: '10.0.0.5',
      created_at: '2026-08-11T10:00:00Z',
    }],
    isLoading: false,
  }),
  useMeusConvitesDeCadastro: () => ({ data: [], isLoading: false, convidar: {} }),
}));

vi.mock('@/stores', async (original) => {
  const real = await original<typeof import('@/stores')>();
  return { ...real, useAuthStore: (s: (x: unknown) => unknown) => s({ user: { id: 1 } }) };
});

function renderizar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  // `ConfirmProvider` não é enfeite: as abas Pessoas e Convites usam
  // `useConfirm` para desativar conta e revogar convite — ações destrutivas que
  // o projeto proíbe fazer com `window.confirm`. Sem o provider, o hook lança e
  // a aba inteira falha ao montar.
  return render(
    <QueryClientProvider client={qc}>
      <ConfirmProvider>
        <AdminPage />
      </ConfirmProvider>
    </QueryClientProvider>,
  );
}

/**
 * O Radix Tabs ativa a aba no `mousedown`, não no `click` sintético — e o
 * conteúdo inativo é desmontado. Sem o `mousedown`, `screen.getByText` de
 * qualquer aba que não seja a inicial falha com "elemento não encontrado", o que
 * parece defeito da tela e é só o disparo errado.
 */
function abrirAba(nome: string) {
  const gatilho = screen.getByRole('tab', { name: nome });
  fireEvent.mouseDown(gatilho);
  fireEvent.click(gatilho);
}

beforeEach(() => {
  souSuperadmin.valor = true;
});

describe('formatação de tamanho', () => {
  it('mostra "—" quando o motor não sabe responder', () => {
    // `null` não é zero: exibir "0 B" faria parecer que o banco está vazio, que
    // é uma resposta — e errada.
    expect(bytes(null)).toBe('—');
    expect(bytes(undefined)).toBe('—');
  });

  it('zero bytes é zero, não "—"', () => {
    expect(bytes(0)).toBe('0 B');
  });

  it('escala as unidades', () => {
    expect(bytes(512)).toBe('512 B');
    expect(bytes(2_621_440)).toBe('2.5 MB');
    expect(bytes(1024 ** 3 * 3)).toBe('3.0 GB');
  });
});

describe('data de calendário', () => {
  it('não volta um dia num fuso negativo', () => {
    // A data da cotação é um DIA CIVIL. `new Date('2026-08-10')` é meia-noite
    // UTC e, em São Paulo (o fuso fixado na config do vitest), seria exibido
    // como 09/08 — a armadilha que o `parseApiDay` do projeto existe para evitar.
    expect(dia('2026-08-10')).toBe('10/08/2026');
    expect(dia('2026-01-01')).toBe('01/01/2026');
  });

  it('lida com ausência', () => {
    expect(dia(null)).toBe('—');
  });
});

describe('visão geral', () => {
  it('mostra as seis abas', () => {
    renderizar();
    for (const aba of ['Visão geral', 'Pessoas', 'Convites', 'Configurações', 'Saúde', 'Auditoria']) {
      expect(screen.getByRole('tab', { name: aba })).toBeInTheDocument();
    }
  });

  it('exibe contagens e espaço, e nenhum valor em dinheiro', () => {
    const { container } = renderizar();
    expect(screen.getByText('128')).toBeInTheDocument();    // lançamentos: quantos
    expect(screen.getByText('2.5 MB')).toBeInTheDocument();  // anexos: quanto ocupa

    // A promessa do ADR 0026, na tela.
    expect(container.textContent).not.toMatch(/R\$/);
    expect(container.textContent).not.toMatch(/total gasto/i);
  });

  it('mostra "—" para o tamanho do banco quando é desconhecido', () => {
    renderizar();
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });
});

describe('pessoas', () => {
  it('lista cada pessoa com o próprio uso', () => {
    renderizar();
    abrirAba('Pessoas');

    const linha = screen.getByText('comum@example.com').closest('tr')!;
    expect(within(linha).getByText('3')).toBeInTheDocument();   // lançamentos
    expect(within(linha).getByText('0 B')).toBeInTheDocument(); // anexos
    expect(within(linha).getByText('—')).toBeInTheDocument();   // nunca entrou
  });

  it('superadministrador pode trocar o papel dos outros', () => {
    renderizar();
    abrirAba('Pessoas');
    expect(screen.getByLabelText('Papel de Pessoa Comum')).toBeInTheDocument();
  });

  it('ninguém troca o próprio papel pela lista', () => {
    // Quem está logado é o id 1 (Dona do Site). A trava de verdade é do
    // servidor; aqui é para não oferecer um controle que só produz erro.
    renderizar();
    abrirAba('Pessoas');
    expect(screen.queryByLabelText('Papel de Dona do Site')).not.toBeInTheDocument();
  });

  it('administrador comum não recebe o seletor de papel', () => {
    souSuperadmin.valor = false;
    renderizar();
    abrirAba('Pessoas');
    expect(screen.queryByLabelText('Papel de Pessoa Comum')).not.toBeInTheDocument();
    // Vê o papel, mas como texto.
    expect(screen.getAllByText('Usuário').length).toBeGreaterThan(0);
  });
});

describe('convites', () => {
  it('distingue convite nominal de link aberto', () => {
    renderizar();
    abrirAba('Convites');
    expect(screen.getByText('convidada@example.com')).toBeInTheDocument();
    expect(screen.getByText('Link aberto')).toBeInTheDocument();
  });

  it('mostra os usos contra o teto', () => {
    renderizar();
    abrirAba('Convites');
    expect(screen.getByText('3 / 3')).toBeInTheDocument();
  });

  it('só oferece revogar no que ainda está pendente', () => {
    renderizar();
    abrirAba('Convites');
    expect(screen.getAllByRole('button', { name: 'Revogar' })).toHaveLength(1);
  });
});

describe('configurações', () => {
  it('explica o teto do servidor web no tamanho de arquivo', () => {
    // O `client_max_body_size` do nginx fica NA FRENTE do backend: sem este
    // aviso, o operador salvaria 20 MB e o usuário levaria 413 numa página que
    // nem é do aplicativo.
    renderizar();
    abrirAba('Configurações');
    expect(screen.getByText(/Máximo de 6 MB/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Tamanho máximo por arquivo/)).toHaveAttribute('max', '6');
  });

  it('converte bytes em MB nos campos de quota', () => {
    renderizar();
    abrirAba('Configurações');
    expect(screen.getByLabelText(/Anexos por workspace/)).toHaveValue(200);
  });

  it('diz quando o valor ainda acompanha o .env', () => {
    renderizar();
    abrirAba('Configurações');
    expect(screen.getByText(/Acompanha ATTACHMENT_QUOTA_BYTES/)).toBeInTheDocument();
  });

  it('só oferece salvar depois de alguma alteração', () => {
    renderizar();
    abrirAba('Configurações');
    expect(screen.queryByRole('button', { name: 'Salvar' })).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/Validade do convite/), { target: { value: '14' } });
    expect(screen.getByRole('button', { name: 'Salvar' })).toBeInTheDocument();
    expect(screen.getByText('Há alterações não salvas.')).toBeInTheDocument();
  });
});

describe('saúde', () => {
  it('mostra o frescor do câmbio como dia de calendário', () => {
    renderizar();
    abrirAba('Saúde');
    expect(screen.getByText('10/08/2026')).toBeInTheDocument();
    expect(screen.getByText(/42 cotação/)).toBeInTheDocument();
  });

  it('explica o que uma data atrasada significa', () => {
    // Se o `cron` morre, nada quebra na hora — recorrências em moeda estrangeira
    // só param de nascer, em silêncio. A tela precisa dizer isso.
    renderizar();
    abrirAba('Saúde');
    expect(screen.getByText(/deixam de nascer sem emitir erro/)).toBeInTheDocument();
  });
});

describe('auditoria', () => {
  it('mostra quem fez o quê, sem o conteúdo do que mudou', () => {
    const { container } = renderizar();
    abrirAba('Auditoria');
    expect(screen.getByText('User #2')).toBeInTheDocument();
    expect(screen.getByText('10.0.0.5')).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/old_values|new_values/);
  });
});
