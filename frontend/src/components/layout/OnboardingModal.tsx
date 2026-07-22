import * as React from 'react';
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MoneyInput } from "@/components/ui/MoneyInput";
import { useAuth } from '@/hooks/use-auth';
import { apiClient } from '@/api/client';
import { useUIStore } from '@/stores';
import { toast } from '@/stores/toast';
import { Wallet, CreditCard, Sparkles, ChevronRight, ArrowLeft, Calendar } from 'lucide-react';

export function OnboardingModal() {
  const { user } = useAuth();
  const { currentWorkspaceId } = useUIStore();
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
      await apiClient.post('/auth/onboarding', {
        workspace_id: currentWorkspaceId,
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

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-background/80 backdrop-blur-sm p-4">
      <div className="w-full max-w-lg bg-card border border-border rounded-3xl shadow-2xl overflow-hidden animate-in zoom-in-95 duration-300">
        <div className="h-2 bg-muted w-full">
          <div 
            className="h-full bg-primary transition-all duration-500 ease-out" 
            style={{ width: `${(step / 3) * 100}%` }} 
          />
        </div>

        <div className="p-8">
          {step === 1 && (
            <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
              <div className="flex flex-col items-center text-center space-y-4">
                <div className="w-16 h-16 bg-primary/10 rounded-2xl flex items-center justify-center">
                  <Sparkles className="h-8 w-8 text-primary" />
                </div>
                <div className="space-y-2">
                  <h2 className="text-3xl font-bold tracking-tight">Bem-vindo, {user?.name.split(' ')[0]}!</h2>
                  <p className="text-muted-foreground">Vamos deixar tudo pronto para você começar a controlar sua vida financeira.</p>
                </div>
              </div>
              <div className="pt-4">
                 <Button onClick={() => setStep(2)} className="w-full h-12 text-lg font-bold gap-2">
                   Começar Setup <ChevronRight className="h-5 w-5" />
                 </Button>
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
              <div className="space-y-2">
                <h3 className="text-xl font-bold flex items-center gap-2">
                  <Wallet className="h-5 w-5 text-primary" /> Qual sua renda mensal?
                </h3>
                <p className="text-sm text-muted-foreground">Isso ajuda a calcular quanto você pode gastar por mês.</p>
              </div>
              <div className="space-y-4 pt-2">
                <div className="space-y-2">
                  <Label htmlFor="salary">Salário / Renda Líquida</Label>
                  <MoneyInput 
                    id="salary" 
                    placeholder="0,00" 
                    value={salary}
                    onChange={(val: number) => setSalary(val)}
                    className="h-12 text-lg font-bold"
                  />
                </div>
              </div>
              <div className="flex gap-3 pt-4">
                <Button variant="ghost" onClick={() => setStep(1)} className="h-12"><ArrowLeft className="h-4 w-4 mr-2" /> Voltar</Button>
                <Button onClick={() => setStep(3)} className="flex-1 h-12 font-bold" disabled={!salary}>Próximo Passo</Button>
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
              <div className="space-y-2">
                <h3 className="text-xl font-bold flex items-center gap-2">
                  <CreditCard className="h-5 w-5 text-primary" /> Seu cartão principal
                </h3>
                <p className="text-sm text-muted-foreground">Adicione um cartão para rastrear suas faturas. (Opcional)</p>
              </div>
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
                       />
                     </div>
                     <div className="space-y-2">
                       <Label className="flex items-center gap-1.5">
                         <Calendar className="h-3.5 w-3.5 text-muted-foreground" /> Fechamento
                       </Label>
                       <Input 
                        type="number" 
                        min={1} 
                        max={31} 
                        placeholder="5" 
                        value={closingDay} 
                        onChange={(e) => setClosingDay(parseInt(e.target.value) || 5)} 
                       />
                     </div>
                   </div>
                </div>
              </div>
              <div className="flex gap-3 pt-4">
                <Button variant="ghost" onClick={() => setStep(2)} className="h-12"><ArrowLeft className="h-4 w-4 mr-2" /> Voltar</Button>
                <Button 
                  onClick={handleFinish} 
                  className="flex-1 h-12 font-bold bg-emerald-600 hover:bg-emerald-700" 
                  disabled={loading || (!!cardName && !cardLimit)}
                >
                  {loading ? 'Finalizando...' : 'Concluir Tutorial'}
                </Button>
              </div>
              <Button variant="link" className="w-full text-muted-foreground text-xs" onClick={handleFinish}>Pular esta etapa</Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
