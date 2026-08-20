import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Avatar } from '@/components/ui/avatar';
import { urlDoAvatar } from '@/lib/avatar';
import { baseURL } from '@/api/client';

/*
 * O avatar tinha sete implementações à mão e nenhuma sabia exibir imagem. Este
 * arquivo fixa as três decisões que decidem se a foto aparece ou não:
 *
 * 1. sem `avatar_version` não há foto — e a inicial NÃO pode sumir;
 * 2. a URL carrega o token de cache, senão a foto trocada continua a antiga;
 * 3. uma imagem que falha ao carregar volta para a inicial, em vez de deixar o
 *    ícone de imagem quebrada.
 */
describe('Avatar', () => {
  it('mostra a inicial quando não há foto', () => {
    render(<Avatar name="Gabriel" userId={7} version={null} title="Gabriel" />);
    expect(screen.getByTitle('Gabriel')).toHaveTextContent('G');
    expect(screen.queryByRole('img')).toBeNull();
  });

  it('mostra a foto quando há versão, com texto alternativo', () => {
    render(<Avatar name="Gabriel" userId={7} version="abc12345" />);
    const img = screen.getByRole('img', { name: 'Foto de Gabriel' });
    expect(img).toHaveAttribute('src', `${baseURL}/auth/users/7/avatar?v=abc12345`);
  });

  it('cai para a inicial se a imagem falhar', () => {
    const { container } = render(<Avatar name="Gabriel" userId={7} version="abc12345" />);
    const img = container.querySelector('img')!;
    // Volume fora do ar, sessão perdida: o `onError` é o que evita o ícone de
    // imagem quebrada no lugar do rosto.
    fireEvent.error(img);
    expect(container.querySelector('img')).toBeNull();
    expect(container.textContent).toBe('G');
  });

  it('usa duas letras quando pedido — "An" distingue Ana de André', () => {
    render(<Avatar name="André" version={null} letras={2} title="André" />);
    expect(screen.getByTitle('André')).toHaveTextContent('AN');
  });

  it('não quebra sem nome', () => {
    render(<Avatar name={undefined} version={null} title="sem nome" />);
    expect(screen.getByTitle('sem nome')).toHaveTextContent('?');
  });
});

describe('urlDoAvatar', () => {
  it('devolve null sem id ou sem versão — o `?v=` é o que faz o cache virar', () => {
    expect(urlDoAvatar(undefined, 'abc')).toBeNull();
    expect(urlDoAvatar(7, null)).toBeNull();
    expect(urlDoAvatar(7, undefined)).toBeNull();
  });

  it('escapa o token', () => {
    expect(urlDoAvatar(7, 'a b')).toBe(`${baseURL}/auth/users/7/avatar?v=a%20b`);
  });
});
