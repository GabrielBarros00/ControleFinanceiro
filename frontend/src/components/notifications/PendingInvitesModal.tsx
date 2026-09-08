import * as React from 'react';
import { Check, Loader2, Mail, X } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/hooks/use-auth';
import { useNotifications, type AppNotification } from '@/hooks/use-notifications';
import { useUIStore } from '@/stores';
import { toast } from '@/stores/toast';
import { getApiErrorMessage } from '@/lib/api-error';

/**
 * Convite esperando resposta, apresentado como MODAL logo depois do onboarding.
 *
 * Desde que o convite passou a exigir aceite explícito, quem se cadastra por
 * fora do link (ou entra com o Google, que não devolve o token) chega ao app
 * sem estar no workspace — e o convite fica no sino, que é justamente o que
 * ninguém olha no primeiro minuto de uso. O resultado era a pessoa achar que o
 * convite não funcionou.
 *
 * Só aparece quando o onboarding JÁ terminou (`needs_onboarding === false`),
 * para não empilhar dois modais em cima do usuário novo. Como o onboarding
 * termina com um reload, na prática ele é a primeira coisa que se vê depois.
 *
 * "Depois" fecha e não volta nesta sessão: o sino e a faixa continuam ali. Uma
 * decisão que dá acesso às finanças de outra família merece ser oferecida uma
 * vez com clareza, não repetida a cada navegação.
 *
 * Construído sobre o `Dialog` (Radix) como todo modal do app: era um `<div>` com
 * `role="dialog"` na mão, sem focus trap, sem `Esc` e sem devolver o foco — e é
 * o PRIMEIRO modal que o usuário novo encontra, decidindo acesso a dados de
 * terceiros. Navegar por teclado aqui não é opcional.
 */
export function PendingInvitesModal() {
  const { user } = useAuth();
  const { setCurrentWorkspaceId } = useUIStore();
  const { notifications, acceptInvite, declineInvite, isResponding } = useNotifications();
  const [dispensado, setDispensado] = React.useState(false);

  const pendentes = notifications.filter(
    (n) => n.type === 'workspace_invite' && !n.read_at && n.invite_token,
  );

  const responder = async (n: AppNotification, aceitar: boolean) => {
    if (!n.invite_token) return;
    try {
      if (aceitar) {
        const { workspace_id } = await acceptInvite(n.invite_token);
        setCurrentWorkspaceId(workspace_id);
        toast.success('Convite aceito', `Você agora faz parte de "${n.workspace_name}".`);
      } else {
        await declineInvite(n.invite_token);
        toast.info('Convite recusado');
      }
    } catch (err) {
      toast.error(getApiErrorMessage(err, 'Não foi possível responder ao convite.'));
    }
  };

  // `needs_onboarding` pode vir indefinido em contas antigas: só o `true`
  // explícito segura o modal (senão ele nunca apareceria para elas).
  const aberto =
    !!user && user.needs_onboarding !== true && !dispensado && pendentes.length > 0;
  const varios = pendentes.length > 1;

  return (
    <Dialog open={aberto} onOpenChange={(next) => !next && setDispensado(true)}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader className="items-center pl-10 text-center sm:text-center">
          <div className="mb-2 flex h-16 w-16 items-center justify-center rounded-2xl bg-brand/10">
            <Mail className="h-8 w-8 text-brand" />
          </div>
          <DialogTitle className="text-2xl font-bold tracking-tight">
            {varios ? `Você tem ${pendentes.length} convites` : 'Você foi convidado'}
          </DialogTitle>
          <DialogDescription>
            Aceitar dá acesso aos lançamentos e às dívidas desse espaço — e deixa
            seus lançamentos nele visíveis para os outros membros.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          {pendentes.map((n) => (
            <div key={n.id} className="rounded-xl border border-border bg-background/50 p-4">
              <p className="text-sm font-semibold text-foreground">{n.title}</p>
              {n.body && <p className="mt-1 text-xs text-muted-foreground">{n.body}</p>}
              <div className="mt-3 flex gap-2">
                <Button
                  size="sm"
                  disabled={isResponding}
                  onClick={() => responder(n, true)}
                  className="h-9 flex-1 gap-1.5 font-bold"
                >
                  {isResponding ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Check className="h-3.5 w-3.5" />
                  )}
                  Aceitar
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={isResponding}
                  onClick={() => responder(n, false)}
                  className="h-9 gap-1.5"
                >
                  <X className="h-3.5 w-3.5" /> Recusar
                </Button>
              </div>
            </div>
          ))}

          <Button
            variant="link"
            onClick={() => setDispensado(true)}
            className="w-full text-xs text-muted-foreground"
          >
            Decidir depois
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
