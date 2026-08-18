import { Home, User } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useWorkspaces } from '@/hooks/use-workspaces';
import { useWorkspaceId } from '@/hooks/use-workspace-id';

/*
 * ScopeBadge — "isto é seu" ou "isto é do espaço X", ao lado do título.
 *
 * O app tem pares de telas quase homônimos que só se distinguiam por um pronome
 * possessivo: "Acertos" × "Seus acertos", "Relatórios" × "Seus relatórios",
 * "Configurações" × "Suas configurações", "Painel" × "Seu mês". Num scan
 * visual — que é como se lê no celular — o possessivo some, e a pessoa não sabe
 * se o número na tela soma todos os espaços ou só este.
 *
 * A informação existia, mas em prosa: subtítulos como "Com quem você se acerta,
 * somando todas as casas. Os saldos nunca se compensam entre elas." ocupam três
 * linhas em 390px e ninguém lê duas vezes. A pílula responde em um relance e o
 * subtítulo continua ali para quem quiser o porquê.
 */
export function ScopeBadge({
  scope,
  className,
}: {
  scope: 'personal' | 'workspace';
  className?: string;
}) {
  const workspaceId = useWorkspaceId();
  const { workspaces } = useWorkspaces();
  const nome = workspaces.find((w) => w.id === workspaceId)?.name;

  const pessoal = scope === 'personal';
  const Icone = pessoal ? User : Home;
  const texto = pessoal ? 'Pessoal' : (nome ?? 'Espaço');

  return (
    <span
      className={cn(
        'inline-flex max-w-full items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium',
        pessoal
          ? 'border-brand-border bg-brand-subtle text-brand'
          : 'border-border bg-muted text-muted-foreground',
        className,
      )}
      title={pessoal ? 'Somando todos os seus espaços — só você vê' : 'Somente este espaço'}
    >
      <Icone className="h-3 w-3 shrink-0" aria-hidden />
      <span className="truncate">{texto}</span>
    </span>
  );
}
