import * as React from 'react';
import { Download, Smartphone } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog, DialogContent, DialogDescription, DialogTitle,
} from '@/components/ui/dialog';
import { useInstallPrompt } from '@/hooks/use-install-prompt';
import { toast } from '@/stores/toast';

/*
 * Instalar como aplicativo — o botão da barra superior e o cartão de
 * Configurações, juntos porque compartilham a cópia e o estado.
 *
 * A mecânica inteira (por que a captura do evento vive fora do React, e a
 * diferença entre "esta janela é o app" e "este aparelho tem o app") está no
 * cabeçalho de `lib/install.ts`. Aqui é só apresentação.
 */

/**
 * O caminho do iPhone, que é manual.
 *
 * Aparece nos DOIS lugares — a folha do botão e o cartão de Configurações — e é
 * por isso que mora aqui: duplicada, a instrução divergiria na primeira vez que
 * alguém corrigisse o nome de um menu da Apple em um só dos lados.
 */
function PassosIOS() {
  return (
    <div className="space-y-2 text-sm text-muted-foreground">
      <p>No iPhone e no iPad a instalação é pelo Safari, em dois toques:</p>
      <ol className="ml-4 list-decimal space-y-1">
        <li>Toque em <strong className="text-foreground">Compartilhar</strong> (o quadrado com a seta para cima).</li>
        <li>Escolha <strong className="text-foreground">Adicionar à Tela de Início</strong>.</li>
      </ol>
      <p className="text-xs">
        Só funciona no Safari — em outros navegadores do iPhone a opção não aparece.
      </p>
    </div>
  );
}

/**
 * Botão de instalar para a barra superior — a porta que faltava.
 *
 * A oferta existia só no fim de Configurações › Aparência, e ninguém chega lá
 * por acaso. Aqui ela fica em toda tela autenticada, no celular e no desktop.
 *
 * ## Um botão só, não dois
 *
 * O rótulo some abaixo de `sm` por CSS (`hidden sm:inline`), e não por duas
 * cópias com `sm:hidden` + `hidden sm:block`. Duplicar renderizaria DOIS nós
 * interativos com o mesmo nome acessível — a armadilha documentada em
 * `hooks/use-media-query.ts`, em que um `getByRole` passa a achar dois
 * resultados e falhar. O `aria-label` fixo mantém o nome acessível igual nas
 * duas larguras.
 */
export function InstallAppButton() {
  const { estado, instalar } = useInstallPrompt();
  const [passosAbertos, setPassosAbertos] = React.useState(false);

  // `instalado`: esta janela já é o app. `indisponivel`: o navegador não tem o
  // que oferecer (Firefox no Android, desktop sem suporte) — um botão aqui
  // abriria um diálogo que não existe.
  if (estado === 'instalado' || estado === 'indisponivel') return null;

  const aoClicar = async () => {
    if (estado === 'manual-ios') {
      setPassosAbertos(true);
      return;
    }
    if (await instalar()) {
      toast.success('Aplicativo instalado', 'Ele já está na sua tela de início.');
    }
  };

  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        aria-label="Instalar aplicativo"
        onClick={aoClicar}
        className="gap-1.5"
      >
        <Download className="h-4 w-4" />
        <span className="hidden sm:inline">Instalar app</span>
      </Button>

      <Dialog open={passosAbertos} onOpenChange={setPassosAbertos}>
        <DialogContent className="sm:max-w-md">
          <DialogTitle>Instalar aplicativo</DialogTitle>
          <DialogDescription>
            Para abrir em tela cheia, com ícone próprio, sem a barra de endereço.
          </DialogDescription>
          <PassosIOS />
        </DialogContent>
      </Dialog>
    </>
  );
}

