import * as React from 'react';
import { Bot, Check, Copy, ExternalLink, Link2Off, PlugZap, ShieldCheck, Terminal } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorState } from '@/components/ui/error-state';
import { EmptyState } from '@/components/ui/empty-state';
import { StatusPill } from '@/components/ui/status-pill';
import { useConfirm } from '@/components/ui/confirm';
import { copiarTexto } from '@/lib/clipboard';
import { parseApiDate } from '@/lib/date';
import { getApiErrorMessage } from '@/lib/api-error';
import { toast } from '@/stores/toast';
import {
  useAiActivity,
  useAiIntegrations,
  useDisconnectAi,
  type AiConnection,
  type AiScope,
} from '@/hooks/use-ai-integrations';
import { VERIFICADO_EM, clientGuides, connectionProfile, type ClientGuide } from './client-guides';

function quando(valor?: string | null): string {
  if (!valor) return 'nunca';
  return parseApiDate(valor).toLocaleString('pt-BR', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

/**
 * Copiar com os três estados que a pessoa precisa ver: parado, copiando e
 * copiado. O "copiando" vem do próprio `Button` (onClick que devolve promessa);
 * o "copiado" fica 2 s e volta, para o mesmo botão poder ser usado de novo.
 */
export function CopyButton({ text, label, what }: { text: string; label: string; what: string }) {
  const [copiado, setCopiado] = React.useState(false);
  React.useEffect(() => {
    if (!copiado) return;
    const t = window.setTimeout(() => setCopiado(false), 2000);
    return () => window.clearTimeout(t);
  }, [copiado]);
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className="gap-1.5"
      aria-label={`${label}: ${what}`}
      onClick={async () => {
        const ok = await copiarTexto(text);
        if (ok) {
          setCopiado(true);
          toast.success(`${what} copiado.`);
        } else {
          toast.error('Não foi possível copiar. Selecione o texto e copie manualmente.');
        }
      }}
    >
      {copiado ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : <Copy className="h-3.5 w-3.5" aria-hidden="true" />}
      {copiado ? 'Copiado' : label}
    </Button>
  );
}

function CodeBlock({ code, label }: { code: string; label: string }) {
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
        <CopyButton text={code} label="Copiar" what={label} />
      </div>
      <pre className="max-w-full overflow-x-auto rounded-lg border border-border bg-muted/50 p-3 text-xs leading-relaxed">
        <code className="whitespace-pre">{code}</code>
      </pre>
    </div>
  );
}

function GuideView({ guide }: { guide: ClientGuide }) {
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">{guide.requirements}</p>
      {guide.warning && (
        <p className="rounded-lg border border-warning/30 bg-warning-subtle px-3 py-2 text-sm text-foreground">{guide.warning}</p>
      )}
      <ol className="list-decimal space-y-1.5 pl-5 text-sm text-foreground">
        {guide.steps.map((passo) => <li key={passo}>{passo}</li>)}
      </ol>
      {guide.commands.map((c) => <CodeBlock key={c.label} code={c.code} label={c.label} />)}
      <p className="flex items-start gap-2 text-sm text-muted-foreground">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-income" aria-hidden="true" />
        <span>{guide.auth}</span>
      </p>
      <p className="text-xs text-muted-foreground">
        Documentação oficial:{' '}
        <a href={guide.docsUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-primary underline-offset-4 hover:underline">
          {guide.docsLabel} <ExternalLink className="h-3 w-3" aria-hidden="true" />
        </a>
        {' · '}verificado em {VERIFICADO_EM}. Menus e planos desses produtos mudam — na dúvida, vale o link.
      </p>
    </div>
  );
}

