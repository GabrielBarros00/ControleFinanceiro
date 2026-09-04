import * as React from 'react';
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MoneyInput } from "@/components/ui/MoneyInput";
import { useAuth } from '@/hooks/use-auth';
import { useBaseCurrency } from '@/hooks/use-base-currency';
import { currencySymbol } from '@/lib/money';
import { apiClient } from '@/api/client';
import { toast } from '@/stores/toast';
import { Wallet, CreditCard, Sparkles, ChevronRight, ArrowLeft, Calendar } from 'lucide-react';
import { NumberInput } from '@/components/ui/NumberInput';

export function OnboardingModal() {
  const { user } = useAuth();
  const baseCurrency = useBaseCurrency();
  const [isOpen, setIsOpen] = React.useState(false);
  const [step, setStep] = React.useState(1);
  const [loading, setLoading] = React.useState(false);

  // Form State
  const [salary, setSalary] = React.useState<number>(0);
  const [cardName, setCardName] = React.useState('');
  const [cardLimit, setCardLimit] = React.useState<number>(0);
  const [closingDay, setClosingDay] = React.useState<number>(5);

  React.useEffect(() => {
    if (user && user.needs_onboarding) {
      setIsOpen(true);
    }
  }, [user]);

  const handleFinish = async () => {
    setLoading(true);
    try {
      // SEM workspace_id: o onboarding cria a renda e o cartão DA PESSOA, então
      // o backend resolve o workspace próprio dela. Mandar o `currentWorkspaceId`
      // gravava o salário no workspace compartilhado quando o usuário se
      // cadastrava por um convite (ele nasce com dois workspaces).
      await apiClient.post('/auth/onboarding', {
        salary: salary || 0,
        credit_card_name: cardName || null,
        credit_card_limit: cardLimit || null,
        credit_card_closing_day: cardName ? closingDay : null
      });
      setIsOpen(false);
      window.location.reload(); // Reload to refresh user state and dashboard
    } catch {
      toast.error('Erro ao salvar onboarding', 'Verifique se preencheu todos os campos corretamente.');
    } finally {
      setLoading(false);
    }
  };

  // Diálogo BLOQUEANTE: sem X, sem Esc, sem clique fora — o onboarding é a porta
  // de entrada e só sai concluído ou pulado. Mas é um `Dialog` de verdade (Radix)
  // e não uma `<div>` na mão: foco preso dentro, foco devolvido na saída,
  // `role="dialog"`/`aria-modal` e o resto da página marcado como inerte para
  // leitores de tela. Era a PRIMEIRA tela do usuário novo e a única do app que
  // ainda não tinha nada disso.
  return (
    <Dialog open={isOpen}>
      <DialogContent
        className="p-0 sm:max-w-lg"
        showCloseButton={false}
        onEscapeKeyDown={(e) => e.preventDefault()}
        onPointerDownOutside={(e) => e.preventDefault()}
        // Sem `id`/`aria-labelledby` na mão: o Radix gera o id do título e o
        // associa sozinho. Fixar `id="onboarding-titulo"` no `DialogTitle`
        // SOBRESCREVIA o id gerado, então a verificação interna do Radix não
        // encontrava o título e disparava, a cada abertura,
        // "`DialogContent` requires a `DialogTitle`" — o erro de console que a
        // auditoria externa via repetido no log e que nenhum teste pegava.
      >
        <div className="h-2 bg-muted w-full">
          <div
            className="h-full bg-primary transition-all duration-500 ease-out"
            role="progressbar"
            aria-valuenow={step}
            aria-valuemin={1}
            aria-valuemax={3}
            aria-label={`Passo ${step} de 3`}
            style={{ width: `${(step / 3) * 100}%` }}
          />
        </div>

        <div className="p-8 pt-2">
          {step === 1 && (
            <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
              <DialogHeader className="flex flex-col items-center space-y-4 text-center sm:text-center">
                <div className="w-16 h-16 bg-primary/10 rounded-2xl flex items-center justify-center">
                  <Sparkles className="h-8 w-8 text-primary" />
                </div>
                <div className="space-y-2">
                  <DialogTitle className="text-3xl font-bold tracking-tight">
                    Bem-vindo, {user?.name.split(' ')[0]}!
                  </DialogTitle>
                  <DialogDescription>
                    Vamos deixar tudo pronto para você começar a controlar sua vida financeira.
                  </DialogDescription>
                </div>
              </DialogHeader>
              <div className="space-y-2 pt-4">
                 <Button onClick={() => setStep(2)} className="w-full h-12 text-lg font-bold gap-2">
                   Começar <ChevronRight className="h-5 w-5" />
                 </Button>
                 {/* Saída no PRIMEIRO passo. O diálogo é bloqueante de propósito
                     (sem X, sem Esc, sem clique fora), e até aqui a única opção
                     da tela de boas-vindas era seguir — quem só quer olhar o app
                     não tinha alternativa nenhuma à vista. Os passos 2 e 3 já
                     ofereciam pular; o primeiro, não. */}
                 <Button variant="link" onClick={handleFinish} className="w-full text-muted-foreground text-xs">
                   Configurar depois
                 </Button>
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
              <DialogHeader className="space-y-2">
                <DialogTitle className="text-xl font-bold flex items-center gap-2">
                  <Wallet className="h-5 w-5 text-primary" /> Qual sua renda mensal?
                </DialogTitle>
                <DialogDescription>
                  Isso ajuda a calcular quanto você pode gastar por mês.
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-4 pt-2">
                <div className="space-y-2">
                  <Label htmlFor="salary">Salário / Renda Líquida</Label>
                  <MoneyInput
                    id="salary"
                    placeholder="0,00"
                    value={salary}
                    onChange={(val: number) => setSalary(val)}
                    prefix={currencySymbol(baseCurrency)}
                    className="h-12 text-lg font-bold"
                  />
                </div>
              </div>
              <div className="flex gap-3 pt-4">
                <Button variant="ghost" onClick={() => setStep(1)} className="h-12"><ArrowLeft className="h-4 w-4 mr-2" /> Voltar</Button>
                {/* Sem `disabled`: o backend suporta pular a etapa (salary <= 0
                    não cria renda — auth.py), mas a UI travava o botão em 0 e
                    obrigava a inventar um valor. */}
                <Button onClick={() => setStep(3)} className="flex-1 h-12 font-bold">
                  {salary ? 'Próximo' : 'Pular por enquanto'}
                </Button>
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
              <DialogHeader className="space-y-2">
                <DialogTitle className="text-xl font-bold flex items-center gap-2">
                  <CreditCard className="h-5 w-5 text-primary" /> Seu cartão principal
                </DialogTitle>
                <DialogDescription>
                  Adicione um cartão para rastrear suas faturas. (Opcional)
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-4 pt-2">
                <div className="grid gap-4">
                   <div className="space-y-2">
                     <Label>Nome do Cartão</Label>
                     <Input placeholder="Ex: Nubank, Inter..." value={cardName} onChange={(e) => setCardName(e.target.value)} />
                   </div>
                   
                   <div className="grid grid-cols-2 gap-4">
                     <div className="space-y-2">
                       <Label>Limite Total</Label>
                       <MoneyInput
                        placeholder="0,00"
                        value={cardLimit}
                        onChange={(val: number) => setCardLimit(val)}
                        prefix={currencySymbol(baseCurrency)}
                       />
                     </div>
                     <div className="space-y-2">
                       <Label className="flex items-center gap-1.5">
                         <Calendar className="h-3.5 w-3.5 text-muted-foreground" /> Fechamento
                       </Label>
                       {/* `padraoAoSair` no lugar do antigo `|| 5`: aquele
                           repunha o valor a CADA tecla, então não dava para
                           apagar o campo nem digitar um número começado por 0.
                           Agora o padrão é aplicado só quando a pessoa sai
                           deixando vazio. */}
                       <NumberInput
                        aria-label="Dia de fechamento do cartão"
                        min={1}
                        max={31}
                        padraoAoSair={5}
                        placeholder="5"
                        value={closingDay}
                        onChange={(v) => setClosingDay(v ?? 5)}
                       />
                     </div>
                   </div>
                </div>
              </div>
              {/* O botão "Concluir" trava quando há nome de cartão sem limite —
                  e até aqui ele travava em SILÊNCIO: nem erro no campo, nem
                  asterisco, nem `aria-describedby`. A pessoa ficava olhando um
                  botão apagado sem saber o que faltava. */}
              {!!cardName && !cardLimit && (
                <p id="onboarding-falta-limite" className="text-xs font-medium text-destructive">
                  Informe o limite do cartão para concluir — ou deixe o nome em branco e pule esta etapa.
                </p>
              )}
              <div className="flex gap-3 pt-4">
                <Button variant="ghost" onClick={() => setStep(2)} className="h-12"><ArrowLeft className="h-4 w-4 mr-2" /> Voltar</Button>
                <Button 
                  onClick={handleFinish} 
                  className="flex-1 h-12 font-bold" 
                  disabled={loading || (!!cardName && !cardLimit)}
                  aria-describedby={!!cardName && !cardLimit ? 'onboarding-falta-limite' : undefined}
                >
                  {loading ? 'Salvando…' : 'Concluir'}
                </Button>
              </div>
              <Button variant="link" className="w-full text-muted-foreground text-xs" onClick={handleFinish}>Pular esta etapa</Button>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
