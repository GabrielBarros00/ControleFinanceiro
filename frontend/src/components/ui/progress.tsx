import * as React from "react"
import * as ProgressPrimitive from "@radix-ui/react-progress"

import { cn } from "@/lib/utils"

const Progress = React.forwardRef<
  React.ElementRef<typeof ProgressPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root>
>(({ className, value, ...props }, ref) => (
  <ProgressPrimitive.Root
    ref={ref}
    className={cn(
      "relative h-2 w-full overflow-hidden rounded-full bg-muted",
      className
    )}
    {...props}
  >
    {/* `bg-primary` e não um roxo avulso: a barra de progresso é a marca em
        movimento, e `bg-purple-500` era um segundo roxo — próximo do índigo do
        tema, mas não igual, e cego para a troca claro/escuro (o `--primary` do
        tema escuro é bem mais claro, de propósito). Mesma história do trilho,
        que era `bg-slate-900/50`: uma cor fixa e escura num componente que
        aparece nos dois temas. */}
    <ProgressPrimitive.Indicator
      className="h-full w-full flex-1 bg-primary transition-all"
      style={{ transform: `translateX(-${100 - (value || 0)}%)` }}
    />
  </ProgressPrimitive.Root>
))
Progress.displayName = ProgressPrimitive.Root.displayName

export { Progress }