/**
 * "Aplicativo no celular", em Configurações › Aparência — porque é disso que se
 * trata: onde e como o app aparece, ao lado da escolha de tema.
 *
 * ## Por que ele agora DIAGNOSTICA em vez de só oferecer
 *
 * O mesmo manifesto produz dois resultados diferentes no Android, e a diferença
 * é invisível de dentro do app até alguém medi-la: instalar de verdade gera um
 * **WebAPK** (ícone limpo, app no gaveteiro); quando a ponte Chrome↔Play
 * Services falha, ou quando a pessoa escolheu "Adicionar à tela inicial" em vez
 * de "Instalar app", o Chrome cai num mero **atalho**, que ganha um Chrome
 * pequeno no canto do ícone.
 *
 * Nenhum código conserta isso — a decisão é do aparelho. O que dá para fazer é
 * dizer em qual dos dois estados a pessoa está, e é o que as duas linhas de
 * estado fazem. Sem elas, a única resposta possível a "por que meu ícone tem um
 * Chrome no canto?" seria adivinhação.
 */
export function InstallAppCard() {
  const { estado, appDetectado, instalar } = useInstallPrompt();

  return (
    <Card className="bg-card border-border shadow-xl">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Smartphone className="h-5 w-5 text-primary" />
          Aplicativo no celular
        </CardTitle>
        <CardDescription>
          Instale para abrir em tela cheia, com ícone próprio, sem a barra de endereço.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <dl className="space-y-1 text-sm">
          <div className="flex flex-wrap gap-x-2">
            <dt className="text-muted-foreground">Abrindo em:</dt>
            <dd className="font-medium">
              {estado === 'instalado' ? 'janela própria do aplicativo' : 'aba do navegador'}
            </dd>
          </div>
          <div className="flex flex-wrap gap-x-2">
            <dt className="text-muted-foreground">App instalado neste aparelho:</dt>
            <dd className="font-medium">
              {appDetectado === null
                ? 'não dá para saber neste navegador'
                : appDetectado
                  ? 'sim'
                  : 'não'}
            </dd>
          </div>
        </dl>

        {estado === 'disponivel' && (
          <Button
            type="button"
            onClick={async () => {
              if (await instalar()) {
                toast.success('Aplicativo instalado', 'Ele já está na sua tela de início.');
              }
            }}
            className="h-11 w-full gap-2 sm:w-auto"
          >
            <Download className="h-4 w-4" /> Instalar aplicativo
          </Button>
        )}

        {estado === 'manual-ios' && <PassosIOS />}

        {/* `<details>` nativo: o texto interessa a quem está com o problema na
            mão, e ninguém mais precisa lê-lo toda vez que abre Aparência. */}
        <details className="rounded-lg border border-border p-3 text-sm">
          <summary className="cursor-pointer font-medium">
            Meu ícone tem um Chrome pequeno no canto — por quê?
          </summary>
          <div className="mt-3 space-y-2 text-muted-foreground">
            <p>
              Porque o que foi criado ali é um <strong className="text-foreground">atalho</strong>,
              não o aplicativo. No Android, instalar de verdade faz o Chrome pedir ao Google um
              pacote assinado só para este site — aí o ícone fica limpo e ele aparece na lista de
              aplicativos do aparelho. Quando isso não dá certo, o Chrome cria um atalho e o marca
              com o próprio logo.
            </p>
            <p>
              Acontece quando a instalação partiu de "Adicionar à tela inicial" ou "Criar atalho"
              em vez de <strong className="text-foreground">"Instalar app"</strong>, quando ela foi
              feita por outro navegador (Samsung Internet, Firefox), ou quando a Play Store estava
              deslogada, o Chrome desatualizado ou a rede ruim naquele instante.
            </p>
            <p>Para refazer: apague o ícone atual, confira que a Play Store está conectada à sua
              conta Google e que o Chrome está atualizado, abra o site
              <strong className="text-foreground"> no Chrome</strong> e use "Instalar app".
              A linha "App instalado neste aparelho" aqui em cima dirá se funcionou.
            </p>
          </div>
        </details>
      </CardContent>
    </Card>
  );
}
