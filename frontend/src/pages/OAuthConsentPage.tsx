import * as React from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { AlertTriangle, Bot, Loader2, ShieldCheck, Terminal } from 'lucide-react';
import { AuthShell } from '@/components/auth/AuthShell';
import { Card, CardContent, CardDescription, CardFooter, CardHeader } from '@/components/ui/card';
import { Button, buttonVariants } from '@/components/ui/button';
import { useAuth } from '@/hooks/use-auth';
import { useConsentDecision, useConsentRequest } from '@/hooks/use-ai-integrations';
import { getApiErrorMessage } from '@/lib/api-error';
import { toast } from '@/stores/toast';

/** Mensagens para os erros que o `/oauth/authorize` manda para cá (os que NÃO
 *  podem voltar ao cliente, porque o próprio redirect é suspeito). */
const ERROS: Record<string, string> = {
  invalid_client: 'O aplicativo que pediu acesso não foi reconhecido.',
  invalid_request: 'O pedido de conexão veio incompleto ou inválido.',
  unauthorized_client: 'Este aplicativo não pode pedir acesso desta forma.',
  access_denied: 'O acesso foi negado.',
  server_error: 'O servidor não conseguiu processar o pedido de conexão.',
};

function Erro({ titulo, texto }: { titulo: string; texto: string }) {
  return (
    <Card className="border-border shadow-xl">
      <CardHeader>
        <h1 className="flex items-center gap-2 font-heading text-lg font-medium leading-snug">
          <AlertTriangle className="h-5 w-5 text-warning" aria-hidden="true" /> {titulo}
        </h1>
        <CardDescription>{texto}</CardDescription>
      </CardHeader>
      <CardFooter className="flex flex-wrap gap-2">
        <Link to="/me/settings?tab=ai" className={buttonVariants({ variant: 'outline' })}>Integrações com IA</Link>
        <Link to="/overview" className={buttonVariants({ variant: 'ghost' })}>Voltar ao app</Link>
      </CardFooter>
    </Card>
  );
}

/**
 * Consentimento OAuth de um agente de IA (ADR 0035).
 *
 * Chega-se aqui pelo `/api/v1/oauth/authorize`, que valida o pedido e o assina
 * num `request` de 10 minutos. A página é protegida (`ProtectedRoute`): sem
 * sessão, a pessoa faz login — com senha ou Google — e VOLTA para cá.
 *
 * O que a tela precisa deixar impossível de ignorar: QUAL conta está sendo
 * ligada, PARA ONDE o acesso vai (o host do redirect, não só o nome que o
 * aplicativo diz ter) e O QUE ele poderá fazer. Nome de aplicativo é texto
 * escolhido por quem se registrou; por isso o host vem em destaque.
 */
