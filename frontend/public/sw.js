/*
 * Service worker do Controle Financeiro — escrito à mão, sem Workbox.
 *
 * Faz duas coisas, e só estas duas:
 *
 * 1. É o que o Chrome exige para oferecer "Instalar aplicativo" (manifesto
 *    válido + um SW com handler de `fetch`).
 * 2. Guarda a CASCA do app para que, sem rede, a pessoa veja a interface com uma
 *    mensagem honesta em vez do dinossauro do navegador.
 *
 * ## A regra que não se quebra: `/api/` NUNCA é interceptado
 *
 * Este é um app de dinheiro. Um saldo cacheado é pior do que saldo nenhum: o
 * número aparece com a cara de atual, ninguém desconfia, e a decisão é tomada em
 * cima dele. Toda requisição para a API passa direto para a rede — se não houver
 * rede, ela falha, e as telas já sabem mostrar erro (regra ERR-001, ver
 * `components/ui/error-state.tsx`, que existe justamente para falha não virar
 * "R$ 0,00"). O mesmo vale para o WebSocket.
 *
 * ## Por que sem Workbox
 *
 * O `vite-plugin-pwa` traz uma árvore de dependências para gerar 60 linhas, e a
 * CSP do `frontend/nginx.conf` é `default-src 'self'` — worker vindo de `blob:`
 * seria bloqueado. Aqui não há precache manifest porque não é preciso: os
 * arquivos de `/assets/` têm hash no nome e são imutáveis, então cache-first sob
 * demanda dá o mesmo resultado sem gerar lista nenhuma no build.
 */

// Suba a versão para invalidar tudo o que ficou em cache de uma vez. É o único
// botão de emergência de um SW: sem ele, um cache ruim sobrevive no aparelho da
// pessoa e não há como alcançá-lo do servidor.
const VERSAO = 'cf4-v2';
const CACHE_CASCA = `${VERSAO}-casca`;
const CACHE_ASSETS = `${VERSAO}-assets`;

// A casca é o `index.html` (a SPA monta o resto) e o ícone.
const CASCA = ['/', '/index.html', '/icon-192.png'];

