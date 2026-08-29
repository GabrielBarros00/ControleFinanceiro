import * as React from 'react';
import { BellRing, Check, Share, Smartphone } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { useAuth } from '@/hooks/use-auth';
import { usePush } from '@/hooks/use-push';
import { toast } from '@/stores/toast';
import { cn } from '@/lib/utils';

/*
 * "Quer ser avisado antes de a conta vencer?" (ADR 0033)
 *
 * ## Por que existe um convite NOSSO antes do prompt do navegador
 *
 * `Notification.requestPermission()` é irreversível na prática: negado, o
 * navegador não deixa perguntar de novo, e o conserto vira um caminho nas
 * configurações que ninguém acha sozinho. Disparar o prompt nativo assim que a
 * pessoa entra é a forma mais eficiente de perder o canal para sempre — ela nega
 * por reflexo, sem saber o que estava recusando.
 *
 * Então: primeiro a gente explica o que ela ganha, e o prompt do navegador só
 * aparece depois do clique em "Ativar" — que é também o gesto de usuário que a
 * API exige, e a única situação em que a resposta tende a ser sim.
 *
 * ## Quem diz "agora não" não some
 *
 * O convite volta sozinho depois de uma semana, e enquanto isso fica um botão
 * discreto ao lado do sino e na tela de Contas a pagar — que é onde a falta do
 * aviso dói. Sem isso, "agora não" viraria "nunca mais", e a pessoa não teria
 * como mudar de ideia sem procurar em Configurações.
 */

const CHAVE_ADIADO = 'cf4:aviso-push-adiado-ate';
const UMA_SEMANA_MS = 7 * 24 * 60 * 60 * 1000;

function adiadoAte(): number {
  try {
    return Number(localStorage.getItem(CHAVE_ADIADO) ?? 0);
  } catch {
    // `localStorage` estoura em modo anônimo de alguns navegadores. Sem memória
    // do adiamento, o pior caso é o convite reaparecer — melhor do que quebrar.
    return 0;
  }
}

function adiar() {
  try {
    localStorage.setItem(CHAVE_ADIADO, String(Date.now() + UMA_SEMANA_MS));
  } catch {
    /* ver acima */
  }
}

/** O que a pessoa ganha. Fica fora dos dois componentes porque os dois mostram. */
function Beneficios() {
  return (
    <ul className="space-y-2.5 text-sm text-muted-foreground">
      {[
        'Três dias antes de vencer, para dar tempo de organizar o dinheiro.',
        'No dia do vencimento, como último lembrete.',
        'Conta a pagar, fatura do cartão e parcela de financiamento.',
      ].map((texto) => (
        <li key={texto} className="flex items-start gap-2.5">
          <Check className="mt-0.5 h-4 w-4 shrink-0 text-brand" aria-hidden />
          <span>{texto}</span>
        </li>
      ))}
    </ul>
  );
}

/** As instruções do iPhone — o único caminho lá é instalar antes. */
function ComoInstalarNoIPhone() {
  return (
    <div className="rounded-lg border border-border bg-accent/40 p-3">
      <p className="flex items-center gap-2 text-sm font-semibold text-foreground">
        <Smartphone className="h-4 w-4 shrink-0" aria-hidden />
        No iPhone, instale o app primeiro
      </p>
      <p className="mt-1.5 text-sm text-muted-foreground">
        A Apple só entrega notificação para aplicativo adicionado à Tela de
        Início. Pelo <strong>Safari</strong>, toque em{' '}
        <Share className="inline h-3.5 w-3.5 align-[-2px]" aria-label="Compartilhar" />{' '}
        <strong>Compartilhar</strong> e depois em{' '}
        <strong>Adicionar à Tela de Início</strong>. Abra o app por esse ícone e
        o botão de ativar aparece aqui.
      </p>
    </div>
  );
}

/** O que fazer quando o navegador já está bloqueado. */
function ComoDesbloquear() {
  return (
    <p className="text-sm text-muted-foreground">
      As notificações estão <strong>bloqueadas</strong> para este site no
      navegador, e por isso não dá para pedir de novo por aqui. Toque no cadeado
      (ou no ícone ao lado do endereço), abra as permissões do site e mude
      <strong> Notificações</strong> para <em>Permitir</em> — depois recarregue a
      página.
    </p>
  );
}

/**
 * O convite que aparece ao entrar no site.
 *
 * Montado uma vez, no `AppShell`. Ele se cala sozinho em todos os casos em que
 * não teria o que oferecer.
 */
