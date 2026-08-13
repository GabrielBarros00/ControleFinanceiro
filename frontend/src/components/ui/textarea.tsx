import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * Campo de texto multi-linha.
 *
 * Não existia: "Descrição" e "Observação" eram `<Input>` de uma linha, então o
 * texto rolava horizontalmente dentro de um campo de 36px e não havia como ver
 * o que já tinha sido escrito. `field-sizing-content` cresce com o conteúdo nos
 * navegadores que o suportam, e `min-h` garante o piso nos demais.
 *
 * Mesma pele do `Input` (altura de linha, borda, foco) para não introduzir uma
 * quarta aparência de controle no formulário.
 */
function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "min-h-20 w-full min-w-0 rounded-lg border border-input bg-background px-3 py-2 text-base text-foreground shadow-sm transition-colors outline-hidden placeholder:text-muted-foreground/50 focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm dark:bg-background dark:border-border",
        className
      )}
      {...props}
    />
  )
}

export { Textarea }
