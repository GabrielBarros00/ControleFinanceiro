import * as React from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Loader2, Users, AlertCircle } from 'lucide-react';
import { apiClient } from '@/api/client';
import { getApiErrorMessage } from '@/lib/api-error';
import { useUIStore } from '@/stores';
import { useQueryClient } from '@tanstack/react-query';

export function InviteAcceptPage() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { setCurrentWorkspaceId } = useUIStore();
  const [accepting, setAccepting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const infoQuery = useQuery({
    queryKey: ['invite-info', token],
    queryFn: async () => {
      const response = await apiClient.get(`/invites/info/${token}`);
      return response.data as {
        workspace_name: string;
        role: string;
        invited_by: string | null;
        valid: boolean;
        reason: string | null;
      };
    },
    enabled: !!token,
    retry: false,
  });

  const accept = async () => {
    setAccepting(true);
    setError(null);
    try {
      const response = await apiClient.post(`/invites/accept/${token}`);
      const workspaceId = response.data.workspace_id as number;
      setCurrentWorkspaceId(workspaceId);
      queryClient.invalidateQueries();
      // Direto para o workspace que acabou de aceitar (ADR 0020) — antes ia para
      // `/`, que dependia do estado guardado e podia abrir na casa errada.
      navigate(`/w/${workspaceId}`);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Erro ao aceitar o convite.'));
    } finally {
      setAccepting(false);
    }
  };

  const info = infoQuery.data;

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md bg-card/50 backdrop-blur-xl border-border shadow-2xl animate-in zoom-in-95 duration-500">
        <CardHeader className="space-y-2 text-center pt-8">
          <div className="mx-auto w-12 h-12 bg-primary/10 rounded-xl flex items-center justify-center shadow-lg mb-4 text-primary">
            <Users className="h-6 w-6" />
          </div>
          <CardTitle className="text-2xl font-bold tracking-tight text-foreground">
            Convite para Workspace
          </CardTitle>
          {info && (
            <CardDescription className="text-muted-foreground">
              {info.invited_by ? `${info.invited_by} convidou você` : 'Você foi convidado(a)'} para participar de{' '}
              <span className="font-bold text-foreground">"{info.workspace_name}"</span>.
            </CardDescription>
          )}
        </CardHeader>
        <CardContent className="pb-8 space-y-4">
          {infoQuery.isLoading ? (
            <div className="flex justify-center py-6">
              <Loader2 className="h-6 w-6 animate-spin text-primary" />
            </div>
          ) : infoQuery.isError ? (
            <div className="p-3 rounded-lg bg-destructive/10 border border-destructive/20 flex items-center gap-3 text-destructive text-sm font-medium">
              <AlertCircle className="h-4 w-4 shrink-0" />
              Convite não encontrado ou inválido.
            </div>
          ) : info && !info.valid ? (
            <div className="p-3 rounded-lg bg-destructive/10 border border-destructive/20 flex items-center gap-3 text-destructive text-sm font-medium">
              <AlertCircle className="h-4 w-4 shrink-0" />
              {info.reason ?? 'Este convite não é mais válido.'}
            </div>
          ) : (
            <>
              {error && (
                <div className="p-3 rounded-lg bg-destructive/10 border border-destructive/20 flex items-center gap-3 text-destructive text-sm font-medium">
                  <AlertCircle className="h-4 w-4 shrink-0" />
                  {error}
                </div>
              )}
              <Button
                onClick={accept}
                disabled={accepting}
                className="w-full h-11 bg-primary hover:bg-primary/90 text-primary-foreground font-bold shadow-lg shadow-primary/20"
              >
                {accepting ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Aceitar Convite'}
              </Button>
            </>
          )}
          <Button variant="ghost" className="w-full" onClick={() => navigate('/')}>
            Voltar ao Início
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
