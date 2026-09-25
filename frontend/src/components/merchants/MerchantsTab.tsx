import * as React from 'react';
import { Link } from 'react-router-dom';
import { GitMerge, Pencil, Plus, Store, Trash2 } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { useConfirm } from '@/components/ui/confirm';
import { useMerchants, type Merchant } from '@/hooks/use-merchants';
import { useCategories } from '@/hooks/use-categories';
import { useWorkspaceId } from '@/hooks/use-workspace-id';
import { useWorkspaceRole } from '@/hooks/use-workspace-role';
import { getApiErrorMessage } from '@/lib/api-error';
import { toast } from '@/stores/toast';

/** "IFD*MC DONALDS, MC DONALDS" → duas grafias; o servidor normaliza cada uma. */
function apelidos(texto: string): string[] {
  return texto.split(/[,\n]/).map((a) => a.trim()).filter(Boolean);
}

/**
 * Estabelecimentos do espaço (ADR 0038).
 *
 * O nome é o que a tela mostra; os apelidos são como o extrato escreve o lugar.
 * Um lançamento novo cujo título é EXATAMENTE um apelido (sem acento, caixa,
 * número ou pontuação) se liga sozinho — parecido não liga, e é para isso que
 * existe "Mesclar": juntar dois cadastros do mesmo lugar sem perder lançamento.
 */
