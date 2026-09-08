import * as React from 'react';
import * as TabsPrimitive from '@radix-ui/react-tabs';
import { cn } from '@/lib/utils';

/*
 * Tabs — sobre Radix (data-[state=active] confiável). Antes era Base UI, cujo
 * `data-horizontal`/`data-active` não casava com o Tailwind → aba invisível e
 * sem realce do ativo. Radix resolve os dois (docs/frontend-redesign/05 §8).
 */
function Tabs({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Root>) {
  return <TabsPrimitive.Root className={cn('flex flex-col gap-4', className)} {...props} />;
}

function TabsList({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      className={cn(
        /*
         * `max-w-full overflow-x-auto` é o que impede a lista de empurrar a
         * página. Era `w-fit` sem rolagem, e cada `TabsTrigger` tem
         * `whitespace-nowrap`: as 4 abas de Relatórios somam ~388px e as 6 de
         * /admin somam ~540px, então em 390px de tela a última aba ficava
         * CORTADA e inalcançável (vê-se em screenshots/mobile-relatorios-*.png,
         * com "Orçamento" partido na borda) e o resto do app ganhava rolagem
         * horizontal.
         *
         * `justify-start` porque com rolagem o `justify-center` faria o
         * conteúdo começar fora da vista quando ele não coubesse.
         */
                // `h-11` no celular (44px), `sm:h-9` no desktop: as abas mediam 28px de
        // altura no toque — abaixo do mínimo confortável, e o extrato já tinha
        // recebido 40px nos botões de editar/excluir pelo mesmo motivo. Quem usa
        // com o polegar erra o alvo e vai para a aba vizinha.
        'inline-flex h-11 w-fit max-w-full shrink-0 items-center justify-start overflow-x-auto rounded-lg bg-muted p-1 text-muted-foreground scrollbar-none sm:h-9',
        className,
      )}
      {...props}
    />
  );
}

function TabsTrigger({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        // A aba INATIVA foi o que o axe reprovou (4,39:1 sobre o `--muted` da
        // lista). O conserto foi no token `--muted-foreground` (index.css), não
        // aqui: `text-foreground/80` seria pior que inútil — em Tailwind v3 o
        // modificador de opacidade não compila sobre cor em `var()` e a classe
        // some em silêncio, como as variantes `data-*` bare.
        // `shrink-0`: agora que a lista rola, sem isto o flex espremeria os
        // triggers até o texto sumir em vez de deixar a faixa rolar.
        'inline-flex h-full shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1 text-sm font-medium text-muted-foreground transition-all hover:text-foreground',
        'focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring',
        'disabled:pointer-events-none disabled:opacity-50',
        'data-[state=active]:bg-card data-[state=active]:text-foreground data-[state=active]:shadow-sm',
        className,
      )}
      {...props}
    />
  );
}

function TabsContent({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Content>) {
  return <TabsPrimitive.Content className={cn('flex-1 outline-hidden', className)} {...props} />;
}

export { Tabs, TabsList, TabsTrigger, TabsContent };
