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
import { Wallet, Sparkles, ChevronRight, ArrowLeft } from 'lucide-react';

export function OnboardingModal() {
  const { user } = useAuth();
  const baseCurrency = useBaseCurrency();
  const [isOpen, setIsOpen] = React.useState(false);
  const [step, setStep] = React.useState(1);
  const [loading, setLoading] = React.useState(false);

  /*
   * O onboarding pergunta UMA coisa: quanto você tem hoje, e onde.
   *
   * Ele pedia salário e cartão. Nenhum dos dois é o que a primeira tela usa
   * para responder a primeira pergunta — e depois da Onda 2 isso ficou visível:
   * "Hoje" abre com "Seu dinheiro", e para todo usuário novo esse bloco dizia
   * *"Saldo ainda não configurado"*. Três passos de cadastro no primeiro minuto,
   * e a tela inicial ainda começava vazia no lugar mais importante.
   *
   * Saldo de abertura é o único dado que o app não deduz de nada: não sai de
   * lançamento, nem de renda, nem de fatura. Salário reaparece todo mês sozinho
   * (recorrência) e cartão se cadastra na hora de usar — os dois viraram convite
   * em contexto, nas telas de Rendas e Cartões vazias.
   */
  const [accountName, setAccountName] = React.useState('');
  const [accountBalance, setAccountBalance] = React.useState<number>(0);

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
        // `account_balance` vai mesmo quando é 0: "não tenho nada na conta" é
        // uma resposta, e diferente de "não quis dizer" (que é não mandar nome).
        account_name: accountName || null,
        account_balance: accountName ? accountBalance : null,
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
            aria-valuemax={2}
            aria-label={`Passo ${step} de 2`}
            style={{ width: `${(step / 2) * 100}%` }}
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
                  <Wallet className="h-5 w-5 text-primary" /> Quanto você tem hoje, e onde?
                </DialogTitle>
                <DialogDescription>
                  É o ponto de partida. O que aconteceu antes de hoje já está dentro
                  desse número — daqui para frente o app conta a partir dele.
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-4 pt-2">
                <div className="space-y-2">
                  <Label htmlFor="account-name">Onde está o dinheiro</Label>
                  <Input
                    id="account-name"
                    placeholder="Ex: Nubank, Itaú, carteira"
                    value={accountName}
                    onChange={(e) => setAccountName(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="account-balance">Quanto há nela agora</Label>
                  <MoneyInput
                    id="account-balance"
                    placeholder="0,00"
                    value={accountBalance}
                    onChange={(val: number) => setAccountBalance(val)}
                    prefix={currencySymbol(baseCurrency)}
                    className="h-12 text-lg font-bold"
                  />
                </div>
              </div>
              <div className="flex gap-3 pt-4">
                <Button variant="ghost" onClick={() => setStep(1)} className="h-12">
                  <ArrowLeft className="h-4 w-4 mr-2" /> Voltar
                </Button>
                {/* Sem `disabled`: quem não sabe o número agora não pode ficar
                    preso na porta de entrada. O backend aceita concluir sem
                    conta nenhuma, e a primeira tela continua oferecendo
                    informar depois. */}
                <Button onClick={handleFinish} disabled={loading} className="h-12 flex-1 font-bold">
                  {loading ? 'Salvando…' : accountName ? 'Concluir' : 'Pular esta etapa'}
                </Button>
              </div>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