export function MerchantsTab() {
  const { merchants, isLoading, isError, create } = useMerchants();
  const { canWrite } = useWorkspaceRole();
  const [nome, setNome] = React.useState('');
  const [grafias, setGrafias] = React.useState('');
  const [salvando, setSalvando] = React.useState(false);

  const criar = async () => {
    if (!nome.trim()) return;
    setSalvando(true);
    try {
      await create({ name: nome.trim(), aliases: apelidos(grafias) });
      setNome('');
      setGrafias('');
      toast.success('Estabelecimento criado');
    } catch (err) {
      toast.error(getApiErrorMessage(err, 'Não foi possível criar o estabelecimento.'));
    } finally {
      setSalvando(false);
    }
  };

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
      <Card className="bg-card border-border shadow-xl">
        <CardHeader>
          <CardTitle>Estabelecimentos</CardTitle>
          <CardDescription>
            Onde as despesas foram feitas. Os apelidos são como o nome aparece no extrato
            (&ldquo;IFD*MC DONALDS&rdquo;): um lançamento novo com esse título se liga sozinho.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {canWrite && (
            <div className="grid gap-3 sm:grid-cols-[1fr_1.4fr_auto] sm:items-end">
              <div className="space-y-1.5">
                <Label htmlFor="novo-estabelecimento">Nome</Label>
                <Input id="novo-estabelecimento" placeholder="Ex.: Padaria Pão Quente" value={nome} maxLength={120}
                  onChange={(e) => setNome(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void criar()} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="novos-apelidos">Apelidos no extrato (opcional)</Label>
                <Input id="novos-apelidos" placeholder="Separados por vírgula" value={grafias}
                  onChange={(e) => setGrafias(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void criar()} />
              </div>
              <Button onClick={() => void criar()} disabled={!nome.trim()} pending={salvando} className="h-10 gap-2">
                <Plus className="h-4 w-4" /> Criar
              </Button>
            </div>
          )}

          {isError ? (
            <p role="alert" className="text-sm text-destructive">Não foi possível carregar os estabelecimentos.</p>
          ) : isLoading ? (
            <p className="text-sm text-muted-foreground">Carregando…</p>
          ) : merchants.length === 0 ? (
            <div className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
              <Store className="mx-auto mb-2 h-5 w-5" />
              Nenhum estabelecimento ainda. Eles também nascem quando você informa onde foi a
              compra num lançamento.
            </div>
          ) : (
            <ul className="space-y-2">
              {merchants.map((m) => <Linha key={m.id} m={m} todos={merchants} podeEditar={canWrite} />)}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Linha({ m, todos, podeEditar }: { m: Merchant; todos: Merchant[]; podeEditar: boolean }) {
  const { update, merge, remove } = useMerchants();
  const { categories } = useCategories();
  const ws = useWorkspaceId();
  const confirm = useConfirm();
  const [modo, setModo] = React.useState<'ver' | 'editar' | 'mesclar'>('ver');
  const [nome, setNome] = React.useState(m.name);
  const [grafias, setGrafias] = React.useState((m.aliases ?? []).join(', '));
  const [categoria, setCategoria] = React.useState(m.default_category_id ? String(m.default_category_id) : '');
  const [destino, setDestino] = React.useState('');
  const [salvando, setSalvando] = React.useState(false);
  const categoriaPadrao = categories.find((c) => c.id === m.default_category_id)?.name;
  const outros = todos.filter((o) => o.id !== m.id);
  const quantos = m.transaction_count ?? 0;

  const abrirEdicao = () => {
    setNome(m.name);
    setGrafias((m.aliases ?? []).join(', '));
    setCategoria(m.default_category_id ? String(m.default_category_id) : '');
    setModo('editar');
  };

  const executar = async (acao: () => Promise<unknown>, ok: string, falha: string) => {
    setSalvando(true);
    try {
      await acao();
      toast.success(ok);
      setModo('ver');
    } catch (err) {
      toast.error(getApiErrorMessage(err, falha));
    } finally {
      setSalvando(false);
    }
  };

  const salvar = () => executar(
    () => update({
      id: m.id,
      data: { name: nome.trim(), aliases: apelidos(grafias), default_category_id: categoria ? Number(categoria) : null },
    }),
    'Estabelecimento atualizado', 'Não foi possível salvar.',
  );

  const mesclar = async () => {
    const alvo = outros.find((o) => String(o.id) === destino);
    if (!alvo) return;
    const sim = await confirm({
      title: 'Mesclar estabelecimentos',
      description: `"${m.name}" deixa de existir: ${quantos === 1 ? 'o lançamento dele passa' : `os ${quantos} lançamentos dele passam`} para "${alvo.name}", junto com os apelidos.`,
      confirmLabel: 'Mesclar',
    });
    if (sim) await executar(() => merge({ id: m.id, intoId: alvo.id }), `Mesclado em ${alvo.name}`, 'Não foi possível mesclar.');
  };

  const excluir = async () => {
    const sim = await confirm({
      title: 'Excluir estabelecimento',
      description: quantos
        ? `Excluir "${m.name}"? ${quantos === 1 ? 'O lançamento continua' : `Os ${quantos} lançamentos continuam`}, só sem estabelecimento.`
        : `Excluir "${m.name}"?`,
      confirmLabel: 'Excluir',
      destructive: true,
    });
    if (sim) await executar(() => remove(m.id), 'Estabelecimento excluído', 'Não foi possível excluir.');
  };

  if (modo === 'editar') {
    return (
      <li className="space-y-3 rounded-xl border border-border bg-accent/20 p-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor={`nome-${m.id}`}>Nome</Label>
            <Input id={`nome-${m.id}`} value={nome} maxLength={120} onChange={(e) => setNome(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`categoria-${m.id}`}>Categoria padrão</Label>
            <NativeSelect id={`categoria-${m.id}`} value={categoria} onChange={(e) => setCategoria(e.target.value)}>
              <option value="">Nenhuma</option>
              {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </NativeSelect>
          </div>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor={`apelidos-${m.id}`}>Apelidos no extrato</Label>
          <Input id={`apelidos-${m.id}`} value={grafias} placeholder="Separados por vírgula" onChange={(e) => setGrafias(e.target.value)} />
          <p className="text-xs text-muted-foreground">
            A categoria padrão vale para o lançamento novo que chega sem categoria.
          </p>
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={() => setModo('ver')}>Cancelar</Button>
          <Button onClick={() => void salvar()} disabled={!nome.trim()} pending={salvando}>Salvar</Button>
        </div>
      </li>
    );
  }

  return (
    <li className="rounded-xl border border-border/60 bg-accent/30 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-foreground">{m.name}</p>
          <p className="text-xs text-muted-foreground">
            {quantos > 0 && ws
              ? <Link to={`/w/${ws}/transactions?estabelecimento=${m.id}`} className="font-medium text-brand hover:underline">
                  {quantos === 1 ? '1 lançamento' : `${quantos} lançamentos`}
                </Link>
              : 'Nenhum lançamento'}
            {categoriaPadrao && <> · categoria padrão {categoriaPadrao}</>}
          </p>
          {(m.aliases ?? []).length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {(m.aliases ?? []).map((a) => (
                <span key={a} title={a}
                  className="max-w-full truncate whitespace-nowrap rounded-full bg-background px-2 py-0.5 font-mono text-[11px] text-muted-foreground">{a}</span>
              ))}
            </div>
          )}
        </div>
        {podeEditar && modo === 'ver' && (
          <div className="flex shrink-0 items-center gap-1">
            {/* No celular só o ícone: o nome e os apelidos precisam da largura. */}
            <Button variant="ghost" size="sm" className="h-8 gap-1 px-2 text-xs" aria-label={`Editar ${m.name}`} onClick={abrirEdicao}>
              <Pencil className="h-3.5 w-3.5" /> <span className="hidden sm:inline">Editar</span>
            </Button>
            {outros.length > 0 && (
              <Button variant="ghost" size="sm" className="h-8 gap-1 px-2 text-xs" aria-label={`Mesclar ${m.name}`}
                onClick={() => { setDestino(''); setModo('mesclar'); }}>
                <GitMerge className="h-3.5 w-3.5" /> <span className="hidden sm:inline">Mesclar</span>
              </Button>
            )}
            <Button variant="ghost" size="sm" aria-label={`Excluir o estabelecimento ${m.name}`}
              className="h-8 w-8 p-0 text-destructive hover:bg-destructive/10" onClick={() => void excluir()}>
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        )}
      </div>
      {modo === 'mesclar' && (
        <div className="mt-3 flex flex-wrap items-end gap-2 border-t border-border/60 pt-3">
          <div className="min-w-48 flex-1 space-y-1.5">
            <Label htmlFor={`mesclar-${m.id}`}>É o mesmo que</Label>
            <NativeSelect id={`mesclar-${m.id}`} value={destino} onChange={(e) => setDestino(e.target.value)}>
              <option value="">Escolha…</option>
              {outros.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
            </NativeSelect>
          </div>
          <Button variant="ghost" onClick={() => setModo('ver')}>Cancelar</Button>
          <Button onClick={() => void mesclar()} disabled={!destino} pending={salvando}>Mesclar</Button>
        </div>
      )}
    </li>
  );
}
