import axios from 'axios';
import type { QueryClient } from '@tanstack/react-query';
import { useAuthStore } from '@/stores';

// O QueryClient é criado no App; o interceptor precisa dele para descartar o
// cache quando a sessão morre de vez (mesma limpeza do logout explícito). Sem
// isto, expirar a sessão deixava os dados do usuário em memória para a próxima
// pessoa que entrasse no mesmo navegador.
let queryClientRef: QueryClient | null = null;

export function registerQueryClient(client: QueryClient): void {
  queryClientRef = client;
}

export const baseURL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

/*
 * Prazo de TODA requisição — e a ausência dele era a tela preta.
 *
 * O relato: "passo um tempo sem entrar, volto, e a tela fica preta, como se
 * tentasse carregar". Reproduzido: basta a primeira leva de requisições sair por
 * uma conexão que morreu enquanto o aparelho dormia (o Wi-Fi que virou 4G, o NAT
 * que expirou, a aba descongelada). Ela não volta nem com sucesso nem com erro,
 * e sem prazo o axios espera PARA SEMPRE: o `/auth/me` da carga fica pendente, e
 * o guard de rota mostra "Carregando sua sessão…" no fundo escuro sem nunca
 * sair dali. O F5 resolvia porque abre conexões novas.
 *
 * Com prazo, a requisição pendurada vira falha de rede, o react-query tenta de
 * novo (já por outra conexão) e, se nem assim der, a tela diz que não conseguiu
 * falar com o servidor e oferece o botão — em vez de girar sem fim.
 *
 * 30 s cabe com folga qualquer resposta saudável deste backend. Arquivo (envio
 * de nota, extrato, foto; download de anexo) ganha mais, porque o corpo viaja
 * pela rede do celular — ver o interceptor de requisição abaixo.
 */
export const PRAZO_PADRAO_MS = 30_000;
export const PRAZO_DE_ARQUIVO_MS = 120_000;
/** A renovação de sessão é um POST sem corpo: se passar disto, a conexão morreu. */
export const PRAZO_DA_RENOVACAO_MS = 15_000;

export const apiClient = axios.create({
  baseURL,
  withCredentials: true, // Crucial for JWT cookies
  timeout: PRAZO_PADRAO_MS,
  headers: {
    'Content-Type': 'application/json',
  },
  // FastAPI lê lista como parâmetro REPETIDO (`?source=a&source=b`); o padrão do
  // Axios serializa `source[]=a`, que o backend ignora SEM ERRO — 200, resposta
  // completa, filtro nenhum. No Extrato global o botão ficava marcado, a URL da
  // tela dizia `?source=income` e a tabela continuava mostrando tudo, totais
  // inclusive. O teste que existia mockava o hook e só via o array em memória:
  // a serialização HTTP nunca era exercitada (ver use-overview.serializacao).
  paramsSerializer: { indexes: null },
});

apiClient.interceptors.request.use((config) => {
  const envioDeArquivo = typeof FormData !== 'undefined' && config.data instanceof FormData;
  if (envioDeArquivo || config.responseType === 'blob') {
    config.timeout = Math.max(config.timeout ?? 0, PRAZO_DE_ARQUIVO_MS);
  }
  return config;
});

// Rotas de auth nunca disparam refresh (evita loop em login/refresh inválidos)
const AUTH_URLS = [
  '/auth/login',
  '/auth/register',
  '/auth/refresh',
  '/auth/logout',
  '/auth/forgot-password',
  '/auth/reset-password',
];

let renovacaoEmCurso: Promise<void> | null = null;

/**
 * O servidor RECUSOU a renovação (401/403): a sessão acabou de verdade.
 *
 * Qualquer outra falha — rede, prazo estourado, 502 do túnel durante um deploy —
 * diz só que não deu para perguntar. Tratar as duas como a primeira era o
 * defeito: um soluço de rede na volta do celular deslogava quem tinha sessão
 * válida e mostrava "Bem-vindo, entre com suas credenciais" (reproduzido com um
 * 502 na renovação).
 */
export function renovacaoRecusada(erro: unknown): boolean {
  const status = (erro as { response?: { status?: number } })?.response?.status;
  return status === 401 || status === 403;
}

