import * as React from "react"
import * as DialogPrimitive from "@radix-ui/react-dialog"
import { X } from "lucide-react"

import { cn } from "@/lib/utils"
import { useFecharComVoltar } from "@/hooks/use-fechar-com-voltar"

/**
 * `Dialog` — o `Root` do Radix mais uma regra do celular: **voltar fecha a
 * camada, não sai da página**.
 *
 * Ficar aqui, e não em cada diálogo, é o ponto: quem reportou o defeito viu na
 * gaveta "Mais", mas ele valia para toda sobreposição do app (verificado também
 * em "Nova despesa"). São 12 diálogos; corrigir um por um é garantir que o
 * décimo terceiro nasça errado.
 *
 * O hook só entra quando há `onOpenChange` — ou seja, quando o diálogo pode ser
 * fechado. O onboarding é bloqueante de propósito (sem X, sem Esc, sem clique
 * fora) e não passa a função; para ele, "voltar" continua sendo navegação, que
 * é o comportamento correto para uma porta que ainda não foi atravessada.
 */
function Dialog({ open, onOpenChange, ...props }: DialogPrimitive.DialogProps) {
  const fechar = React.useCallback(() => onOpenChange?.(false), [onOpenChange]);
  useFecharComVoltar(!!open && !!onOpenChange, fechar);
  return <DialogPrimitive.Root open={open} onOpenChange={onOpenChange} {...props} />;
}

const DialogTrigger = DialogPrimitive.Trigger

const DialogPortal = DialogPrimitive.Portal

const DialogClose = DialogPrimitive.Close

const DialogOverlay = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn(
      "fixed inset-0 z-50 bg-black/80  data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
      className
    )}
    {...props}
  />
))
DialogOverlay.displayName = DialogPrimitive.Overlay.displayName

interface DialogContentProps
  extends React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> {
  /**
   * Mostra o "X" de fechar (padrão). Passe `false` em diálogo BLOQUEANTE (ex.:
   * onboarding) — esconder por CSS não serve: o botão continua no DOM, focável
   * pelo Tab e anunciado pelo leitor de tela, oferecendo uma saída que não existe.
   */
  showCloseButton?: boolean;
}

const DialogContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  DialogContentProps
>(({ className, children, showCloseButton = true, ...props }, ref) => (
  <DialogPortal>
    <DialogOverlay />
    <DialogPrimitive.Content
      ref={ref}
      className={cn(
        "fixed z-50 grid gap-4 border bg-card p-4 shadow-lg duration-200 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 sm:p-6",
        // Mobile: bottom sheet (sobe de baixo, cantos superiores arredondados).
        //
        // O `pb-` com `env(safe-area-inset-bottom)` é o que tira o último
        // controle do formulário de baixo do indicador de home do iPhone (e da
        // barra de gestos do Android). `max()` porque em aparelho sem recorte o
        // inset é 0 e o rodapé ficaria colado na borda.
        "inset-x-0 bottom-0 max-h-[92vh] w-full overflow-y-auto rounded-t-2xl pb-[max(1.25rem,env(safe-area-inset-bottom))] data-[state=closed]:slide-out-to-bottom data-[state=open]:slide-in-from-bottom",
        // >= sm: dialog centralizado
        "sm:inset-x-auto sm:bottom-auto sm:left-[50%] sm:top-[50%] sm:max-h-[85vh] sm:max-w-lg sm:translate-x-[-50%] sm:translate-y-[-50%] sm:rounded-lg sm:pb-6 sm:data-[state=closed]:slide-out-to-left-1/2 sm:data-[state=closed]:slide-out-to-top-[48%] sm:data-[state=open]:slide-in-from-left-1/2 sm:data-[state=open]:slide-in-from-top-[48%] sm:data-[state=closed]:zoom-out-95 sm:data-[state=open]:zoom-in-95",
        className
      )}
      {...props}
    >
      {children}
      {/* O alvo era o ícone nu: 16×16 px, o menor botão do app inteiro, num
          diálogo que no celular é bottom sheet e se fecha com o polegar.
          Agora são 40×40 — o ícone continua com 16, só ganhou área. */}
      {showCloseButton && (
        <DialogPrimitive.Close className="absolute right-2 top-2 flex h-10 w-10 items-center justify-center rounded-lg opacity-70 ring-offset-background transition-opacity hover:bg-muted hover:opacity-100 focus:outline-hidden focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:pointer-events-none data-[state=open]:text-muted-foreground sm:right-3 sm:top-3">
          <X className="h-4 w-4" />
          <span className="sr-only">Fechar</span>
        </DialogPrimitive.Close>
      )}
    </DialogPrimitive.Content>
  </DialogPortal>
))
DialogContent.displayName = DialogPrimitive.Content.displayName