self.addEventListener('install', (evento) => {
  evento.waitUntil(
    caches
      .open(CACHE_CASCA)
      .then((cache) => cache.addAll(CASCA))
      // `skipWaiting` para a versão nova assumir sem esperar todas as abas
      // fecharem. É seguro aqui porque o SW não guarda estado entre versões:
      // o pior caso é uma aba antiga buscar um asset que o cache novo ainda não
      // tem, e aí ele vem da rede.
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (evento) => {
  evento.waitUntil(
    caches
      .keys()
      .then((nomes) =>
        Promise.all(
          nomes
            .filter((nome) => !nome.startsWith(VERSAO))
            .map((nome) => caches.delete(nome)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('message', (evento) => {
  // Gancho para a página pedir a troca imediata depois de avisar o usuário.
  if (evento.data === 'pular-espera') self.skipWaiting();
});

/*
 * ---- Aviso de vencimento (ADR 0033) ----
 *
 * Este handler é o que faz o aviso chegar com o app FECHADO — é a razão de o
 * push existir, e o único pedaço do app que roda sem nenhuma aba aberta.
 *
 * `showNotification` é OBRIGATÓRIO. Um push recebido que não mostra notificação
 * é "silent push", e os navegadores punem: o Chrome mostra um aviso genérico
 * ("Este site foi atualizado em segundo plano") e, na reincidência, revoga a
 * permissão da origem. Por isso o `catch` abaixo também notifica — falhar
 * calado aqui custa o canal inteiro.
 */
self.addEventListener('push', (evento) => {
  let dados = {};
  try {
    dados = evento.data ? evento.data.json() : {};
  } catch {
    // Payload que não é JSON (teste manual pelo DevTools, versão futura do
    // servidor). Cai no genérico em vez de estourar — ver o parágrafo acima.
  }

  const titulo = dados.titulo || 'Controle Financeiro';
  const opcoes = {
    body: dados.corpo || 'Você tem uma conta chegando no vencimento.',
    icon: '/icon-192.png',
    // `badge` é o ícone monocromático da barra de status do Android. Sem ele o
    // sistema desenha um quadrado cinza no lugar.
    badge: '/icon-192.png',
    lang: 'pt-BR',
    // `tag` fixa: um aviso novo SUBSTITUI o anterior em vez de empilhar. O
    // servidor já agrupa as contas do dia numa mensagem só, então duas
    // notificações na bandeja significam que a de ontem ficou para trás — e
    // ninguém quer sete cartõezinhos de "conta vencendo" acumulados.
    tag: 'vencimento',
    data: { url: dados.url || '/me/payables' },
  };

  evento.waitUntil(
    self.registration.showNotification(titulo, opcoes).catch(() =>
      self.registration.showNotification('Controle Financeiro', {
        body: 'Você tem uma conta chegando no vencimento.',
        icon: '/icon-192.png',
        tag: 'vencimento',
      }),
    ),
  );
});

self.addEventListener('notificationclick', (evento) => {
  evento.notification.close();
  const destino = (evento.notification.data && evento.notification.data.url) || '/me/payables';

  // Reaproveita uma janela já aberta em vez de abrir outra: quem tem o app
  // instalado e toca no aviso espera voltar para o app que já estava lá, não
  // ganhar uma segunda janela do mesmo app.
  evento.waitUntil(
    self.clients
      .matchAll({ type: 'window', includeUncontrolled: true })
      .then((janelas) => {
        for (const janela of janelas) {
          if (janela.url.includes(destino) && 'focus' in janela) return janela.focus();
        }
        const primeira = janelas[0];
        if (primeira && 'navigate' in primeira) {
          return primeira.navigate(destino).then((j) => j && j.focus());
        }
        return self.clients.openWindow(destino);
      }),
  );
});

self.addEventListener('fetch', (evento) => {
  const { request } = evento;

  // Só GET: POST/PUT/DELETE mudam dado no servidor e não têm o que cachear.
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  // Outra origem (nada hoje, mas a CSP pode mudar): passa reto.
  if (url.origin !== self.location.origin) return;

  // ---- A regra: a API é intocável ----
  //
  // Medido: hoje esta linha é REDUNDANTE. Uma requisição para `/api/` não casa
  // com `/assets/` nem tem `mode: 'navigate'`, então já cairia no fim do handler
  // sem ser tocada — tirar o `return` daqui não muda nada, e o teste de
  // `e2e-prod/pwa.spec.ts` continua verde (foi conferido).
  //
  // Fica assim mesmo, e é deliberado: ela é a guarda para a PRÓXIMA ramificação
  // que alguém acrescentar acima ou abaixo. Um "cache-first para todo GET" —
  // uma linha, e a mais natural de escrever — bota saldo em cache. O teste pega
  // ESSE caso (conferido também: três URLs de `/api/` no Cache Storage e a
  // asserção falha); esta linha o impede antes.
  if (url.pathname.startsWith('/api/')) return;

  // ---- Assets com hash no nome: imutáveis, cache-first ----
  if (url.pathname.startsWith('/assets/')) {
    evento.respondWith(
      caches.match(request).then(
        (emCache) =>
          emCache ||
          fetch(request).then((resposta) => {
            // Só guarda o que deu certo: cachear um 404 ou um 500 congelaria o
            // erro no aparelho até a próxima troca de VERSAO.
            if (resposta.ok) {
              const copia = resposta.clone();
              caches.open(CACHE_ASSETS).then((cache) => cache.put(request, copia));
            }
            return resposta;
          }),
      ),
    );
    return;
  }

  // ---- Navegação: rede primeiro, casca como rede de segurança ----
  //
  // Rede PRIMEIRO, e não cache: o `index.html` referencia os bundles por nome
  // com hash. Servindo um index velho depois de um deploy, ele pediria assets
  // que já não existem e o app abriria em branco.
  if (request.mode === 'navigate') {
    evento.respondWith(
      fetch(request)
        .then((resposta) => {
          if (resposta.ok) {
            const copia = resposta.clone();
            caches.open(CACHE_CASCA).then((cache) => cache.put('/index.html', copia));
          }
          return resposta;
        })
        .catch(() =>
          caches
            .match('/index.html')
            .then((emCache) => emCache || caches.match('/')),
        ),
    );
  }
});
