import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import type { components } from '@/types/api.gen';

/**
 * Integração com agentes de IA (ADR 0035) — o lado do APP.
 *
 * O agente fala com `/mcp` usando um token OAuth; esta tela é onde a pessoa vê
 * o endereço para conectar, as conexões que autorizou e o que elas fizeram, e
 * onde desconecta. Nenhum token passa por aqui: o app nunca mostra nem guarda
 * credencial de agente no navegador.
 */
export type AiIntegrations = components['schemas']['AiIntegrationsRead'];
export type AiConnection = components['schemas']['AiConnectionRead'];
export type AiActivity = components['schemas']['AiActivityRead'];
export type AiScope = components['schemas']['AiScopeRead'];

export function useAiIntegrations() {
  const query = useQuery({
    queryKey: ['ai-integrations'],
    queryFn: async (): Promise<AiIntegrations> => (await apiClient.get('/me/ai-integrations')).data,
  });
  return {
    data: query.data,
    isLoading: query.isLoading,
    isError: query.isError,
    refetch: query.refetch,
  };
}

export function useAiActivity(limit = 20) {
  const query = useQuery({
    queryKey: ['ai-integrations', 'activity', limit],
    queryFn: async (): Promise<AiActivity[]> =>
      (await apiClient.get('/me/ai-integrations/activity', { params: { limit } })).data,
  });
  return { activity: query.data ?? [], isLoading: query.isLoading, isError: query.isError };
}

export function useDisconnectAi() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (grantId: number) => {
      await apiClient.delete(`/me/ai-integrations/connections/${grantId}`);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['ai-integrations'] }),
  });
}

// --- Consentimento OAuth ------------------------------------------------------

export type ConsentRequest = components['schemas']['ConsentRequestRead'];

export function useConsentRequest(request: string | null) {
  const query = useQuery({
    queryKey: ['oauth-consent', request],
    queryFn: async (): Promise<ConsentRequest> =>
      (await apiClient.get('/oauth/consent', { params: { request } })).data,
    enabled: !!request,
    // O pedido é assinado e vence em minutos: nada a ganhar refazendo a leitura.
    staleTime: Infinity,
    retry: false,
  });
  return { consent: query.data, isLoading: query.isLoading, isError: query.isError, error: query.error };
}

export function useConsentDecision() {
  return useMutation({
    mutationFn: async (
      args: { request: string; approve: true; scopes: string[] } | { request: string; approve: false },
    ): Promise<string> => {
      const res = args.approve
        ? await apiClient.post('/oauth/consent/approve', { request: args.request, scopes: args.scopes })
        : await apiClient.post('/oauth/consent/deny', { request: args.request });
      return (res.data as components['schemas']['ConsentDecisionRead']).redirect_to;
    },
  });
}
