import * as React from "react"
import { cn } from "@/lib/utils"

const Table = React.forwardRef<
  HTMLTableElement,
  React.HTMLAttributes<HTMLTableElement>
>(({ className, ...props }, ref) => (
  /*
    `tabIndex={0}` + `role="region"` + nome: uma área que ROLA precisa ser
    alcançável pelo teclado.

    Quem usa mouse arrasta a barra; quem usa só teclado não tem como chegar ao
    conteúdo que ficou fora de vista, porque não há nada focável dentro de uma
    tabela de leitura. O axe reprova como `scrollable-region-focusable`
    (gravidade "serious"), e foi o que sobrou no Extrato a 390px, onde a tabela
    é mais larga que a tela.

    Focável só quando de fato rola? Não dá — o navegador não expõe isso em CSS, e
    medir no JS custaria um observador de tamanho por tabela. Uma parada a mais
    no Tab, num contêiner nomeado, é um preço menor que conteúdo inalcançável.
  */
  <div
    className="relative w-full overflow-auto focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
    tabIndex={0}
    role="region"
    aria-label="Tabela — role para os lados para ver todas as colunas"
  >
    <table
      ref={ref}
      className={cn("w-full caption-bottom text-sm", className)}
      {...props}
    />
  </div>
))
Table.displayName = "Table"

const TableHeader = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <thead ref={ref} className={cn("[&_tr]:border-b", className)} {...props} />
))
TableHeader.displayName = "TableHeader"

const TableBody = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <tbody
    ref={ref}
    className={cn("[&_tr:last-child]:border-0", className)}
    {...props}
  />
))
TableBody.displayName = "TableBody"

const TableFooter = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <tfoot
    ref={ref}
    className={cn(
      "border-t bg-muted/50 font-medium last:[&>tr]:border-b-0",
      className
    )}
    {...props}
  />
))
TableFooter.displayName = "TableFooter"

const TableRow = React.forwardRef<
  HTMLTableRowElement,
  React.HTMLAttributes<HTMLTableRowElement>
>(({ className, ...props }, ref) => (
  <tr
    ref={ref}
    className={cn(
      "border-b transition-colors hover:bg-muted/50 data-[state=selected]:bg-muted",
      className
    )}
    {...props}
  />
))
TableRow.displayName = "TableRow"

const TableHead = React.forwardRef<
  HTMLTableCellElement,
  React.ThHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => (
  <th
    ref={ref}
    className={cn(
      // px-3 no celular: com `px-4` em toda célula, uma tabela de 5 colunas
      // gastava 40px só de respiro por linha — o suficiente para empurrar a
      // coluna de valor para fora da área rolável.
      "h-12 px-3 text-left align-middle font-medium text-muted-foreground has-[[role=checkbox]]:pr-0 sm:px-4",
      className
    )}
    {...props}
  />
))
TableHead.displayName = "TableHead"

const TableCell = React.forwardRef<
  HTMLTableCellElement,
  React.TdHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => (
  <td
    ref={ref}
    className={cn("p-3 align-middle has-[[role=checkbox]]:pr-0 sm:p-4", className)}
    {...props}
  />
))
TableCell.displayName = "TableCell"

const TableCaption = React.forwardRef<
  HTMLTableCaptionElement,
  React.HTMLAttributes<HTMLTableCaptionElement>
>(({ className, ...props }, ref) => (
  <caption
    ref={ref}
    className={cn("mt-4 text-sm text-muted-foreground", className)}
    {...props}
  />
))
TableCaption.displayName = "TableCaption"

export {
  Table,
  TableHeader,
  TableBody,
  TableFooter,
  TableHead,
  TableRow,
  TableCell,
  TableCaption,
}
