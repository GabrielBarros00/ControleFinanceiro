import * as React from 'react';
import { createPortal } from 'react-dom';
import { Bell, Check, Loader2, X, Mail } from 'lucide-react';
import { ActionLink } from '@/components/ui/action-link';
import { Button } from '@/components/ui/button';
import { useNotifications, type AppNotification } from '@/hooks/use-notifications';
import { useUIStore } from '@/stores';
import { toast } from '@/stores/toast';
import { getApiErrorMessage } from '@/lib/api-error';
import { parseApiDate } from '@/lib/date';
import { cn } from '@/lib/utils';

function quando(iso: string): string {
  const data = parseApiDate(iso);
  const minutos = Math.round((Date.now() - data.getTime()) / 60000);
  if (minutos < 1) return 'agora';
  if (minutos < 60) return `há ${minutos} min`;
  const horas = Math.round(minutos / 60);
  if (horas < 24) return `há ${horas}h`;
  return data.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' });
}

/**
 * Central de avisos do usuário.
 *
 * Nasceu com o convite que passou a exigir aceite: e-mail sozinho não bastava
 * (muita gente não lê), então o convite precisa gritar DENTRO do app. Por isso o
 * sino tem contador, o convite pendente aparece destacado e as duas ações —
 * aceitar e recusar — ficam à mão, sem precisar caçar link nenhum.
 */
