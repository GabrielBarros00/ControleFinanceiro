import * as React from "react"
import { Input as InputPrimitive } from "@base-ui/react/input"

import { cn } from "@/lib/utils"

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <InputPrimitive
      type={type}
      data-slot="input"
      className={cn(
        // h-10 (40px), não h-9: o app tinha TRÊS alturas de controle convivendo
        // — Select 32px, Input 36px e o `<select>` nativo usado dentro de
        // diálogos 40px —, então uma linha de formulário nunca alinhava e o
        // alvo de toque ficava pequeno. 40px é a altura do nativo, que é a que
        // já aparecia nos formulários.
        "h-10 w-full min-w-0 rounded-lg border border-input bg-background px-3 py-2 text-base text-foreground shadow-sm transition-colors outline-none file:inline-flex file:h-6 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-muted-foreground/50 focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm dark:bg-background dark:border-border",
        className
      )}
      {...props}
    />
  )
}

export { Input }
