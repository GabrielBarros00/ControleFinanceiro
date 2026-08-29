import * as React from 'react';
import { useQuery } from '@tanstack/react-query';

import { apiClient } from '@/api/client';
import { ehIOS } from '@/lib/install';
import { useInstallPrompt } from '@/hooks/use-install-prompt';

/*
 * Ativar o aviso de vencimento neste navegador (ADR 0033).
 *
 * ## O estado que importa não é booleano
 *
 * "Ativado ou não" esconde os cinco casos que a tela precisa tratar de formas
 * diferentes — e tratá-los como um só produz exatamente o botão que não
 * funciona:
 *
 * - `indisponivel`  o navegador não faz push (nada a oferecer);
 * - `precisa-instalar`  iPhone em ABA. A Apple só permite push em app da Tela
 *   de Início, então aqui o caminho é instalar ANTES, e oferecer "Ativar"
 *   seria oferecer um botão que não pode funcionar;
 * - `bloqueado`  a pessoa já negou no navegador. `requestPermission()` volta
 *   `denied` na hora, sem perguntar nada: só resta ensinar a reverter;
 * - `desativado`  dá para ativar. É o único estado em que o convite aparece;
 * - `ativado`  já está inscrito neste aparelho.
 *
 * ## A permissão se pede UMA vez
 *
 * `Notification.requestPermission()` é irreversível na prática. Negado, o
 * navegador não deixa perguntar de novo e o conserto vira um caminho nas
 * configurações que ninguém acha sozinho. Por isso este hook NÃO pede nada ao
 * montar: quem chama `ativar()` é o clique da pessoa, depois de ela ter lido o
 * que ganha com isso.
 */

export type EstadoDoPush =
  | 'indisponivel'
  | 'precisa-instalar'
  | 'bloqueado'
  | 'desativado'
  | 'ativado';

interface PushConfig {
  enabled: boolean;
  public_key: string | null;
}

/** base64url -> Uint8Array, que é o formato que `applicationServerKey` exige. */
function chaveParaBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const base64 = (base64url + '='.repeat((4 - (base64url.length % 4)) % 4))
    .replace(/-/g, '+')
    .replace(/_/g, '/');
  const cru = atob(base64);
  // `new Uint8Array(new ArrayBuffer(n))` e não `Uint8Array.from(...)`: aquele
  // devolve `Uint8Array<ArrayBufferLike>`, que abrange `SharedArrayBuffer` e por
  // isso não satisfaz o `BufferSource` de `applicationServerKey`. Alocar o
  // buffer explicitamente fixa o tipo.
  const bytes = new Uint8Array(new ArrayBuffer(cru.length));
  for (let i = 0; i < cru.length; i += 1) bytes[i] = cru.charCodeAt(i);
  return bytes;
}

const suportado = () =>
  typeof window !== 'undefined' &&
  'serviceWorker' in navigator &&
  'PushManager' in window &&
  'Notification' in window;

export function usePush() {
  const { estado: estadoDeInstalacao } = useInstallPrompt();
  const [inscrito, setInscrito] = React.useState<boolean | null>(null);
  const [ocupado, setOcupado] = React.useState(false);
  // Lido uma vez e mantido em estado: `Notification.permission` não dispara
  // evento nenhum ao mudar, então quem muda é quem atualiza.
  const [permissao, setPermissao] = React.useState<NotificationPermission | null>(
    suportado() ? Notification.permission : null,
  );

  const { data: config } = useQuery<PushConfig>({
    queryKey: ['push', 'config'],
    queryFn: async () => (await apiClient.get('/me/push/config')).data,
    // Sem chave VAPID no servidor a resposta não muda entre telas; e com chave,
    // ela só muda num deploy.
    staleTime: 5 * 60 * 1000,
  });

  React.useEffect(() => {
    if (!suportado()) {
      setInscrito(false);
      return;
    }
    let vivo = true;
    navigator.serviceWorker.ready
      .then((reg) => reg.pushManager.getSubscription())
      .then((sub) => vivo && setInscrito(!!sub))
      .catch(() => vivo && setInscrito(false));
    return () => {
      vivo = false;
    };
  }, []);

  const estado: EstadoDoPush = React.useMemo(() => {
    if (!suportado() || config?.enabled === false) return 'indisponivel';
    // iPhone fora do app instalado: a Apple não permite push em aba. Este teste
    // vem ANTES do de permissão porque ali `Notification.permission` é
    // 'default' e pareceria que basta pedir.
    if (ehIOS() && estadoDeInstalacao !== 'instalado') return 'precisa-instalar';
    if (permissao === 'denied') return 'bloqueado';
    if (inscrito) return 'ativado';
    return 'desativado';
  }, [config?.enabled, estadoDeInstalacao, permissao, inscrito]);

  // Extraída para um identificador simples: com `config?.public_key` na lista de
  // dependências, o React Compiler não consegue preservar a memoização (o
  // encadeamento opcional não é uma referência estável que ele saiba rastrear).
  const chavePublica = config?.public_key ?? null;

  /** Pede a permissão e inscreve. Só deve ser chamada a partir de um clique. */
  const ativar = React.useCallback(async (): Promise<boolean> => {
    if (!suportado() || !chavePublica) return false;
    setOcupado(true);
    try {
      const resposta = await Notification.requestPermission();
      setPermissao(resposta);
      if (resposta !== 'granted') return false;

      const registro = await navigator.serviceWorker.ready;
      const inscricao =
        (await registro.pushManager.getSubscription()) ??
        (await registro.pushManager.subscribe({
          // Obrigatório `true`: os navegadores não aceitam mais inscrição que
          // possa receber push sem mostrar notificação.
          userVisibleOnly: true,
          applicationServerKey: chaveParaBytes(chavePublica),
        }));

      // `toJSON()` já entrega `{endpoint, keys:{p256dh, auth}}`, que é
      // exatamente o corpo que a rota espera.
      await apiClient.post('/me/push/subscriptions', inscricao.toJSON());
      setInscrito(true);
      return true;
    } catch {
      return false;
    } finally {
      setOcupado(false);
    }
  }, [chavePublica]);

  const desativar = React.useCallback(async (): Promise<void> => {
    if (!suportado()) return;
    setOcupado(true);
    try {
      const registro = await navigator.serviceWorker.ready;
      const inscricao = await registro.pushManager.getSubscription();
      if (inscricao) {
        // Avisa o servidor ANTES de cancelar no navegador: cancelado primeiro,
        // perde-se o endpoint e a linha ficaria órfã no banco até o serviço de
        // push responder 410 — o que pode nunca acontecer.
        await apiClient.delete('/me/push/subscriptions', {
          data: { endpoint: inscricao.endpoint },
        });
        await inscricao.unsubscribe();
      }
      setInscrito(false);
    } finally {
      setOcupado(false);
    }
  }, []);

  return { estado, ativar, desativar, ocupado };
}
