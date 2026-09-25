import { Link } from 'react-router-dom';
import { Store } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useMerchantSpending } from '@/hooks/use-merchants';
import { formatMoney } from '@/lib/money';

/**
 * Gasto do mês por estabelecimento (ADR 0038).
 *
 * Mostra o valor cheio E a sua parte, lado a lado: a pergunta "quanto foi no
 * mercado" tem as duas respostas numa casa dividida, e escolher uma escondia a
 * outra. A soma é a mesma do agrupamento do agente (status realizados, por
 * moeda, só o que você vê). O que não tem estabelecimento vira uma linha só, no
 * fim, e não some: o total da tabela fecha com o do mês.
 */
export function MerchantSpendingPanel({ month, workspaceId }: { month: string; workspaceId: number | null }) {
  const { data, isLoading, isError } = useMerchantSpending(month);

  return (
    <Card className="bg-card border-border shadow-xl">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <Store className="h-5 w-5 text-primary" /> Por estabelecimento
        </CardTitle>
        <CardDescription>
          Onde o dinheiro foi gasto neste mês. Cadastre e junte estabelecimentos em
          Configurações do espaço › Estabelecimentos.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-40 w-full" />
        ) : isError || !data ? (
          <p role="alert" className="text-sm text-destructive">Não foi possível carregar o gasto por estabelecimento.</p>
        ) : data.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">Nenhum gasto neste mês.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground">
                  <th className="py-2 pr-3 font-medium">Estabelecimento</th>
                  <th className="hidden py-2 pr-3 text-right font-medium sm:table-cell">Lançamentos</th>
                  <th className="hidden py-2 pr-3 text-right font-medium sm:table-cell">Valor cheio</th>
                  <th className="py-2 text-right font-medium">Sua parte</th>
                </tr>
              </thead>
              <tbody>
                {data.map((linha) => (
                  <tr key={`${linha.id ?? 'sem'}-${linha.currency}`} className="border-b border-border/50 last:border-0">
                    <td className="max-w-[12rem] py-2 pr-3 sm:max-w-[16rem]">
                      {linha.id && workspaceId ? (
                        <Link to={`/w/${workspaceId}/transactions?estabelecimento=${linha.id}&month=${month}`}
                          className="block truncate font-medium text-foreground hover:text-brand hover:underline">
                          {linha.name}
                        </Link>
                      ) : (
                        <span className="block truncate text-muted-foreground">{linha.name}</span>
                      )}
                      {/* No celular a contagem e o valor cheio descem para baixo do
                          nome: em 360px só cabe uma coluna de dinheiro, e o número em
                          destaque é o da pessoa — o total vem nomeado ("de R$ X"). */}
                      <span className="block text-xs text-muted-foreground sm:hidden">
                        {linha.count === 1 ? '1 lançamento' : `${linha.count} lançamentos`}
                        {' · de '}{formatMoney(Number(linha.total), { currency: linha.currency })}
                      </span>
                    </td>
                    <td className="tabular hidden py-2 pr-3 text-right text-muted-foreground sm:table-cell">{linha.count}</td>
                    <td className="tabular hidden whitespace-nowrap py-2 pr-3 text-right sm:table-cell">{formatMoney(Number(linha.total), { currency: linha.currency })}</td>
                    <td className="tabular whitespace-nowrap py-2 text-right font-semibold">{formatMoney(Number(linha.my_share), { currency: linha.currency })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
