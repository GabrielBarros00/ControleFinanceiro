import * as React from 'react';

/*
 * "Instalar como aplicativo" — os dois caminhos que existem.
 *
 * **Android/Chrome/Edge:** o navegador decide que o site é instalável e dispara
 * `beforeinstallprompt`. O evento precisa ser CAPTURADO e guardado: ele só pode
 * ser usado uma vez, e só a partir de um gesto do usuário. Guardar é o que
 * permite oferecer o botão onde faz sentido (em Configurações) em vez de aceitar
 * o banner que o navegador põe onde quer.
 *
 * **iOS/Safari:** não existe evento nenhum. A Apple nunca implementou
 * `beforeinstallprompt`, e instalar é um caminho manual — Compartilhar →
 * Adicionar à Tela de Início. A única coisa honesta a fazer é detectar iOS e
 * ENSINAR o caminho. Um botão "Instalar" que não faz nada no iPhone é pior do
 * que não ter botão.
 */

/** O evento não está no lib.dom padrão — é uma extensão do Chromium. */
interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

export type EstadoDeInstalacao =
  /** Já está rodando como app instalado — não há o que oferecer. */
  | 'instalado'
  /** O navegador ofereceu o gancho: dá para instalar com um toque. */
  | 'disponivel'
  /** iOS: dá para instalar, mas só à mão. Mostrar as instruções. */
  | 'manual-ios'
  /** Nem instalado nem instalável (desktop sem suporte, Firefox Android…). */
  | 'indisponivel';

/** Rodando em janela própria, sem barra de endereço? */
function ehStandalone(): boolean {
  return (
    window.matchMedia('(display-mode: standalone)').matches ||
    // O Safari do iOS não implementa `display-mode`; usa esta propriedade
    // fora do padrão, que só existe lá.
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

function ehIOS(): boolean {
  const ua = navigator.userAgent;
  // `MSStream` exclui o IE Mobile antigo, que mentia "iPhone" no user agent.
  const iOSClassico = /iPad|iPhone|iPod/.test(ua) && !('MSStream' in window);
  // Desde o iPadOS 13 o iPad se anuncia como Mac; o toque é o que o distingue.
  const iPadModerno = /Macintosh/.test(ua) && navigator.maxTouchPoints > 1;
  return iOSClassico || iPadModerno;
}

export function useInstallPrompt() {
  const [evento, setEvento] = React.useState<BeforeInstallPromptEvent | null>(null);
  const [instalado, setInstalado] = React.useState(ehStandalone);

  React.useEffect(() => {
    const aoOferecer = (e: Event) => {
      // Sem o `preventDefault` o Chrome mostra a própria barra de instalação
      // por cima do app — e o botão em Configurações vira redundante.
      e.preventDefault();
      setEvento(e as BeforeInstallPromptEvent);
    };
    const aoInstalar = () => {
      setInstalado(true);
      setEvento(null);
    };
    window.addEventListener('beforeinstallprompt', aoOferecer);
    window.addEventListener('appinstalled', aoInstalar);
    return () => {
      window.removeEventListener('beforeinstallprompt', aoOferecer);
      window.removeEventListener('appinstalled', aoInstalar);
    };
  }, []);

  const estado: EstadoDeInstalacao = instalado
    ? 'instalado'
    : evento
      ? 'disponivel'
      : ehIOS()
        ? 'manual-ios'
        : 'indisponivel';

  /** Abre o diálogo do navegador. Devolve `true` se a pessoa aceitou. */
  const instalar = React.useCallback(async () => {
    if (!evento) return false;
    await evento.prompt();
    const { outcome } = await evento.userChoice;
    // O evento é de uso único: guardá-lo depois de consumido daria um botão que
    // não faz mais nada. Quem recusou verá a oferta de novo numa próxima visita,
    // quando o navegador decidir disparar o evento outra vez.
    setEvento(null);
    return outcome === 'accepted';
  }, [evento]);

  return { estado, instalar };
}