const DialogHeader = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "flex flex-col space-y-1.5 text-center sm:text-left",
      className
    )}
    {...props}
  />
)
DialogHeader.displayName = "DialogHeader"

/**
 * Rodapé do diálogo — e ele é FIXO, não rola com o conteúdo.
 *
 * O `DialogContent` é o contêiner de rolagem (`overflow-y-auto`, teto de 85vh no
 * desktop e 92vh no celular), e até aqui as ações rolavam junto com o resto. Em
 * "Nova Despesa" — o formulário mais longo do app — isso significava que o botão
 * "Salvar Despesa" nascia FORA DA TELA em toda resolução menos 1920×1080:
 * 150px abaixo da borda num notebook de 768px de altura, 322px abaixo num
 * celular. A pessoa abria o formulário mais importante do produto e não via o
 * botão que o conclui.
 *
 * `sticky bottom-0` dentro do próprio contêiner de rolagem resolve sem mexer no
 * layout de ninguém: onde o conteúdo cabe, o rodapé fica exatamente onde ficava;
 * onde não cabe, ele para na borda de baixo em vez de sair de vista.
 *
 * As margens negativas fazem a faixa sangrar até as bordas do diálogo (que tem
 * `p-4 sm:p-6`), para a linha divisória atravessar de ponta a ponta em vez de
 * flutuar no meio com dois vãos nas laterais. O `bg-card` é obrigatório: sem
 * fundo opaco, o conteúdo rolaria POR BAIXO do rodapé e apareceria através dele.
 *
 * O deslocamento de baixo é NEGATIVO e vale exatamente o `padding-bottom` do
 * `DialogContent` (24px no desktop, `max(1.25rem, área segura)` no celular).
 * Medido: com `bottom: 0` o Chrome ancora o rodapé no fim do **content box**, e
 * sobrava uma tira do tamanho do padding — 25px no desktop, 21px no celular —
 * por onde o conteúdo reaparecia embaixo da barra de ações. Puxar a âncora para
 * baixo por esse mesmo tanto encosta o rodapé na borda interna do diálogo.
 *
 * O `padding-bottom` do próprio rodapé devolve o que a âncora consumiu — e é o
 * que mantém os botões fora do indicador de home do iPhone, que era a razão de
 * o `DialogContent` ter aquele `pb` para começo de conversa.
 *
 * (Margem negativa NÃO serve aqui, e foi a primeira tentativa: ela move a caixa,
 * então o rodapé passava a poder parar abaixo da área de rolagem e o conteúdo
 * reaparecia por baixo dele.)
 */
const DialogFooter = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "sticky z-10 -mx-4 mt-2 flex flex-col-reverse gap-2 border-t border-border bg-card px-4 pt-3",
      "bottom-[calc(max(1.25rem,env(safe-area-inset-bottom))*-1)] pb-[max(1.25rem,env(safe-area-inset-bottom))]",
      "sm:-mx-6 sm:bottom-[-1.5rem] sm:flex-row sm:justify-end sm:space-x-2 sm:px-6 sm:pb-6",
      className
    )}
    {...props}
  />
)
DialogFooter.displayName = "DialogFooter"

const DialogTitle = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={cn(
      "text-lg font-semibold leading-none tracking-tight",
      className
    )}
    {...props}
  />
))
DialogTitle.displayName = DialogPrimitive.Title.displayName

const DialogDescription = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={cn("text-sm text-muted-foreground", className)}
    {...props}
  />
))
DialogDescription.displayName = DialogPrimitive.Description.displayName

export {
  Dialog,
  DialogPortal,
  DialogOverlay,
  DialogClose,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
}
