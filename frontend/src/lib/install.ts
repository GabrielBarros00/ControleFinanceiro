/*
 * "Instalar como aplicativo" — o estado, guardado fora do React.
 *
 * ## Por que isto não é um `useEffect`
 *
 * `beforeinstallprompt` dispara **uma vez por carregamento de página**, cedo, e
 * o Chrome não o repete em navegação de SPA. Quem só começa a escutar quando um
 * componente monta perde o evento e nunca mais o vê.
 *
 * Era exatamente o que acontecia aqui: o listener vivia dentro do hook, e o
 * único componente que usava o hook era o cartão no fim de Configurações. O
 * percurso real de quem usa o app é chegar em `/login` (evento dispara, ninguém
 * escuta), entrar — e o login navega por `navigate()`, client-side, sem reload —
 * e só depois, se algum dia, abrir Configurações. O cartão montava num mundo em
 * que o evento já tinha passado, caía em `indisponivel` e devolvia `null`. O
 * botão "Instalar" só aparecia para quem desse F5 ESTANDO em `/settings`.
 *
 * Nada disso dá erro em log nenhum. A funcionalidade simplesmente não existia.
 *
 * A correção é registrar o listener em escopo de módulo, antes do `createRoot`
 * (ver `iniciarCapturaDeInstalacao` sendo chamado em `main.tsx`), e guardar o
 * resultado num store externo. O React lê por `useSyncExternalStore` — mesmo
 * padrão de `hooks/use-media-query.ts`, e pela mesma razão: o dono do estado é
 * o navegador.
 *
 * ## As duas perguntas, que são diferentes
 *
 * - **"Esta janela é o app?"** — `display-mode: standalone`. É sobre a JANELA.
 * - **"Este aparelho tem o app instalado?"** — `getInstalledRelatedApps()`. É
 *   sobre o APARELHO, e responde mesmo quando se está numa aba comum.
 *
 * A diferença entre as duas é o que explica o ícone com um Chrome pequeno no
 * canto: no Android, "instalar" de verdade produz um **WebAPK** (o Chrome manda
 * o manifesto ao servidor de emissão do Google, que assina um APK e o instala em
 * silêncio). Quando essa ponte falha — Play Store deslogada, Chrome velho, rede
 * ruim no instante — ou quando a pessoa escolheu "Adicionar à tela inicial" em
 * vez de "Instalar app", o Chrome cai no fallback e cria um mero ATALHO, que
 * ganha o crachá. Um atalho não é um WebAPK: `getInstalledRelatedApps()` devolve
 * lista vazia e o `beforeinstallprompt` continua disparando. É essa combinação
 * que deixa o app dizer "isso que você instalou é só um atalho".
 */

/** O evento não está no lib.dom padrão — é uma extensão do Chromium. */
interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

/** `getInstalledRelatedApps` também não está no lib.dom do TypeScript 5.9. */
interface RelatedApplication {
  platform: string;
  url?: string;
  id?: string;
  version?: string;
}
type NavigatorComApps = Navigator & {
  getInstalledRelatedApps?: () => Promise<RelatedApplication[]>;
};

export interface EstadoDeInstalacao {
  /** O evento do Chromium, se ele já veio. Uso único. */
  evento: BeforeInstallPromptEvent | null;
  /** Esta janela é o app instalado (sem barra de endereço)? */
  standalone: boolean;
  /**
   * Existe app instalado NESTE APARELHO?
   *
   * `null` não é "não": é "este navegador não sabe responder" — iOS, Firefox,
   * desktop antigo. Confundir os dois faria o diagnóstico afirmar "não está
   * instalado" justamente onde ele não tem como saber.
   */
  appDetectado: boolean | null;
}