function ConnectionRow({ c, scopes }: { c: AiConnection; scopes: AiScope[] }) {
  const confirm = useConfirm();
  const desconectar = useDisconnectAi();
  const rotulo = (s: string) => scopes.find((x) => x.scope === s)?.label ?? s;
  const ativa = c.status === 'active';
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0 space-y-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-foreground">{c.client_name}</span>
          <StatusPill tone={ativa ? 'success' : 'warning'}>{ativa ? 'Ativa' : 'Autorização expirada'}</StatusPill>
        </div>
        {(c.redirect_host || c.client_host) && (
          <p className="truncate text-xs text-muted-foreground">{c.client_host ?? c.redirect_host}</p>
        )}
        <div className="flex flex-wrap gap-1.5">
          {c.scopes.map((s) => (
            <span key={s} className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">{rotulo(s)}</span>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">
          Conectado em {quando(c.created_at)} · último uso {quando(c.last_used_at)}
        </p>
        {!ativa && (
          <p className="text-xs text-muted-foreground">
            O acesso venceu. Reconecte pelo próprio agente para voltar a usar.
          </p>
        )}
      </div>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="shrink-0 gap-1.5 text-destructive hover:bg-destructive/10"
        onClick={async () => {
          const ok = await confirm({
            title: `Desconectar ${c.client_name}?`,
            description: 'O agente perde o acesso na hora. Para usar de novo, será preciso conectar e autorizar outra vez.',
            confirmLabel: 'Desconectar',
            destructive: true,
          });
          if (!ok) return;
          try {
            await desconectar.mutateAsync(c.grant_id);
            toast.success(`${c.client_name} desconectado.`);
          } catch (err) {
            toast.error(getApiErrorMessage(err));
          }
        }}
      >
        <Link2Off className="h-3.5 w-3.5" aria-hidden="true" /> Desconectar
      </Button>
    </div>
  );
}

function RecentActivity() {
  const { activity, isLoading, isError } = useAiActivity(20);
  if (isLoading) return <Skeleton className="h-24 rounded-xl" />;
  if (isError) return <p className="text-sm text-muted-foreground">Não foi possível carregar a atividade recente.</p>;
  if (activity.length === 0) {
    return <p className="text-sm text-muted-foreground">Nenhuma ação de agente ainda.</p>;
  }
  return (
    <ul className="divide-y divide-border rounded-xl border border-border">
      {activity.map((a) => (
        <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 text-sm">
          <div className="min-w-0">
            <span className="font-medium text-foreground">{a.title}</span>
            <span className="ml-2 text-xs text-muted-foreground">{a.client_name ?? 'agente'} · {quando(a.created_at)}</span>
          </div>
          <div className="flex items-center gap-1.5">
            {a.replayed && <StatusPill tone="neutral">repetição</StatusPill>}
            {a.outcome === 'ok'
              ? <StatusPill tone={a.kind === 'read' ? 'neutral' : 'brand'}>{a.kind === 'read' ? 'consulta' : 'alteração'}</StatusPill>
              : <StatusPill tone="danger">{a.error_code ?? 'erro'}</StatusPill>}
          </div>
        </li>
      ))}
    </ul>
  );
}

/**
 * Aba "Integrações com IA" (ADR 0035): conectar ChatGPT, Claude, Codex, Gemini
 * CLI, Antigravity ou qualquer cliente MCP a esta conta, ver e revogar conexões.
 */
export function AiIntegrationsTab() {
  const { data, isLoading, isError, refetch } = useAiIntegrations();

  if (isLoading) {
    return (
      <div className="space-y-4" aria-busy="true">
        <Skeleton className="h-40 rounded-xl" />
        <Skeleton className="h-64 rounded-xl" />
      </div>
    );
  }
  if (isError || !data) {
    return (
      <ErrorState
        title="Não foi possível carregar as integrações"
        message="Tente de novo em instantes."
        onRetry={() => refetch()}
      />
    );
  }

  const guias = clientGuides(data.mcp_url);
  const perfil = connectionProfile({
    mcpUrl: data.mcp_url,
    serverName: data.server_name,
    serverVersion: data.server_version,
    scopes: data.scopes.map((s) => s.scope),
  });

  return (
    <div className="space-y-6">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-semibold text-foreground">
          <Bot className="h-5 w-5 text-primary" aria-hidden="true" /> Integrações com IA
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Conecte o ChatGPT, o Claude ou outro agente de IA à sua conta para consultar gastos e registrar
          lançamentos conversando. O agente age com as SUAS permissões e só com o que você autorizar.
        </p>
      </div>

      {!data.enabled ? (
        <Card className="border-border">
          <CardContent className="py-6">
            <EmptyState
              icon={PlugZap}
              title="Integração desativada"
              description="O administrador deste site desligou a conexão de agentes de IA. Conexões existentes não funcionam enquanto isso."
            />
          </CardContent>
        </Card>
      ) : (
        <Card className="border-border">
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center gap-2 text-base">
              Status <StatusPill tone="success">Disponível</StatusPill>
            </CardTitle>
            <CardDescription>Use este endereço no seu agente. Não há senha nem token para copiar: a autorização é feita aqui no app.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <span className="text-xs font-medium text-muted-foreground">Endpoint MCP</span>
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <code className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap rounded-lg border border-border bg-muted/50 px-3 py-2 text-sm">
                  {data.mcp_url}
                </code>
                <CopyButton text={data.mcp_url} label="Copiar URL" what="Endereço" />
              </div>
            </div>
            <dl className="grid gap-3 text-sm sm:grid-cols-2">
              <div><dt className="text-xs text-muted-foreground">Transporte</dt><dd className="text-foreground">Streamable HTTP</dd></div>
              <div><dt className="text-xs text-muted-foreground">Autenticação</dt><dd className="text-foreground">OAuth 2.1 com PKCE</dd></div>
              <div className="min-w-0"><dt className="text-xs text-muted-foreground">Conta</dt><dd className="truncate text-foreground">{data.account.name} · {data.account.email}</dd></div>
              <div><dt className="text-xs text-muted-foreground">Última utilização</dt><dd className="text-foreground">{quando(data.last_used_at)}</dd></div>
              <div><dt className="text-xs text-muted-foreground">Servidor</dt><dd className="text-foreground">{data.server_name} {data.server_version}</dd></div>
              <div><dt className="text-xs text-muted-foreground">Ambiente</dt><dd className="text-foreground">{data.environment}</dd></div>
            </dl>
          </CardContent>
        </Card>
      )}

      <Card className="border-border">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base"><Terminal className="h-4 w-4" aria-hidden="true" /> Como conectar</CardTitle>
          <CardDescription>Escolha o seu agente. Os comandos já vêm com o endereço desta conta.</CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="chatgpt">
            <TabsList aria-label="Agentes de IA">
              {guias.map((g) => <TabsTrigger key={g.id} value={g.id}>{g.name}</TabsTrigger>)}
            </TabsList>
            {guias.map((g) => (
              <TabsContent key={g.id} value={g.id} className="pt-2">
                <GuideView guide={g} />
              </TabsContent>
            ))}
          </Tabs>
        </CardContent>
      </Card>

      <Card className="border-border">
        <CardHeader>
          <CardTitle className="text-base">Perfil de conexão</CardTitle>
          <CardDescription>Para clientes MCP que pedem a configuração completa. Não contém nenhuma credencial.</CardDescription>
        </CardHeader>
        <CardContent>
          <CodeBlock code={perfil} label="Configuração" />
        </CardContent>
      </Card>

      <Card className="border-border">
        <CardHeader>
          <CardTitle className="text-base">Conexões autorizadas</CardTitle>
          <CardDescription>Cada agente que você autorizou, com o que ele pode fazer.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {data.connections.length === 0 ? (
            <EmptyState
              icon={PlugZap}
              title="Nenhum agente conectado"
              description="Quando você autorizar um agente, ele aparece aqui — e daqui dá para desconectá-lo a qualquer momento."
            />
          ) : (
            data.connections.map((c) => <ConnectionRow key={c.grant_id} c={c} scopes={data.scopes} />)
          )}
        </CardContent>
      </Card>

      <Card className="border-border">
        <CardHeader>
          <CardTitle className="text-base">Atividade recente</CardTitle>
          <CardDescription>O que os agentes fizeram na sua conta. O detalhe de cada mudança fica na auditoria do espaço, marcado "via IA".</CardDescription>
        </CardHeader>
        <CardContent><RecentActivity /></CardContent>
      </Card>

      <Card className="border-border">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base"><ShieldCheck className="h-4 w-4" aria-hidden="true" /> Privacidade e controle</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p>O agente vê só o que você vê no app, nas permissões que você marcou ao autorizar. O que ele lê vai para o provedor do agente (OpenAI, Anthropic, Google…), sob a política de privacidade dele.</p>
          <p>Nada é apagado ou alterado em massa sem uma prévia que você confirma. Toda ação fica registrada, e desconectar corta o acesso na hora.</p>
          <p>Trocar a senha ou encerrar suas sessões também desconecta todos os agentes.</p>
        </CardContent>
      </Card>
    </div>
  );
}
