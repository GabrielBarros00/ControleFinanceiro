import * as React from "react"
import { Button as ButtonPrimitive } from "@base-ui/react/button"
import { cva, type VariantProps } from "class-variance-authority"
import { Loader2 } from "lucide-react"

import { useAcaoPendente } from "@/hooks/use-acao-pendente"
import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "group/button inline-flex shrink-0 items-center justify-center rounded-lg border border-transparent bg-clip-padding text-sm font-medium whitespace-nowrap transition-all outline-hidden select-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 active:not-aria-[haspopup]:translate-y-px disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-[3px] aria-invalid:ring-destructive/20 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground [a]:hover:bg-primary/80",
        outline:
          "border-border bg-background hover:bg-muted hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground dark:border-input dark:bg-muted/50 dark:hover:bg-muted",
        secondary:
          "bg-secondary text-secondary-foreground hover:bg-secondary/80 aria-expanded:bg-secondary aria-expanded:text-secondary-foreground",
        ghost:
          "hover:bg-muted hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground dark:hover:bg-muted/50",
        destructive:
          "bg-destructive/10 text-destructive hover:bg-destructive/20 focus-visible:border-destructive/40 focus-visible:ring-destructive/20 dark:bg-destructive/20 dark:hover:bg-destructive/30 dark:focus-visible:ring-destructive/40",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default:
          "h-8 gap-1.5 px-2.5 has-data-[icon=inline-end]:pr-2 has-data-[icon=inline-start]:pl-2",
        xs: "h-6 gap-1 rounded-[min(var(--radius-md),10px)] px-2 text-xs in-data-[slot=button-group]:rounded-lg has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 [&_svg:not([class*='size-'])]:size-3",
        sm: "h-7 gap-1 rounded-[min(var(--radius-md),12px)] px-2.5 text-[0.8rem] in-data-[slot=button-group]:rounded-lg has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 [&_svg:not([class*='size-'])]:size-3.5",
        lg: "h-9 gap-1.5 px-2.5 has-data-[icon=inline-end]:pr-2 has-data-[icon=inline-start]:pl-2",
        icon: "size-8",
        "icon-xs":
          "size-6 rounded-[min(var(--radius-md),10px)] in-data-[slot=button-group]:rounded-lg [&_svg:not([class*='size-'])]:size-3",
        "icon-sm":
          "size-7 rounded-[min(var(--radius-md),12px)] in-data-[slot=button-group]:rounded-lg",
        "icon-lg": "size-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

type ButtonProps = Omit<ButtonPrimitive.Props, "onClick"> &
  VariantProps<typeof buttonVariants> & {
    /** Pode devolver uma promessa: o botão se tranca até ela assentar. */
    onClick?: (event: React.MouseEvent<HTMLButtonElement>) => unknown
    /** Trava explícita, para quando o clique não é quem dispara a ação. */
    pending?: boolean
  }

/**
 * O botão que se tranca sozinho enquanto a ação não termina.
 *
 * O sintoma que trouxe isto até aqui foi "Convidar": nada acontecia na tela
 * entre o clique e a resposta, então parecia que o clique não tinha pego, e a
 * pessoa clicava de novo — mandando dois convites.
 *
 * A causa não era aquele botão. Os 19 hooks devolviam apenas `mutateAsync` e
 * jogavam fora o `isPending` de cada mutação, então NENHUM botão do app tinha
 * como saber que havia ação em voo, mesmo que quisesse. Consertar botão por
 * botão trataria os 149 de hoje e deixaria o próximo nascer com o mesmo
 * defeito; por isso a trava mora aqui, onde todos passam.
 *
 * A regra é uma só: **se o `onClick` devolve uma promessa, o botão se
 * desabilita e mostra um spinner até ela assentar** — resolvida OU rejeitada.
 * Não engolimos a rejeição: ela segue para quem chamou, senão o `catch` que
 * levanta o toast de erro pararia de rodar.
 *
 * Duas travas, e não uma: o `disabled` cobre o clique depois do re-render, e a
 * trava por `ref` cobre a janela ANTES dele — dois cliques rápidos entram no
 * mesmo ciclo do React, e o estado ainda não mudou quando o segundo chega.
 *
 * Quando o clique não é quem dispara a ação — botão `type="submit"`, em que
 * quem submete é o `<form>` — use a prop `pending`.
 */
function Button({
  className,
  variant = "default",
  size = "default",
  onClick,
  pending,
  disabled,
  children,
  ...props
}: ButtonProps) {
  const { disparar, pendente } = useAcaoPendente(onClick)
  const ocupado = pending ?? pendente
  const soIcone = typeof size === "string" && size.startsWith("icon")

  return (
    <ButtonPrimitive
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      disabled={disabled || ocupado}
      aria-busy={ocupado || undefined}
      onClick={disparar}
      {...props}
    >
      {ocupado ? <Loader2 className="animate-spin" aria-hidden="true" /> : null}
      {/* Num botão só-de-ícone, spinner E ícone juntos estouram a caixa de
          32px — ali o spinner toma o lugar do ícone. */}
      {ocupado && soIcone ? null : children}
    </ButtonPrimitive>
  )
}

export { Button, buttonVariants }
export type { ButtonProps }