export function ConviteDeNotificacao() {
  const { user } = useAuth();
  const { estado, ativar, ocupado } = usePush();
  const [aberto, setAberto] = React.useState(false);

  React.useEffect(() => {
    if (!user) return;
    // O onboarding tem precedência: ele já abre um diálogo, e dois modais na
    // primeira tela é o caminho mais curto para a pessoa fechar os dois sem ler.
    if (user.needs_onboarding) return;
    if (estado !== 'desativado' && estado !== 'precisa-instalar') return;
    if (Date.now() < adiadoAte()) return;

    // Um respiro antes de aparecer: o convite que salta junto com a tela é lido
    // como pop-up e fechado por reflexo.
    const id = setTimeout(() => setAberto(true), 1200);
    return () => clearTimeout(id);
  }, [user, estado]);

  const fechar = () => {
    adiar();
    setAberto(false);
  };

  const confirmar = async () => {
    const deu = await ativar();
    setAberto(false);
    if (deu) {
      toast.success('Pronto', 'Vamos avisar quando uma conta estiver perto de vencer.');
    } else {
      // Também adia quando a pessoa nega no prompt do navegador: insistir na
      // próxima visita não muda a resposta e só irrita.
      adiar();
    }
  };

  return (
    <Dialog open={aberto} onOpenChange={(v) => (v ? setAberto(true) : fechar())}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-xl bg-brand/10 text-brand">
            <BellRing className="h-6 w-6" aria-hidden />
          </div>
          <DialogTitle className="text-center">Quer ser avisado antes de vencer?</DialogTitle>
          <DialogDescription className="text-center">
            Esquecer uma conta é a falha mais cara que este app pode deixar
            acontecer — e ele já sabe todas as suas datas.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <Beneficios />
          {estado === 'precisa-instalar' && <ComoInstalarNoIPhone />}
        </div>

        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="ghost" onClick={fechar}>
            Agora não
          </Button>
          {estado === 'desativado' && (
            <Button onClick={confirmar} pending={ocupado} className="font-bold">
              Ativar avisos
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

/**
 * O botão que fica ao lado do sino e na tela de Contas a pagar.
 *
 * `variante="icone"` na barra superior (ao lado do sino, onde só cabe um ícone)
 * e `variante="faixa"` dentro de uma tela, onde há espaço para dizer o porquê.
 */
export function BotaoAtivarNotificacoes({
  variante = 'icone',
  className,
}: {
  variante?: 'icone' | 'faixa';
  className?: string;
}) {
  const { estado, ativar, ocupado } = usePush();
  const [detalhe, setDetalhe] = React.useState(false);

  // Some quando não há o que oferecer: já ativado, ou navegador sem suporte.
  if (estado === 'ativado' || estado === 'indisponivel') return null;

  const rotulo = estado === 'bloqueado' ? 'Notificações bloqueadas' : 'Ativar avisos de vencimento';

  const acionar = async () => {
    // Nos dois casos em que ativar aqui não pode dar certo, o botão ENSINA em
    // vez de tentar: no iPhone sem instalar não existe push, e bloqueado o
    // `requestPermission` volta 'denied' na hora, sem perguntar nada.
    if (estado === 'bloqueado' || estado === 'precisa-instalar') {
      setDetalhe(true);
      return;
    }
    const deu = await ativar();
    if (deu) toast.success('Pronto', 'Vamos avisar quando uma conta estiver perto de vencer.');
  };

  return (
    <>
      {variante === 'icone' ? (
        <button
          type="button"
          onClick={acionar}
          disabled={ocupado}
          aria-label={rotulo}
          title={rotulo}
          className={cn(
            'relative flex h-9 w-9 items-center justify-center rounded-lg transition-colors',
            'text-muted-foreground hover:bg-accent hover:text-foreground',
            className,
          )}
        >
          <BellRing className="h-5 w-5" />
          {/* Ponto discreto: é um convite, não um alerta — sem contador e sem
              vermelho, que aqui competiriam com o do sino ao lado. */}
          <span
            className="absolute right-1 top-1 h-2 w-2 rounded-full bg-brand ring-2 ring-background"
            aria-hidden
          />
        </button>
      ) : (
        <button
          type="button"
          onClick={acionar}
          disabled={ocupado}
          className={cn(
            'flex w-full items-center gap-3 rounded-xl border border-brand/40 bg-brand/5 px-4 py-3 text-left transition-colors hover:bg-brand/10 disabled:opacity-60',
            className,
          )}
        >
          <BellRing className="h-5 w-5 shrink-0 text-brand" aria-hidden />
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-semibold text-foreground">{rotulo}</span>
            <span className="block text-xs text-muted-foreground">
              {estado === 'bloqueado'
                ? 'Toque para ver como desbloquear no navegador.'
                : estado === 'precisa-instalar'
                  ? 'No iPhone, é preciso instalar o app antes. Toque para ver como.'
                  : 'Avisamos três dias antes e no dia do vencimento.'}
            </span>
          </span>
        </button>
      )}

      <Dialog open={detalhe} onOpenChange={setDetalhe}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {estado === 'bloqueado' ? 'Como desbloquear' : 'Como receber no iPhone'}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-1">
            {estado === 'bloqueado' ? <ComoDesbloquear /> : <ComoInstalarNoIPhone />}
            <Beneficios />
          </div>
          <div className="flex justify-end">
            <Button variant="secondary" onClick={() => setDetalhe(false)}>
              Entendi
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
