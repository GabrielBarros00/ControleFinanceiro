/** @jsxImportSource preact */
/**
 * Resumo do mês (`reports_show`) e análise agrupada (`view_show view=breakdown`).
 *
 * Clicar numa categoria (ou grupo) abre os lançamentos dela ali mesmo, pela tool
 * de busca — a mesma regra de "minha parte" do resumo.
 */
import { useEffect, useState } from 'preact/hooks';
import type { Bridge } from '../bridge';
import { money, monthLong, monthTitle } from '../format';
import type { Meta, Ref } from '../tipos';
import { erroDe } from '../ui/acao';
import { Aviso, Barras, Button, Colunas, Esqueleto, Header, Section, Stat } from '../ui/base';
import { Escolha, Segmentos } from '../ui/form';
import { IconChart, IconExternal, IconX } from '../ui/icons';
import type { Consulta } from '../ui/paginas';
import { Filtros, ListaDeLancamentos } from './Lista';

const MES_CURTO = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
const curto = (m: string) => MES_CURTO[Number(m.slice(5, 7)) - 1] ?? m;

/** Os lançamentos por trás de um número, abertos sob demanda. */
function Detalhe({ consulta, titulo, bridge, meta, aoFechar }: { consulta: Consulta; titulo: string; bridge: Bridge; meta: Meta; aoFechar: () => void }) {
  const [dados, setDados] = useState<Record<string, unknown> | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  // A consulta do primeiro render: o componente é recriado (`key`) quando ela muda.
  const [alvo] = useState(consulta);
  useEffect(() => {
    bridge.callTool(alvo.tool, alvo.args).then(
      (r) => (r.isError ? setErro(erroDe(r).mensagem) : setDados((r.structuredContent ?? {}) as Record<string, unknown>)),
      () => setErro('Não foi possível abrir.'),
    );
  }, [bridge, alvo]);
  return (
    <div class="w-aparece space-y-2 rounded-lg border border-border p-3">
      <div class="flex items-center justify-between gap-2">
        <p class="text-[13px] font-semibold">{titulo}</p>
        <Button variante="ghost" icone={<IconX size={14} />} onClick={aoFechar}>Fechar</Button>
      </div>
      {erro ? <Aviso tom="erro">{erro}</Aviso> : !dados ? <Esqueleto linhas={3} /> : <ListaDeLancamentos dados={dados} consulta={alvo} meta={meta} bridge={bridge} />}
    </div>
  );
}

export function ResumoView({ dados, meta, bridge }: { dados: Record<string, unknown>; meta: Meta; bridge: Bridge }) {
  const moeda = (dados.currency as string) ?? 'BRL';
  const mes = dados.month as string;
  const cats = (dados.my_categories as Array<{ category: string; amount: string }> | undefined) ?? [];
  const serie = (dados.series as Array<{ month: string; consumption: string; income: string; result: string }> | undefined) ?? [];
  const espacos = (dados.spaces as Array<{ space: Ref; my_consumption: string; house_total: string; currency: string }> | undefined) ?? [];
  const resultado = Number(dados.result ?? 0);
  const [aberta, setAberta] = useState<string | null>(null);
  const [curva, setCurva] = useState<'consumption' | 'result'>('consumption');

  return (
    <div class="space-y-3">
      <Header icone={<IconChart size={18} />} tom="destaque" titulo={monthTitle(mes)}
        subtitulo="Todos os espaços"
        direita={<><p class="text-[11px] text-muted-fg">Resultado</p><p class={`num text-[17px] font-semibold ${resultado >= 0 ? 'text-income' : 'text-expense'}`}>{money(resultado, moeda)}</p></>} />
      <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat rotulo="Renda" tom="entrada">{money(dados.income as string, moeda)}</Stat>
        <Stat rotulo="Seu consumo" tom="saida">{money(dados.consumption as string, moeda)}</Stat>
        <Stat rotulo="Saiu do caixa">{money(dados.cash_out as string, moeda)}</Stat>
        <Stat rotulo="A pagar">{money(dados.payables_total as string, moeda)}</Stat>
      </div>
      {(Number(dados.to_pay ?? 0) > 0 || Number(dados.to_receive ?? 0) > 0) && (
        <p class="text-[12px] text-muted-fg">Entre pessoas: você deve {money(dados.to_pay as string, moeda)} e tem a receber {money(dados.to_receive as string, moeda)}.</p>
      )}
      {serie.length > 1 && (
        <Section titulo="Últimos meses" contagem={serie.length} aberta>
          <div class="mb-2"><Segmentos rotulo="Série" valor={curva} aoMudar={setCurva}
            opcoes={[{ valor: 'consumption', rotulo: 'Consumo' }, { valor: 'result', rotulo: 'Resultado' }]} /></div>
          <Colunas moeda={moeda} pontos={serie.map((s) => ({
            rotulo: curto(s.month), valor: Number(s[curva]),
            tom: curva === 'result' ? (Number(s.result) >= 0 ? 'entrada' : 'saida') : undefined,
          }))} />
        </Section>
      )}
      {cats.length > 0 && (
        <Section titulo="Seu consumo por categoria" contagem={cats.length} aberta>
          <Barras total={dados.consumption as string} fatias={cats.map((c) => ({
            chave: c.category, rotulo: c.category, valor: c.amount, moeda, onClick: () => setAberta(c.category),
          }))} />
          {aberta && (
            <div class="mt-2">
              <Detalhe key={aberta} titulo={`${aberta} em ${monthLong(mes)}`} bridge={bridge} meta={meta} aoFechar={() => setAberta(null)}
                consulta={{ tool: 'transactions_search', args: { month: mes, ...(aberta === 'Sem categoria' ? { uncategorized: true } : { category: aberta }) } }} />
            </div>
          )}
        </Section>
      )}
      {espacos.length > 1 && (
        <Section titulo="Por espaço" contagem={espacos.length}>
          <Barras total={dados.consumption as string} fatias={espacos.map((e) => ({
            chave: String(e.space.id), rotulo: e.space.name, valor: e.my_consumption, moeda: e.currency, extra: `total ${money(e.house_total, e.currency)}`,
          }))} />
        </Section>
      )}
      {meta.app_url && <Button variante="ghost" icone={<IconExternal size={14} />} onClick={() => bridge.openLink(meta.app_url!)}>Abrir no app</Button>}
    </div>
  );
}