export function OAuthConsentPage() {
  const [params] = useSearchParams();
  const pedido = params.get('request');
  const erro = params.get('error');
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { consent, isLoading, isError, error } = useConsentRequest(erro ? null : pedido);
  const decidir = useConsentDecision();
  const [marcados, setMarcados] = React.useState<Set<string> | null>(null);
  const [saindo, setSaindo] = React.useState(false);

  React.useEffect(() => {
    if (consent && marcados === null) {
      setMarcados(new Set(consent.scopes.map((s) => s.scope)));
    }
  }, [consent, marcados]);

  const decidirE = async (aprovar: boolean) => {
    if (!pedido) return;
    try {
      const destino = aprovar
        ? await decidir.mutateAsync({ request: pedido, approve: true, scopes: [...(marcados ?? [])] })
        : await decidir.mutateAsync({ request: pedido, approve: false });
      setSaindo(true);
      // Navegação de verdade (e não do router): o destino é o aplicativo que
      // pediu acesso — outro site, ou o `localhost` de um agente de terminal.
      window.location.assign(destino);
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  };

  const trocarDeConta = async () => {
    const aqui = `/oauth/consent?${params.toString()}`;
    await logout();
    navigate('/login', { replace: true, state: { from: aqui } });
  };

  let corpo: React.ReactNode;
  if (erro) {
    corpo = (
      <Erro
        titulo="Não foi possível conectar"
        texto={`${ERROS[erro] ?? 'O pedido de conexão foi recusado.'} Volte ao agente de IA e tente conectar de novo.`}
      />
    );
  } else if (!pedido) {
    corpo = <Erro titulo="Pedido de conexão ausente" texto="Abra esta página a partir do agente de IA que você quer conectar." />;
  } else if (isLoading) {
    corpo = (
      <div className="flex min-h-64 items-center justify-center" aria-busy="true">
        <Loader2 className="h-8 w-8 animate-spin text-primary" aria-label="Carregando o pedido" />
      </div>
    );
  } else if (isError || !consent) {
    corpo = (
      <Erro
        titulo="Pedido expirado ou inválido"
        texto={`${getApiErrorMessage(error, 'Este pedido de conexão não vale mais.')} Os pedidos valem 10 minutos — volte ao agente e conecte de novo.`}
      />
    );
  } else if (saindo) {
    corpo = (
      <div className="flex min-h-64 flex-col items-center justify-center gap-3 text-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" aria-hidden="true" />
        <p className="text-sm text-muted-foreground">Voltando para {consent.client.name}…</p>
      </div>
    );
  } else {
    const { client, account, scopes } = consent;
    corpo = (
      <Card className="border-border shadow-xl">
        <CardHeader className="space-y-3">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10">
            <Bot className="h-6 w-6 text-primary" aria-hidden="true" />
          </div>
          {/* h1 e não CardTitle (div): é o título da página inteira, e leitor de tela
              precisa achá-lo como tal — é a decisão que a pessoa está tomando. */}
          <h1 className="text-center font-heading text-xl font-medium leading-snug">Autorizar “{client.name}”?</h1>
          <CardDescription className="text-center">
            Um agente de IA quer acessar o seu Controle Financeiro. O nome acima é o que o próprio aplicativo informou.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="rounded-lg border border-border bg-muted/40 p-3 text-sm">
            <p className="text-xs text-muted-foreground">O acesso será entregue a</p>
            <p className="break-all font-semibold text-foreground">{client.redirect_host}</p>
            {client.client_host && client.client_host !== client.redirect_host && (
              <p className="mt-1 break-all text-xs text-muted-foreground">Aplicativo registrado em {client.client_host}</p>
            )}
          </div>

          {client.loopback_only && (
            <div className="flex gap-2 rounded-lg border border-warning/30 bg-warning-subtle p-3 text-sm text-foreground" role="note">
              <Terminal className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <span>
                Este aplicativo roda no seu computador (um agente de terminal, como Claude Code, Codex ou Gemini CLI).
                Só autorize se foi <strong>você</strong> quem acabou de iniciar a conexão.
              </span>
            </div>
          )}

          <div className="text-sm">
            <p className="text-xs text-muted-foreground">Conta</p>
            <p className="text-foreground">
              <span className="font-medium">{account.name}</span> · {account.email}
            </p>
            {user && (
              <button type="button" onClick={trocarDeConta} className="mt-1 text-xs text-primary underline-offset-4 hover:underline">
                Não é você? Entrar com outra conta
              </button>
            )}
          </div>

          <fieldset className="space-y-2">
            <legend className="mb-1 text-sm font-medium text-foreground">O que o agente poderá fazer</legend>
            {scopes.map((s) => {
              const id = `escopo-${s.scope}`;
              const marcado = s.required || (marcados?.has(s.scope) ?? true);
              return (
                <label key={s.scope} htmlFor={id} className="flex cursor-pointer items-start gap-3 rounded-lg border border-border p-3">
                  <input
                    id={id}
                    type="checkbox"
                    className="mt-0.5 h-5 w-5 shrink-0 rounded border-border accent-primary"
                    checked={marcado}
                    disabled={s.required}
                    onChange={(e) => {
                      setMarcados((atual) => {
                        const novo = new Set(atual ?? []);
                        if (e.target.checked) novo.add(s.scope);
                        else novo.delete(s.scope);
                        return novo;
                      });
                    }}
                  />
                  <span className="min-w-0">
                    <span className="block text-sm font-medium text-foreground">
                      {s.label}{s.required && <span className="ml-1 text-xs font-normal text-muted-foreground">(obrigatório)</span>}
                    </span>
                    <span className="block text-xs text-muted-foreground">{s.description}</span>
                  </span>
                </label>
              );
            })}
          </fieldset>

          <p className="flex items-start gap-2 text-xs text-muted-foreground">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-income" aria-hidden="true" />
            <span>
              O agente age com as suas permissões em cada espaço. Exclusões em massa sempre pedem uma prévia confirmada.
              Você pode desconectar a qualquer momento em Configurações › Integrações com IA.
            </span>
          </p>
        </CardContent>
        <CardFooter className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="outline" className="w-full sm:w-auto" onClick={() => decidirE(false)}>
            Negar
          </Button>
          <Button type="button" className="w-full sm:w-auto" onClick={() => decidirE(true)}>
            Autorizar
          </Button>
        </CardFooter>
      </Card>
    );
  }

  return <AuthShell>{corpo}</AuthShell>;
}
