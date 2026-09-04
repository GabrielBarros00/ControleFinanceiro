import type { ReactNode } from 'react';
import { Sidebar } from './Sidebar';
import { BottomNav } from './BottomNav';
import { ScopeSwitcher } from './ScopeSwitcher';
import { OnboardingModal } from './OnboardingModal';
import { NewTransactionDialog } from '@/components/dashboard/NewTransactionDialog';
import { TransactionDetailHost } from '@/components/dashboard/TransactionDetailHost';
import { NotificationCenter } from '@/components/notifications/NotificationCenter';
import { InstallAppButton } from '@/components/pwa/InstallApp';
import { PendingInvitesModal } from '@/components/notifications/PendingInvitesModal';
import {
  BotaoAtivarNotificacoes, ConviteDeNotificacao,
} from '@/components/notifications/AtivarNotificacoes';
import { useWorkspaceEvents } from '@/hooks/use-workspace-events';
import { useNewTxStore } from '@/stores';

/*
 * AppShell — casca persistente das telas autenticadas (docs/frontend-redesign/04).
 * Sidebar no desktop, BottomNav no mobile, conteúdo centralizado (max 1200) e o
 * dialog global de "Nova despesa" (acionável do FAB e de qualquer tela).
 */
export function AppShell({ children }: { children: ReactNode }) {
  useWorkspaceEvents();
  const { open, setOpen } = useNewTxStore();

  return (
    /*
      `min-h-dvh` e não `min-h-screen`.

      `min-h-screen` é `100vh`, e no celular `100vh` é o viewport GRANDE — a
      altura da tela com a barra de endereço já recolhida. Com a barra à vista
      (que é o estado inicial de toda visita), o documento nasce 60 a 120px mais
      alto do que a área visível: qualquer página, mesmo vazia, ganha rolagem
      vertical que ninguém pediu, e um `bottom: 0` fixo passa a disputar espaço
      com a barra do navegador.

      `100dvh` é o viewport DINÂMICO: acompanha a barra do navegador aparecendo e
      sumindo, e vale a altura realmente visível nos dois estados. O projeto não
      tinha um `dvh` sequer.
    */
    <div className="flex min-h-dvh bg-background">
      {/*
        "Pular para o conteúdo" — o primeiro item focável da página.

        Medido antes: o primeiro Tab focava a marca e os treze seguintes
        percorriam a barra lateral; o conteúdo da página só recebia foco no 15º
        Tab — e no 22º dentro de um espaço. **Em toda navegação de página.** É a
        falha do critério 2.4.1 do WCAG (nível A), e para quem navega só de
        teclado significa atravessar o menu inteiro a cada tela.

        `sr-only focus:not-sr-only`: invisível até receber foco, que é o
        comportamento esperado — ele não é um botão da interface, é um atalho.
      */}
      <a
        href="#conteudo"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-100 focus:rounded-lg focus:bg-primary focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-primary-foreground"
      >
        Pular para o conteúdo
      </a>
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        {/*
          Barra superior. À direita, a central de avisos: o convite passou a
          exigir aceite, e o aviso precisa estar visível de QUALQUER tela — não
          dá para depender de a pessoa abrir Configurações.

          À esquerda, e SÓ no celular, o seletor de escopo. No desktop ele já
          mora no topo da barra lateral; abaixo de `md` a barra lateral não
          existe, e esta faixa era uma tira de 40px com um sino solitário —
          enquanto a pergunta "estou no meu ou no espaço compartilhado?" não
          tinha resposta em lugar nenhum da tela, e trocar de espaço era
          simplesmente impossível.

          O botão de instalar fica AGRUPADO com o sino, e não solto como terceiro
          filho: a faixa é `justify-between` no celular, e três filhos diretos
          espalhariam os três pela largura em vez de manter o par colado à
          direita. Ele some sozinho quando não há o que oferecer — ver
          `components/pwa/InstallApp.tsx`.
        */}
        <div className="sticky top-0 z-30 flex items-center justify-between gap-2 border-b border-border/40 bg-background/80 px-2 py-2 pt-safe backdrop-blur-sm sm:px-6 md:justify-end md:px-8">
          <ScopeSwitcher className="md:hidden" />
          <div className="flex items-center gap-1">
            <InstallAppButton />
            {/* Ao LADO do sino, e não dentro dele: o sino mostra o que já
                chegou; este oferece o canal que ainda não existe. Some sozinho
                quando não há o que oferecer (ADR 0033). */}
            <BotaoAtivarNotificacoes />
            <NotificationCenter />
          </div>
        </div>
        {/* O `pb` reserva o espaço da barra inferior fixa MAIS a área segura do
            aparelho — sem a segunda parcela, no iPhone o último item da lista
            ficava atrás do indicador de home e não dava para tocá-lo. */}
        {/* `tabIndex={-1}`: sem ele o `<main>` não é um destino de foco válido e
            o atalho acima levaria a rolagem sem levar o FOCO — o próximo Tab
            voltaria para o começo da barra lateral, desfazendo o atalho. */}
        <main id="conteudo" tabIndex={-1} className="mx-auto w-full max-w-[1200px] flex-1 space-y-6 px-4 py-6 pb-[calc(6rem+env(safe-area-inset-bottom))] animate-in fade-in duration-300 sm:px-6 md:px-8 md:py-8 md:pb-8">
          {children}
        </main>
      </div>
      <BottomNav />
      <OnboardingModal />
      {/* Depois do onboarding (que termina em reload), o convite pendente é a
          primeira coisa a resolver — no sino ele passava batido. */}
      <PendingInvitesModal />
      {/* Depois do onboarding e do convite pendente — ele mesmo se cala
          enquanto qualquer um dos dois estiver na frente. */}
      <ConviteDeNotificacao />
      <NewTransactionDialog open={open} onOpenChange={setOpen} />
      <TransactionDetailHost />
    </div>
  );
}