export function NotificationCenter() {
  const [aberto, setAberto] = React.useState(false);
  const painelRef = React.useRef<HTMLDivElement>(null);
  const { setCurrentWorkspaceId } = useUIStore();
  const {
    notifications, unread, isLoading,
    markRead, markAllRead, acceptInvite, declineInvite, isResponding,
  } = useNotifications();

  // Fecha ao clicar fora / apertar Esc
  React.useEffect(() => {
    if (!aberto) return;
    const onClick = (e: MouseEvent) => {
      if (painelRef.current && !painelRef.current.contains(e.target as Node)) setAberto(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setAberto(false);
    };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [aberto]);

  const convitesPendentes = notifications.filter(
    (n) => n.type === 'workspace_invite' && !n.read_at && n.invite_token,
  );

  const responder = async (n: AppNotification, aceitar: boolean) => {
    if (!n.invite_token) return;
    try {
      if (aceitar) {
        const { workspace_id } = await acceptInvite(n.invite_token);
        setCurrentWorkspaceId(workspace_id);
        toast.success('Convite aceito', `Você agora faz parte de "${n.workspace_name}".`);
        setAberto(false);
      } else {
        await declineInvite(n.invite_token);
        toast.info('Convite recusado');
      }
    } catch (err) {
      toast.error(getApiErrorMessage(err, 'Não foi possível responder ao convite.'));
    }
  };

  return (
    <div className="relative" ref={painelRef}>
      <button
        type="button"
        onClick={() => setAberto((v) => !v)}
        aria-label={unread > 0 ? `Notificações (${unread} não lidas)` : 'Notificações'}
        aria-expanded={aberto}
        className={cn(
          'relative flex h-9 w-9 items-center justify-center rounded-lg transition-colors',
          'text-muted-foreground hover:bg-accent hover:text-foreground',
          unread > 0 && 'text-brand',
        )}
      >
        <Bell className={cn('h-5 w-5', unread > 0 && 'animate-in zoom-in-50')} />
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-semibold text-destructive-foreground ring-2 ring-background">
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </button>

      {aberto && (
        <div className="absolute right-0 z-50 mt-2 w-[min(92vw,22rem)] overflow-hidden rounded-xl border border-border bg-card shadow-2xl animate-in fade-in slide-in-from-top-1">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <p className="text-sm font-bold text-foreground">Notificações</p>
            {unread > 0 && (
              <ActionLink
                onClick={() => markAllRead()}
                className="text-xs font-semibold text-brand hover:underline"
              >
                Marcar todas como lidas
              </ActionLink>
            )}
          </div>

          <div className="max-h-[70vh] overflow-y-auto">
            {isLoading ? (
              <div className="flex justify-center py-8">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            ) : notifications.length === 0 ? (
              <p className="px-4 py-8 text-center text-sm text-muted-foreground">
                Nada por aqui. Você está em dia. ✅
              </p>
            ) : (
              notifications.map((n) => {
                const convite = n.type === 'workspace_invite' && !!n.invite_token && !n.read_at;
                return (
                  <div
                    key={n.id}
                    className={cn(
                      'border-b border-border/60 px-4 py-3 last:border-b-0',
                      !n.read_at && 'bg-brand/5',
                      convite && 'border-l-2 border-l-brand',
                    )}
                  >
                    <div className="flex items-start gap-2">
                      {!n.read_at && (
                        <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-brand" aria-hidden />
                      )}
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-semibold text-foreground">{n.title}</p>
                        {n.body && (
                          <p className="mt-0.5 text-xs text-muted-foreground">{n.body}</p>
                        )}
                        <p className="mt-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                          {quando(n.created_at)}
                        </p>

                        {convite ? (
                          <div className="mt-2 flex gap-2">
                            <Button
                              size="sm"
                              disabled={isResponding}
                              onClick={() => responder(n, true)}
                              className="h-8 gap-1.5 font-bold"
                            >
                              <Check className="h-3.5 w-3.5" /> Aceitar
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={isResponding}
                              onClick={() => responder(n, false)}
                              className="h-8 gap-1.5"
                            >
                              <X className="h-3.5 w-3.5" /> Recusar
                            </Button>
                          </div>
                        ) : (
                          !n.read_at && (
                            <ActionLink
                              onClick={() => markRead(n.id)}
                              className="mt-1.5 text-xs font-semibold text-brand hover:underline"
                            >
                              Marcar como lida
                            </ActionLink>
                          )
                        )}
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}

      {/*
        Faixa fixa quando há convite esperando: o sino sozinho é discreto demais
        para uma decisão que dá acesso às finanças de outra pessoa.

        POR QUE VAI PARA UM PORTAL, e não fica aqui dentro:

        `position: fixed` só resolve contra a viewport enquanto nenhum ancestral
        criar um containing block — e `backdrop-filter` cria. A barra superior do
        `AppShell` é `sticky ... backdrop-blur-sm`, e este componente mora dentro
        dela. O resultado é que `bottom: 5rem` resolvia contra a caixa de ~40px da
        própria barra, e a faixa era desenhada 5rem ACIMA dela: medida no celular,
        `topo=-70` numa tela de 727px de altura. Ou seja, o aviso que "precisa
        estar visível de qualquer tela" nunca esteve visível em tela nenhuma do
        celular — e nada avisa, porque o `fixed` continua sendo `fixed`, só que
        contra outra caixa.

        `createPortal` para o `body` põe a faixa fora do alcance de qualquer
        filtro da barra superior. O `z-40` continua abaixo dos diálogos (z-50) e
        empata com a barra inferior, que ela nunca cobre por causa do `bottom-20`.
      */}
      {convitesPendentes.length > 0 && !aberto && createPortal(
        <button
          type="button"
          onClick={() => setAberto(true)}
          className="fixed inset-x-3 bottom-20 z-40 flex items-center gap-2 rounded-xl border border-brand/40 bg-brand/10 px-4 py-3 text-left shadow-lg backdrop-blur-sm animate-in slide-in-from-bottom-2 md:inset-x-auto md:right-6 md:bottom-6 md:max-w-sm"
        >
          <Mail className="h-4 w-4 shrink-0 text-brand" />
          <span className="text-sm font-semibold text-foreground">
            {convitesPendentes.length === 1
              ? `Convite para "${convitesPendentes[0].workspace_name}" esperando resposta`
              : `${convitesPendentes.length} convites esperando resposta`}
          </span>
        </button>,
        document.body,
      )}
    </div>
  );
}
