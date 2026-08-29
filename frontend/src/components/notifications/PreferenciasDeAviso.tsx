import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { BellRing } from 'lucide-react';

import { apiClient } from '@/api/client';
import { Button } from '@/components/ui/button';
import {
  Card, CardContent, CardDescription, CardHeader, CardTitle,
} from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { Switch } from '@/components/ui/switch';
import { usePush } from '@/hooks/use-push';
import { toast } from '@/stores/toast';
import { getApiErrorMessage } from '@/lib/api-error';

/**
 * Preferências do aviso de vencimento (ADR 0033).
 *
 * Este cartão é também o único caminho para DESLIGAR o push depois de ligado —
 * sem ele, "ativar" seria de mão única, e a única saída da pessoa seria bloquear
 * o site no navegador (que é o estado do qual ela não sabe voltar).
 */

interface Prefs {
  days_before: number;
  by_email: boolean;
  show_amount: boolean;
}

const OPCOES_DE_DIAS = [1, 2, 3, 5, 7, 10, 15];

export function PreferenciasDeAviso() {
  const queryClient = useQueryClient();
  const { estado, desativar, ocupado } = usePush();

  const { data: prefs } = useQuery<Prefs>({
    queryKey: ['notification-preferences'],
    queryFn: async () => (await apiClient.get('/me/notification-preferences')).data,
  });

  const salvar = useMutation({
    mutationFn: async (patch: Partial<Prefs>) =>
      (await apiClient.put('/me/notification-preferences', patch)).data as Prefs,
    onSuccess: (novo) => {
      queryClient.setQueryData(['notification-preferences'], novo);
    },
    onError: (err) => toast.error(getApiErrorMessage(err, 'Não foi possível salvar.')),
  });

  return (
    <Card className="bg-card border-border shadow-xl">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <BellRing className="h-5 w-5 text-muted-foreground" aria-hidden />
          Avisos de vencimento
        </CardTitle>
        <CardDescription>
          Avisamos quando uma conta a pagar, uma fatura de cartão ou uma parcela
          de financiamento está chegando no vencimento. O aviso no sino funciona
          sempre; o push é o que alcança com o app fechado.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[240px] flex-1 space-y-2">
            <Label htmlFor="aviso-dias">Avisar com antecedência de</Label>
            <NativeSelect
              id="aviso-dias"
              value={String(prefs?.days_before ?? 3)}
              onChange={(e) => salvar.mutate({ days_before: Number(e.target.value) })}
            >
              {OPCOES_DE_DIAS.map((d) => (
                <option key={d} value={d} className="bg-card">
                  {d === 1 ? '1 dia' : `${d} dias`}
                </option>
              ))}
            </NativeSelect>
            <p className="text-xs text-muted-foreground">
              Além deste, sempre sai um aviso no dia do vencimento e um se a
              conta passar da data.
            </p>
          </div>
        </div>

        <label className="flex items-start gap-3">
          <Switch
            checked={prefs?.show_amount ?? false}
            onCheckedChange={(v) => salvar.mutate({ show_amount: v })}
            aria-label="Mostrar o valor no aviso"
          />
          <span className="min-w-0">
            <span className="block text-sm font-medium text-foreground">
              Mostrar o valor no aviso
            </span>
            <span className="block text-xs text-muted-foreground">
              Desligado, o aviso diz o que vence e quando, mas não quanto. O
              conteúdo trafega cifrado de ponta a ponta — quem lê é quem olhar a
              tela de bloqueio do seu aparelho.
            </span>
          </span>
        </label>

        <label className="flex items-start gap-3">
          <Switch
            checked={prefs?.by_email ?? false}
            onCheckedChange={(v) => salvar.mutate({ by_email: v })}
            aria-label="Receber também por e-mail"
          />
          <span className="min-w-0">
            <span className="block text-sm font-medium text-foreground">
              Receber também por e-mail
            </span>
            <span className="block text-xs text-muted-foreground">
              Útil se você usa iPhone sem instalar o app — lá o push só funciona
              pelo aplicativo da Tela de Início.
            </span>
          </span>
        </label>

        {estado === 'ativado' && (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-accent/30 px-4 py-3">
            <span className="text-sm text-muted-foreground">
              O push está ativo <strong className="text-foreground">neste aparelho</strong>.
              Cada navegador é ativado separadamente.
            </span>
            <Button
              variant="outline"
              pending={ocupado}
              onClick={async () => {
                await desativar();
                toast.info('Push desativado neste aparelho');
              }}
            >
              Desativar aqui
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
