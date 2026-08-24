import * as React from 'react';
import { assinar, ehIOS, instalar, ler } from '@/lib/install';

/*
 * "Instalar como aplicativo" — a leitura, em React.
 *
 * Toda a mecânica (e o motivo de ela viver FORA do React) está no cabeçalho de
 * `lib/install.ts`. Em uma linha: `beforeinstallprompt` dispara uma vez por
 * carregamento, cedo, e um listener que só nasce quando um componente monta
 * chega tarde demais para sempre.
 *
 * Aqui ficam só as duas coisas que são de React: assinar o store e traduzir o
 * estado cru em algo que a tela saiba mostrar.
 *
 * **iOS:** não existe evento nenhum. A Apple nunca implementou
 * `beforeinstallprompt`, e instalar é um caminho manual — Compartilhar →
 * Adicionar à Tela de Início. A única coisa honesta a fazer é detectar iOS e
 * ENSINAR o caminho. Um botão "Instalar" que não faz nada no iPhone é pior do
 * que não ter botão.
 */

export type EstadoDeInstalacao =
  /** Esta janela JÁ É o app instalado — não há o que oferecer. */
  | 'instalado'
  /** O navegador ofereceu o gancho: dá para instalar com um toque. */
  | 'disponivel'
  /** iOS: dá para instalar, mas só à mão. Mostrar as instruções. */
  | 'manual-ios'
  /** Nem instalado nem instalável (desktop sem suporte, Firefox Android…). */
  | 'indisponivel';

export function useInstallPrompt() {
  const estadoCru = React.useSyncExternalStore(assinar, ler, ler);

  /**
   * Sobre a JANELA atual — se esta tela está rodando dentro do app instalado.
   *
   * Não confundir com `appDetectado`, logo abaixo, que é sobre o APARELHO. As
   * duas divergem no caso mais comum de todos: app instalado, mas aberto pelo
   * navegador.
   */
  const estado: EstadoDeInstalacao = estadoCru.standalone
    ? 'instalado'
    : estadoCru.evento
      ? 'disponivel'
      : ehIOS()
        ? 'manual-ios'
        : 'indisponivel';

  return {
    estado,
    /**
     * Sobre o APARELHO: existe um app instalado?
     *
     * `null` é "este navegador não sabe responder", e não "não". É o que separa
     * um app de verdade (WebAPK) de um mero atalho de tela inicial — o atalho
     * não é registrado como app, então aqui ele aparece como `false`.
     */
    appDetectado: estadoCru.appDetectado,
    instalar,
  };
}
