import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { RegisterPage } from '../RegisterPage';

/*
 * O PORTÃO da tela de cadastro (ADR 0026).
 *
 * Este arquivo nasceu de um defeito que passou por todos os portões automáticos:
 * num deploy novo o modo é `invite_only`, ninguém tem convite e não existe quem
 * o emita — e a tela escondia o formulário, tornando IMPOSSÍVEL pelo navegador o
 * primeiro acesso que o SETUP.md manda fazer. Ninguém pegou porque esta tela não
 * tinha teste nenhum, e porque o `smoke_prod.py` e o `global-setup.ts` do e2e se
 * cadastram pela API — os dois caminhos que existem passam ao largo da tela.
 *
 * A regra que os testes fixam: a tela só esconde o formulário quando NÃO HÁ
 * nenhuma forma de entrar. Esconder é conveniência; a decisão continua sendo do
 * `POST /auth/register`.
 */

const politica = {
  valor: {
    mode: 'invite_only',
    aceita_cadastro: true,
    exige_convite: true,
    primeiro_acesso: false,
  } as Record<string, unknown> | null,
};

vi.mock('@/api/client', () => ({
  baseURL: 'http://api.test/api/v1',
  apiClient: {
    get: vi.fn(async () => {
      if (politica.valor === null) throw new Error('rede fora do ar');
      return { data: politica.valor };
    }),
  },
}));

vi.mock('@/hooks/use-auth', () => ({
  useAuth: () => ({ register: vi.fn(), login: vi.fn() }),
}));

const parametros = { busca: '' };

function renderizar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/register${parametros.busca}`]}>
        <RegisterPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const formularioNaTela = () => screen.queryByLabelText('Nome Completo');

beforeEach(() => {
  parametros.busca = '';
  politica.valor = {
    mode: 'invite_only', aceita_cadastro: true, exige_convite: true, primeiro_acesso: false,
  };
});

describe('cadastro por convite', () => {
  it('esconde o formulário quando exige convite e não há token', async () => {
    renderizar();
    await screen.findByText('Cadastro por convite');
    expect(formularioNaTela()).not.toBeInTheDocument();
  });

  it('mostra o formulário quando o convite acompanha a URL', async () => {
    parametros.busca = '?invite=tok123';
    renderizar();
    expect(await screen.findByLabelText('Nome Completo')).toBeInTheDocument();
    expect(screen.getByText(/Você foi convidado/)).toBeInTheDocument();
  });

  it('esconde o formulário com o cadastro fechado, mesmo com token', async () => {
    parametros.busca = '?invite=tok123';
    politica.valor = {
      mode: 'closed', aceita_cadastro: false, exige_convite: false, primeiro_acesso: false,
    };
    renderizar();
    await screen.findByText('Cadastro fechado');
    expect(formularioNaTela()).not.toBeInTheDocument();
  });

  it('mostra o formulário com o cadastro aberto', async () => {
    politica.valor = {
      mode: 'open', aceita_cadastro: true, exige_convite: false, primeiro_acesso: false,
    };
    renderizar();
    expect(await screen.findByLabelText('Nome Completo')).toBeInTheDocument();
  });
});

describe('primeiro acesso do site', () => {
  it('deixa o SUPERADMIN_EMAIL se cadastrar num site que exige convite', async () => {
    // O caso que quebrava: deploy novo, modo `invite_only`, ninguém dentro.
    politica.valor = {
      mode: 'invite_only', aceita_cadastro: true, exige_convite: true, primeiro_acesso: true,
    };
    renderizar();

    // `findByText` do título e não do campo: enquanto a política não responde a
    // tela já mostra o formulário (é o recuo seguro), então esperar pelo campo
    // passaria mesmo se `primeiro_acesso` fosse ignorado.
    await screen.findByText('Primeiro acesso');
    expect(formularioNaTela()).toBeInTheDocument();
    expect(screen.getByText(/SUPERADMIN_EMAIL/)).toBeInTheDocument();
  });

  it('vale até com o cadastro fechado — como no servidor', async () => {
    // `_e_o_bootstrap` roda ANTES da checagem de modo, inclusive em `closed`.
    // Se a tela fosse mais restritiva que o backend, o `closed` viraria um jeito
    // de trancar o próprio dono do lado de fora.
    politica.valor = {
      mode: 'closed', aceita_cadastro: false, exige_convite: false, primeiro_acesso: true,
    };
    renderizar();
    expect(await screen.findByLabelText('Nome Completo')).toBeInTheDocument();
  });

  it('some assim que o site ganha um administrador', async () => {
    politica.valor = {
      mode: 'open', aceita_cadastro: true, exige_convite: false, primeiro_acesso: false,
    };
    renderizar();
    await screen.findByLabelText('Nome Completo');
    expect(screen.queryByText('Primeiro acesso')).not.toBeInTheDocument();
  });
});

describe('quando a política não responde', () => {
  it('mostra o formulário e deixa o servidor decidir no POST', async () => {
    politica.valor = null;
    renderizar();
    // Falha de rede não pode trancar a porta: o 403 do POST é a decisão que
    // vale, e ela vem com mensagem.
    await waitFor(() => expect(formularioNaTela()).toBeInTheDocument());
  });
});