const AGRUPAR: Array<{ valor: string; rotulo: string }> = [
  { valor: 'category', rotulo: 'Categoria' }, { valor: 'tag', rotulo: 'Tag' }, { valor: 'person', rotulo: 'Pessoa' },
  { valor: 'card', rotulo: 'Cartão' }, { valor: 'account', rotulo: 'Conta' }, { valor: 'payment_method', rotulo: 'Forma de pagamento' },
  { valor: 'month', rotulo: 'Mês' }, { valor: 'space', rotulo: 'Espaço' }, { valor: 'title', rotulo: 'Título' },
];

/** Grupo → o filtro da busca que mostra os lançamentos dele. */
const FILTRO_DO_GRUPO: Record<string, (g: Grupo) => Record<string, unknown> | null> = {
  category: (g) => (g.id ? { category_id: g.id } : { uncategorized: true }),
  tag: (g) => (g.id ? { tag: g.name } : null),
  person: (g) => (g.id ? { person_id: g.id } : null),
  card: (g) => (g.id ? { card_id: g.id } : null),
  account: (g) => (g.id ? { account_id: g.id } : null),
  space: (g) => (g.id ? { space_id: g.id } : null),
  title: (g) => ({ text: g.name.slice(0, 80) }),
};

interface Grupo { id?: number | null; name: string; currency: string; amount: string; count: number; percent: string }

export function AnaliseView({ dados: inicial, meta, bridge }: { dados: Record<string, unknown>; meta: Meta; bridge: Bridge }) {
  const [dados, setDados] = useState(inicial);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [aberto, setAberto] = useState<Grupo | null>(null);
  const args = meta.query?.args ?? {};
  const grupos = [...((dados.groups as Grupo[]) ?? []), ...((dados.others as Grupo[]) ?? [])];
  const totais = Object.entries((dados.totals as Record<string, string>) ?? {});
  const agrupar = String(dados.group_by ?? args.group_by ?? 'category');
  const base = String(dados.basis ?? args.basis ?? 'my_share');
  const filtros = Object.fromEntries(Object.entries(args).filter(([k]) => k !== 'group_by' && k !== 'basis'));

  async function trocar(novo: Record<string, unknown>) {
    setCarregando(true);
    setErro(null);
    setAberto(null);
    const r = await bridge.callTool('reports_breakdown', { ...filtros, group_by: agrupar, basis: base, ...novo }).catch(() => null);
    setCarregando(false);
    if (r && !r.isError) setDados((r.structuredContent ?? {}) as Record<string, unknown>);
    else setErro(r ? erroDe(r).mensagem : 'Não foi possível agrupar.');
  }

  const porMoeda = (m: string) => totais.find(([c]) => c === m)?.[1] ?? '0';
  const filtroDoGrupo = aberto ? FILTRO_DO_GRUPO[agrupar]?.(aberto) : null;

  return (
    <div class="space-y-3">
      <Header icone={<IconChart size={18} />} tom="destaque" titulo="Para onde foi o dinheiro"
        subtitulo={base === 'my_share' ? 'Sua parte de cada lançamento' : 'Valor cheio dos lançamentos'}
        direita={<p class="num text-[15px] font-semibold">{totais.map(([m, v]) => money(v, m)).join(' + ') || '—'}</p>} />
      <Filtros args={filtros} />
      <div class="flex flex-wrap items-center gap-2">
        <span class="w-44"><Escolha valor={agrupar} aoMudar={(v) => void trocar({ group_by: v })} opcoes={AGRUPAR} /></span>
        <Segmentos rotulo="Base" valor={base} aoMudar={(v) => void trocar({ basis: v })}
          opcoes={[{ valor: 'my_share', rotulo: 'Minha parte' }, { valor: 'total', rotulo: 'Total' }]} />
      </div>
      {erro && <Aviso tom="erro">{erro}</Aviso>}
      {carregando ? <Esqueleto linhas={4} /> : grupos.length === 0 ? <Aviso tom="info">Nada com esses filtros.</Aviso> : (
        <Barras total={porMoeda(grupos[0].currency)} fatias={grupos.map((g) => ({
          chave: `${g.id ?? g.name}-${g.currency}`, rotulo: g.name, valor: g.amount, moeda: g.currency,
          extra: `${g.count}× · ${Math.round(Number(g.percent))}%`,
          onClick: FILTRO_DO_GRUPO[agrupar]?.(g) ? () => setAberto(g) : undefined,
        }))} />
      )}
      {aberto && filtroDoGrupo && (
        <Detalhe key={`${agrupar}-${aberto.id ?? aberto.name}`} titulo={aberto.name} bridge={bridge} meta={meta} aoFechar={() => setAberto(null)}
          consulta={{ tool: 'transactions_search', args: { ...filtros, ...filtroDoGrupo } }} />
      )}
    </div>
  );
}
