import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import type { components } from '@/types/api.gen';
import { useWorkspaceId } from './use-workspace-id';

/**
 * Estabelecimentos do espaço (ADR 0038): onde a despesa foi feita.
 *
 * Os apelidos são as grafias do extrato; o servidor os normaliza (sem acento,
 * caixa, dígito ou pontuação), e o lançamento cujo título bate EXATAMENTE com um
 * deles se liga sozinho ao estabelecimento.
 */
export type Merchant = components['schemas']['MerchantRead'];
export type MerchantSpending = components['schemas']['MerchantSpendingRead'];
type MerchantCreate = components['schemas']['MerchantCreate'];
type MerchantUpdate = components['schemas']['MerchantUpdate'];

export function useMerchants() {
  const queryClient = useQueryClient();
  const ws = useWorkspaceId();

  const listQuery = useQuery({
    queryKey: ['merchants', ws],
    queryFn: async (): Promise<Merchant[]> => (await apiClient.get(`/workspaces/${ws}/merchants`)).data,
    enabled: !!ws,
  });

  // Mexer num estabelecimento muda o que os lançamentos mostram (nome, vínculo).
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['merchants', ws] });
    queryClient.invalidateQueries({ queryKey: ['transactions', ws] });
  };

  const create = useMutation({
    mutationFn: async (data: MerchantCreate) => (await apiClient.post(`/workspaces/${ws}/merchants`, data)).data as Merchant,
    onSuccess: invalidate,
  });
  const update = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: MerchantUpdate }) =>
      (await apiClient.put(`/workspaces/${ws}/merchants/${id}`, data)).data as Merchant,
    onSuccess: invalidate,
  });
  const merge = useMutation({
    mutationFn: async ({ id, intoId }: { id: number; intoId: number }) =>
      (await apiClient.post(`/workspaces/${ws}/merchants/${id}/merge`, { into_id: intoId })).data as Merchant,
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: async (id: number) => { await apiClient.delete(`/workspaces/${ws}/merchants/${id}`); },
    onSuccess: invalidate,
  });

  return {
    merchants: listQuery.data ?? [],
    isLoading: listQuery.isLoading,
    isError: listQuery.isError,
    create: create.mutateAsync,
    update: update.mutateAsync,
    merge: merge.mutateAsync,
    remove: remove.mutateAsync,
  };
}

/** Gasto do mês (competência) por estabelecimento: o valor cheio e a sua parte. */
export function useMerchantSpending(month: string) {
  const ws = useWorkspaceId();
  return useQuery({
    queryKey: ['merchants', ws, 'spending', month],
    queryFn: async (): Promise<MerchantSpending[]> =>
      (await apiClient.get(`/workspaces/${ws}/merchants/spending`, { params: { month } })).data,
    enabled: !!ws,
  });
}