/** A sessão morreu: o mesmo que o logout explícito faz com o que está em memória. */
function encerrarSessaoLocal(): void {
  useAuthStore.getState().logout();
  /*
   * E é PRECISO derrubar também a `auth-me` do react-query — o store
   * sozinho não basta, e essa era a causa do "app travado".
   *
   * O comentário que existia aqui dizia "o ProtectedRoute redireciona ao
   * ver que não há usuário". Isso deixou de ser verdade quando o guard
   * passou a ler `useAuth()` (react-query) em vez do espelho em Zustand —
   * mudança certa, feita para resolver outra corrida, que deixou esta
   * linha órfã. Resultado medido: com o app ABERTO e a sessão expirando,
   * o guard continuava vendo `auth-me` no cache com dados válidos, dava a
   * sessão por viva e a tela girava para sempre. Só um F5 saía disso, e o
   * usuário não tinha como saber disso.
   *
   * `setQueryData(null)` e NÃO `removeQueries`: remover uma query com
   * observador montado faz o react-query refazê-la na hora, e o laço
   * `/auth/me` → 401 → `/auth/refresh` → 401 → … volta (é o defeito que o
   * `predicate` logo abaixo foi escrito para evitar). Definir o dado como
   * nulo deixa a query parada, com a resposta correta: não há sessão.
   */
  queryClientRef?.setQueryData(['auth-me'], null);
  // Descarta o cache do usuário que saiu — MENOS a própria `auth-me`.
  //
  // `queryClient.clear()` removia tudo, inclusive ela. E remover uma query
  // que tem observador montado faz o react-query montá-la de novo na hora:
  // `/auth/me` → 401 → `/auth/refresh` → 401 → clear() → `/auth/me` …
  // Era um laço fechado, dezenas de requisições por segundo, com a tela
  // presa no spinner porque a sessão nunca resolvia. Deixando a `auth-me`
  // no cache, ela fica em estado de ERRO — que é a resposta correta
  // ("não há sessão") e não dispara nada.
  queryClientRef?.removeQueries({
    predicate: (query) => query.queryKey[0] !== 'auth-me',
  });
}

/**
 * Uma renovação por vez — na aba E entre abas.
 *
 * O backend gira o refresh token a cada uso e trata a reapresentação de um token
 * já girado como ROUBO: revoga a família inteira (ADR 0013). Então duas
 * renovações com o mesmo cookie não são desperdício, são logout marcado para
 * dali a 30 minutos. E elas aconteciam na volta do aparelho:
 *
 * - na mesma aba, o WebSocket que reconectava com 4401 chamava `/auth/refresh`
 *   por conta própria, ao mesmo tempo que as consultas da tela, com 401, faziam o
 *   mesmo por aqui;
 * - entre abas (ou a janela do app instalado e uma aba do navegador), cada uma
 *   tinha o seu "uma por vez".
 *
 * Na aba, a promessa compartilhada; entre abas, uma trava do navegador (Web
 * Locks): a segunda espera a primeira terminar e sai com o cookie NOVO. Onde a
 * API não existe, fica só a proteção da aba.
 */
export function renovarSessao(): Promise<void> {
  renovacaoEmCurso ??= comTravaEntreAbas(() =>
    apiClient.post('/auth/refresh', undefined, { timeout: PRAZO_DA_RENOVACAO_MS }),
  )
    .then(() => undefined)
    .catch((erro: unknown) => {
      if (renovacaoRecusada(erro)) encerrarSessaoLocal();
      throw erro;
    })
    .finally(() => {
      renovacaoEmCurso = null;
    });
  return renovacaoEmCurso;
}

function comTravaEntreAbas<T>(tarefa: () => Promise<T>): Promise<T> {
  const travas = typeof navigator !== 'undefined' ? navigator.locks : undefined;
  if (typeof travas?.request !== 'function') return tarefa();
  return travas.request('cf-renovar-sessao', tarefa);
}

// Interceptor 401: renova a sessão via cookie refresh_token e repete a request
// original. Várias 401 simultâneas esperam a MESMA renovação.
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;
    const status = error.response?.status;
    const url: string = original?.url ?? '';
    const isAuthUrl = AUTH_URLS.some((u) => url.includes(u));

    if (status === 401 && original && !original._retry && !isAuthUrl) {
      original._retry = true;
      try {
        await renovarSessao();
      } catch (erroDaRenovacao) {
        // Sessão recusada: o 401 original é a resposta certa, e a limpeza já
        // foi feita. Falha de rede na renovação: devolve ELA — quem consultou
        // precisa ver "sem conexão" (e tentar de novo), não "deslogado".
        return Promise.reject(renovacaoRecusada(erroDaRenovacao) ? error : erroDaRenovacao);
      }
      return apiClient(original);
    }
    return Promise.reject(error);
  }
);
