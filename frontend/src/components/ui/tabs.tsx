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
        'inline-flex h-9 w-fit items-center justify-center rounded-lg bg-muted p-1 text-muted-foreground',
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
        'inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1 text-sm font-medium text-muted-foreground transition-all hover:text-foreground',
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
