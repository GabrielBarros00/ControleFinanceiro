import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { useMerchants } from '@/hooks/use-merchants';

export interface SubscriptionFieldsValue {
  is_subscription: boolean;
  plan: string;
  trial_ends_on: string;
  notes: string;
  merchant_name: string;
}

/**
 * O que a recorrência NÃO diz sozinha quando é uma assinatura (ADR 0039).
 *
 * Período e renovação ficam no editor de recorrência, que já os tem; aqui entram
 * o provedor (o estabelecimento, ADR 0038), o plano, o fim do teste grátis e os
 * benefícios. Campos nativos, porque o formulário vive dentro de um Dialog.
 */
export function SubscriptionFields({ value, onChange, idPrefix = 'rec' }: {
  value: SubscriptionFieldsValue;
  onChange: (patch: Partial<SubscriptionFieldsValue>) => void;
  idPrefix?: string;
}) {
  const { merchants } = useMerchants();
  const id = (nome: string) => `${idPrefix}-${nome}`;

  return (
    <div className="space-y-3">
      <div className="space-y-2">
        <Label htmlFor={id('merchant')}>Estabelecimento (opcional)</Label>
        <Input
          id={id('merchant')}
          list={id('merchant-sugestoes')}
          autoComplete="off"
          maxLength={120}
          placeholder="Netflix, Smart Fit, Condomínio…"
          value={value.merchant_name}
          onChange={(e) => onChange({ merchant_name: e.target.value })}
          className="bg-background/50"
        />
        <datalist id={id('merchant-sugestoes')}>
          {merchants.map((m) => <option key={m.id} value={m.name} />)}
        </datalist>
      </div>

      <div className="rounded-lg border border-border bg-accent/30 p-3">
        <div className="flex items-center justify-between gap-4">
          <div className="min-w-0 space-y-0.5">
            <Label htmlFor={id('subscription')}>É uma assinatura</Label>
            <p className="text-[10px] font-medium text-muted-foreground">
              Streaming, academia, software: entra no quadro de assinaturas, com o custo por mês.
            </p>
          </div>
          <Switch
            id={id('subscription')}
            checked={value.is_subscription}
            onCheckedChange={(v) => onChange({ is_subscription: v })}
          />
        </div>
        {value.is_subscription && (
          <div className="mt-3 space-y-3">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor={id('plan')}>Plano</Label>
                <Input id={id('plan')} maxLength={120} placeholder="Premium, Família…" value={value.plan}
                  onChange={(e) => onChange({ plan: e.target.value })} className="bg-background/50" />
              </div>
              <div className="space-y-2">
                <Label htmlFor={id('trial')}>Teste grátis até</Label>
                <Input id={id('trial')} type="date" value={value.trial_ends_on}
                  onChange={(e) => onChange({ trial_ends_on: e.target.value })} className="bg-background/50" />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor={id('notes')}>Benefícios</Label>
              <Textarea id={id('notes')} rows={2} maxLength={1000} placeholder="4 telas, sem anúncios…" value={value.notes}
                onChange={(e) => onChange({ notes: e.target.value })} className="bg-background/50" />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