/** Rodando em janela própria, sem barra de endereço? */
function ehStandalone(): boolean {
  return (
    window.matchMedia('(display-mode: standalone)').matches ||
    // O Safari do iOS não implementa `display-mode`; usa esta propriedade fora
    // do padrão, que só existe lá.
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

export function ehIOS(): boolean {
  const ua = navigator.userAgent;
  // `MSStream` exclui o IE Mobile antigo, que mentia "iPhone" no user agent.
  const iOSClassico = /iPad|iPhone|iPod/.test(ua) && !('MSStream' in window);
  // Desde o iPadOS 13 o iPad se anuncia como Mac; o toque é o que o distingue.
  const iPadModerno = /Macintosh/.test(ua) && navigator.maxTouchPoints > 1;
  return iOSClassico || iPadModerno;
}

let estado: EstadoDeInstalacao = {
  evento: null,
  standalone: false,
  appDetectado: null,
};

const assinantes = new Set<() => void>();

function definir(mudanca: Partial<EstadoDeInstalacao>) {
  // Objeto NOVO a cada mudança: `useSyncExternalStore` compara por identidade e
  // uma mutação no lugar não renderizaria ninguém.
  estado = { ...estado, ...mudanca };
  for (const avisar of assinantes) avisar();
}

let iniciado = false;

/**
 * Liga a captura. Chamada de `main.tsx` antes do `createRoot` — é o "antes do
 * React" de que todo o resto do arquivo depende.
 *
 * Idempotente: em dev o React remonta a árvore, e registrar o mesmo listener
 * duas vezes faria o `preventDefault` correr em duplicidade sem necessidade.
 */
export function iniciarCapturaDeInstalacao() {
  if (iniciado) return;
  iniciado = true;

  definir({ standalone: ehStandalone() });

  window.addEventListener('beforeinstallprompt', (e) => {
    // Sem o `preventDefault` o Chrome mostra a própria barra de instalação por
    // cima do app — e o botão na barra superior vira redundante.
    e.preventDefault();
    definir({ evento: e as BeforeInstallPromptEvent });
  });

  window.addEventListener('appinstalled', () => {
    // O evento é do APARELHO, não da janela: quem instalou a partir de uma aba
    // continua numa aba. Por isso `standalone` NÃO vira `true` aqui — só
    // `appDetectado`, que é a pergunta que acabou de ser respondida.
    definir({ evento: null, appDetectado: true });
  });

  // `display-mode` muda em tempo real quando a mesma aba é promovida a janela do
  // app (acontece no desktop, ao instalar com a página aberta).
  const mq = window.matchMedia('(display-mode: standalone)');
  mq.addEventListener('change', () => definir({ standalone: ehStandalone() }));

  void consultarAppsInstalados();
}

/**
 * Pergunta ao sistema se já existe um app nosso instalado.
 *
 * Depende da entrada auto-referente em `related_applications` no
 * `manifest.webmanifest`: sem ela o Chrome devolve lista vazia SEMPRE, e não
 * daria para separar "não instalado" de "instalado, mas você está numa aba".
 */
async function consultarAppsInstalados() {
  const nav = navigator as NavigatorComApps;
  if (typeof nav.getInstalledRelatedApps !== 'function') return; // segue `null`
  try {
    const apps = await nav.getInstalledRelatedApps();
    definir({ appDetectado: apps.some((app) => app.platform === 'webapp') });
  } catch {
    // Fora de contexto seguro, dentro de iframe, ou fora do `scope` do
    // manifesto. Nada a fazer, e `null` ("não dá para saber") é a resposta
    // honesta — melhor do que afirmar que não está instalado.
  }
}

export function assinar(aoMudar: () => void): () => void {
  assinantes.add(aoMudar);
  return () => {
    assinantes.delete(aoMudar);
  };
}

export function ler(): EstadoDeInstalacao {
  return estado;
}

/**
 * Abre o diálogo do navegador. Devolve `true` se a pessoa aceitou.
 *
 * O evento é de uso único: guardá-lo depois de consumido daria um botão que não
 * faz mais nada. Quem recusar verá a oferta de novo numa próxima visita, quando
 * o navegador decidir disparar o evento outra vez.
 */
export async function instalar(): Promise<boolean> {
  const { evento } = estado;
  if (!evento) return false;
  definir({ evento: null });
  await evento.prompt();
  const { outcome } = await evento.userChoice;
  return outcome === 'accepted';
}
