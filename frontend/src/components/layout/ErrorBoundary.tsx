import * as React from 'react';
import { AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';

/*
 * ErrorBoundary — a tela que aparece quando um pedaço da interface quebra.
 *
 * Antes dele não havia nenhum no app, e qualquer erro de renderização — em
 * especial a falha ao baixar o chunk de uma tela depois de um deploy — desmontava
 * a árvore inteira do React: `#root` vazio, tela branca, e no app instalado (sem
 * barra do navegador) nem o botão de recarregar do navegador à vista
 * (auditoria 2026-09-26, C6).
 *
 * `resetKey` limpa o erro quando muda: dentro do roteador ele recebe o caminho,
 * e voltar pelo botão do celular sai da tela de erro sem recarregar.
 */
interface ErrorBoundaryProps {
  children: React.ReactNode;
  resetKey?: string;
}

interface ErrorBoundaryState {
  erro: Error | null;
}

/**
 * Falha ao baixar código, e não defeito da tela: o chunk sumiu no deploy, veio
 * HTML no lugar do JS, ou a rede caiu no meio. Recarregar resolve — e dizer isso
 * é mais útil do que "algo deu errado".
 */
function falhaDeCarregamento(erro: Error): boolean {
  const texto = `${erro.name} ${erro.message}`;
  return /dynamically imported module|Importing a module script failed|module script|ChunkLoadError|Unable to preload/i.test(texto);
}

export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { erro: null };

  static getDerivedStateFromError(erro: Error): ErrorBoundaryState {
    return { erro };
  }

  componentDidUpdate(anteriores: ErrorBoundaryProps) {
    if (this.state.erro && anteriores.resetKey !== this.props.resetKey) {
      this.setState({ erro: null });
    }
  }

  render() {
    const { erro } = this.state;
    if (!erro) return this.props.children;

    const carregamento = falhaDeCarregamento(erro);
    return (
      <div role="alert" className="flex min-h-dvh items-center justify-center bg-background px-6 py-10 text-foreground">
        <div className="flex max-w-sm flex-col items-center gap-4 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10 text-destructive">
            <AlertTriangle className="h-6 w-6" />
          </div>
          <div className="space-y-2">
            <h1 className="text-lg font-semibold">
              {carregamento ? 'O app foi atualizado' : 'Esta tela não abriu'}
            </h1>
            <p className="text-sm text-muted-foreground">
              {carregamento
                ? 'Recarregue para usar a versão nova. Nada do que você já salvou se perdeu.'
                : 'Aconteceu um erro ao mostrar esta tela. Recarregar costuma resolver; se continuar, volte para o início.'}
            </p>
          </div>
          <div className="flex flex-wrap items-center justify-center gap-3">
            <Button onClick={() => window.location.reload()}>Recarregar</Button>
            {/* `<a>`, não `<Link>`: a tela de erro também existe FORA do
                roteador (a de último recurso, em volta do app inteiro), e um
                carregamento completo é justamente o que resolve. */}
            <a href="/overview" className="text-sm font-medium text-primary underline-offset-4 hover:underline">
              Ir para o início
            </a>
          </div>
        </div>
      </div>
    );
  }
}
