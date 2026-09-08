import * as React from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight, CreditCard, HandCoins, Loader2, Receipt, Search, TrendingUp } from 'lucide-react';

import { apiClient } from '@/api/client';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { formatMoney } from '@/lib/money';
import { parseApiDay } from '@/lib/date';
import type { components } from '@/types/api.gen';

/**
 * Busca global — "onde foi aquele pagamento do dentista?".
 *
 * ## A lacuna
 *
 * O app tinha cinco listas e nenhuma que atravessasse as outras. Achar um
 * lançamento de três meses atrás exigia lembrar em QUAL espaço ele foi, abrir a
 * tela certa e navegar até o mês certo. Quem não lembra o mês não tinha caminho
 * nenhum — a informação estava lá, guardada, e inalcançável.
 *
 * ## O desenho
 *
 * Um diálogo, aberto por `/` ou `Ctrl/⌘+K` no teclado e por um botão na barra
 * superior no toque. Resultados agrupados por tipo, com o rótulo que a pessoa
 * reconhece ("Lançamentos", "Rendas"), e cada linha leva ao lugar onde aquele
 * item vive.
 *
 * O `href` de cada linha vem do SERVIDOR: é ele que sabe em qual espaço o
 * lançamento está. Montar a URL aqui seria repetir esse conhecimento e deixá-lo
 * envelhecer na próxima mudança de rota.
 *
 * ## O que ela não faz
 *
 * Não busca enquanto se digita a primeira letra (mínimo de 2 caracteres, e o
 * servidor recusa menos que isso), não corrige ortografia e não ordena por
 * relevância. É um atalho para achar o que se sabe que existe.
 */
type SearchRead = components['schemas']['SearchRead'];
type SearchHit = components['schemas']['SearchHit'];

const ICONE: Record<string, typeof Receipt> = {
  transaction: Receipt,
  income: TrendingUp,
  settlement: HandCoins,
  card: CreditCard,
};

const ESPERA_MS = 250;

function Linha({ hit, onIr }: { hit: SearchHit; onIr: (href: string) => void }) {
  const Icone = ICONE[hit.kind] ?? Receipt;
  return (
    <li>
      <button
        type="button"
        onClick={() => onIr(hit.href)}
        className="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors hover:bg-muted focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Icone className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-foreground">{hit.title}</span>
          <span className="block truncate text-xs text-muted-foreground">
            {[
              hit.workspace_name,
              hit.occurred_on ? parseApiDay(hit.occurred_on).toLocaleDateString('pt-BR') : null,
            ].filter(Boolean).join(' · ')}
          </span>
        </span>
        {hit.amount != null && (
          <span className="tabular shrink-0 text-sm text-foreground">
            {formatMoney(Number(hit.amount), { currency: hit.currency ?? 'BRL' })}
          </span>
        )}
        <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      </button>
    </li>
  );
}

export function BuscaGlobal({ open, onOpenChange }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const navigate = useNavigate();
  const [texto, setTexto] = React.useState('');
  const [termo, setTermo] = React.useState('');

  // O campo responde a cada tecla; a consulta só sai quando a digitação para.
  // Sem isto, "dentista" dispara oito requisições — o mesmo cuidado que a lista
  // de lançamentos já tomava.
  React.useEffect(() => {
    const id = setTimeout(() => setTermo(texto.trim()), ESPERA_MS);
    return () => clearTimeout(id);
  }, [texto]);

  // Ao fechar, esquece: reabrir com o resultado anterior na tela faz parecer que
  // a busca já rodou para o que se vai digitar agora.
  React.useEffect(() => {
    if (!open) { setTexto(''); setTermo(''); }
  }, [open]);

  const { data, isFetching } = useQuery({
    queryKey: ['busca', termo],
    queryFn: async (): Promise<SearchRead> => {
      const res = await apiClient.get('/me/search', { params: { q: termo } });
      return res.data;
    },
    enabled: termo.length >= 2,
  });

  const ir = (href: string) => {
    onOpenChange(false);
    navigate(href);
  };

  const grupos = data?.groups ?? [];
  const vazio = termo.length >= 2 && !isFetching && grupos.length === 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-base">Buscar</DialogTitle>
        </DialogHeader>

        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <Input
            autoFocus
            value={texto}
            onChange={(e) => setTexto(e.target.value)}
            placeholder="Lançamento, renda, acerto, cartão…"
            aria-label="Buscar em tudo"
            className="pl-9"
          />
          {isFetching && (
            <Loader2 className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-muted-foreground" aria-hidden="true" />
          )}
        </div>

        <div className="max-h-[50vh] min-h-[80px] overflow-y-auto">
          {termo.length < 2 ? (
            <p className="px-2 py-6 text-center text-sm text-muted-foreground">
              Digite pelo menos duas letras.
            </p>
          ) : vazio ? (
            <p className="px-2 py-6 text-center text-sm text-muted-foreground">
              Nada encontrado para "{termo}".
            </p>
          ) : (
            grupos.map((grupo) => (
              <section key={grupo.kind} className="mb-2">
                <h3 className="px-2 py-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {grupo.label}
                </h3>
                <ul>
                  {grupo.items.map((hit) => (
                    <Linha key={`${hit.kind}-${hit.id}`} hit={hit} onIr={ir} />
                  ))}
                </ul>
              </section>
            ))
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
