import * as React from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { ChevronLeft, ChevronRight, Edit2, Trash2, Calendar, CreditCard } from 'lucide-react';

import { useTransactions, type TransactionFilters } from '@/hooks/use-transactions';
import { useCategories } from '@/hooks/use-categories';
import { useMembers } from '@/hooks/use-members';
import { useTags } from '@/hooks/use-tags';
import { useWorkspaceRole } from '@/hooks/use-workspace-role';
import { TransactionDialog } from './TransactionDialog';
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Search, Download, FilterX } from 'lucide-react';
import { getApiErrorMessage } from '@/lib/api-error';
import { paymentMethodLabel, PAYMENT_METHOD_OPTIONS } from '@/lib/payment-methods';
import { useConfirm } from '@/components/ui/confirm';
import { toast } from '@/stores/toast';
import type { TransactionRead } from '@/types/transaction';

export function TransactionHistory() {
  const [filters, setFilters] = React.useState<TransactionFilters>({
    page: 1,
    limit: 10,
    month: new Date().toISOString().slice(0, 7), // YYYY-MM
    search: ''
  });
  
  // Guarda só o ID (nunca o objeto): a transação aberta é SEMPRE derivada do
  // cache atualizado — snapshot congelado era a causa do dado velho na reabertura
  const [selectedTxId, setSelectedTxId] = React.useState<number | null>(null);
  const [dialogOpen, setDialogOpen] = React.useState(false);

  const {
    transactions,
    total,
    totalPages,
    isLoading,
    update,
    remove
  } = useTransactions(filters);

  const selectedTx = React.useMemo(
    () => transactions.find((tx: TransactionRead) => tx.id === selectedTxId) ?? null,
    [transactions, selectedTxId]
  );
  const { categoryName } = useCategories();
  const { members } = useMembers();
  const { tags } = useTags();
  const { canWrite } = useWorkspaceRole();  // viewer não edita/exclui (RBAC-FE-001)
  const confirm = useConfirm();

  const memberName = React.useCallback(
    (userId: number) => members.find((m) => m.user_id === userId)?.user_name ?? `#${userId}`,
    [members]
  );

  const handlePageChange = (newPage: number) => {
    setFilters(prev => ({ ...prev, page: newPage }));
  };

  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFilters(prev => ({ ...prev, search: e.target.value, page: 1 }));
  };

  const handleMonthChange = (value: string | null) => {
    if (value) {
      setFilters(prev => ({ ...prev, month: value, page: 1 }));
    }
  };

  const clearFilters = () => {
    setFilters({
      page: 1,
      limit: 10,
      month: new Date().toISOString().slice(0, 7),
      search: ''
    });
  };

  const exportToCSV = () => {
    if (transactions.length === 0) return;
    
    const headers = ['Data', 'Título', 'Categoria', 'Valor', 'Status'];
    const rows = transactions.map((tx: TransactionRead) => [
      new Date(tx.transaction_date).toLocaleDateString('pt-BR'),
      tx.title,
      categoryName(tx.items?.[0]?.category_id),
      tx.total_amount,
      tx.status
    ]);
    
    const csvContent = [headers, ...rows].map(e => e.join(",")).join("\n");
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement("a");
    const url = URL.createObjectURL(blob);
    link.setAttribute("href", url);
    link.setAttribute("download", `transacoes_${filters.month}.csv`);
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleEdit = (tx: TransactionRead) => {
    setSelectedTxId(tx.id);
    setDialogOpen(true);
  };

  const handleSave = async (data: Record<string, unknown>) => {
    // Sem try/catch: o erro sobe para o TransactionForm exibir a mensagem
    // real da API no banner do dialog (que permanece aberto)
    if (selectedTxId == null) return;
    await update({ id: selectedTxId, data });
    setDialogOpen(false);
  };

  const handleDelete = async (id: number) => {
    const ok = await confirm({
      title: 'Remover transação',
      description: 'Tem certeza que deseja remover esta transação?',
      confirmLabel: 'Remover',
      destructive: true,
    });
    if (!ok) return;
    try {
      await remove(id);
      setDialogOpen(false);
    } catch (err) {
      toast.error(getApiErrorMessage(err, 'Erro ao remover transação'));
    }
  };

  const months = React.useMemo(() => {
    const list = [];
    const now = new Date();
    for (let i = 0; i < 12; i++) {
      const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
      list.push({
        value: d.toISOString().slice(0, 7),
        label: d.toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' })
      });
    }
    return list;
  }, []);

  if (isLoading) {
    return (
      <Card className="bg-card border-border h-[400px] flex items-center justify-center">
        <div className="flex flex-col items-center gap-2">
          <div className="h-8 w-8 border-4 border-primary/20 border-t-primary rounded-full animate-spin" />
          <p className="text-xs text-muted-foreground">Buscando transações...</p>
        </div>
      </Card>
    );
  }

  return (
    <Card className="bg-card border-border h-full flex flex-col">
      <CardHeader className="space-y-4">
        <div className="flex flex-row items-center justify-between">
          <div>
            <CardTitle className="text-foreground">Histórico de Transações</CardTitle>
            <CardDescription className="text-muted-foreground">
              {total} transações encontradas.
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={exportToCSV} className="gap-2">
              <Download className="h-4 w-4" /> Exportar
            </Button>
            <div className="h-8 w-[1px] bg-border mx-1" />
            <Button variant="outline" size="sm" onClick={() => handlePageChange(Math.max(1, filters.page! - 1))} disabled={filters.page === 1}>
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="text-xs font-medium px-2 text-foreground min-w-[80px] text-center">
              {filters.page} / {totalPages}
            </span>
            <Button variant="outline" size="sm" onClick={() => handlePageChange(Math.min(totalPages, filters.page! + 1))} disabled={filters.page === totalPages}>
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>

        <div className="flex flex-col md:flex-row gap-3">
          <div className="relative flex-1 group">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground group-focus-within:text-primary transition-colors" />
            <Input 
              placeholder="Buscar por descrição..." 
              value={filters.search}
              onChange={handleSearchChange}
              className="pl-10 bg-background/50 border-border focus-visible:ring-primary/20"
            />
          </div>
          <div className="flex gap-2">
            <Select items={months} value={filters.month} onValueChange={handleMonthChange}>
              <SelectTrigger className="w-[180px] bg-background/50 border-border">
                <SelectValue placeholder="Selecionar Mês" />
              </SelectTrigger>
              <SelectContent>
                {months.map(m => (
                  <SelectItem key={m.value} value={m.value} className="capitalize">{m.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select
              items={[{ value: 'all', label: 'Todo pagamento' }, ...PAYMENT_METHOD_OPTIONS]}
              value={filters.payment_method || 'all'}
              onValueChange={(value: string | null) =>
                setFilters(prev => ({ ...prev, payment_method: value === 'all' ? undefined : value ?? undefined, page: 1 }))
              }
            >
              <SelectTrigger className="w-[170px] bg-background/50 border-border">
                <SelectValue placeholder="Pagamento" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Todo pagamento</SelectItem>
                {PAYMENT_METHOD_OPTIONS.map(opt => (
                  <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            {tags.length > 0 && (
              <Select
                items={[{ value: 'all', label: 'Toda tag' }, ...tags.map((t) => ({ value: String(t.id), label: t.name }))]}
                value={filters.tag_id ? String(filters.tag_id) : 'all'}
                onValueChange={(value: string | null) =>
                  setFilters(prev => ({ ...prev, tag_id: value && value !== 'all' ? Number(value) : undefined, page: 1 }))
                }
              >
                <SelectTrigger className="w-[140px] bg-background/50 border-border">
                  <SelectValue placeholder="Tag" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Toda tag</SelectItem>
                  {tags.map(tag => (
                    <SelectItem key={tag.id} value={String(tag.id)}>{tag.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            <Button variant="ghost" size="icon" onClick={clearFilters} className="text-muted-foreground hover:text-primary">
              <FilterX className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex-1 overflow-auto">
        <Table>
          <TableHeader>
            <TableRow className="border-border hover:bg-transparent">
              <TableHead className="text-muted-foreground">Data/Hora</TableHead>
              <TableHead className="text-muted-foreground">Descrição</TableHead>
              <TableHead className="text-muted-foreground">Pagamento</TableHead>
              <TableHead className="text-muted-foreground text-right">Valor</TableHead>
              <TableHead className="text-muted-foreground text-center">Ações</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {transactions.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="h-32 text-center text-muted-foreground">
                  Nenhuma transação encontrada.
                </TableCell>
              </TableRow>
            ) : transactions.map((tx: TransactionRead) => (
              <TableRow key={tx.id} className="border-border group hover:bg-accent/50 transition-colors">
                <TableCell>
                  <div className="flex flex-col">
                    <span className="text-xs text-foreground font-medium flex items-center gap-1">
                      <Calendar className="h-3 w-3 text-muted-foreground" />
                      {new Date(tx.transaction_date).toLocaleDateString('pt-BR')}
                    </span>
                    <span className="text-[10px] text-muted-foreground">{new Date(tx.transaction_date).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}</span>
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex flex-col gap-1">
                    <span className="text-sm font-medium text-foreground">{tx.title}</span>
                    <span className="text-[10px] uppercase tracking-wider text-primary font-bold">{categoryName(tx.items?.[0]?.category_id)}</span>
                    {(tx.tags?.length ?? 0) > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {tx.tags.map((tag) => (
                          <span
                            key={tag.id}
                            className="inline-flex items-center gap-1 rounded-full border border-border bg-accent/40 px-1.5 py-0.5 text-[9px] font-bold text-muted-foreground"
                          >
                            <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: tag.color || 'var(--primary)' }} />
                            {tag.name}
                          </span>
                        ))}
                      </div>
                    )}
                    {(tx.splits?.length ?? 0) > 1 && (
                      <div className="flex items-center -space-x-1.5">
                        {tx.splits.slice(0, 5).map((split) => (
                          <span
                            key={split.id}
                            title={`${memberName(split.user_id)} — R$ ${parseFloat(split.computed_amount).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}`}
                            className="h-5 w-5 rounded-full bg-primary/15 border border-border text-[9px] font-bold text-primary flex items-center justify-center uppercase"
                          >
                            {memberName(split.user_id).slice(0, 2)}
                          </span>
                        ))}
                        {tx.splits.length > 5 && (
                          <span className="h-5 w-5 rounded-full bg-muted border border-border text-[9px] font-bold text-muted-foreground flex items-center justify-center">
                            +{tx.splits.length - 5}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <CreditCard className="h-3 w-3" />
                    {paymentMethodLabel(tx.payment_method, tx.credit_card_id)}
                  </div>
                </TableCell>
                <TableCell className="text-right">
                  <span className={`font-bold ${parseFloat(tx.total_amount) < 0 ? 'text-destructive' : 'text-emerald-500'}`}>
                    R$ {Math.abs(parseFloat(tx.total_amount)).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}
                  </span>
                </TableCell>
                <TableCell>
                  <div className="flex items-center justify-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label="Editar transação"
                      disabled={!canWrite}
                      className="h-8 w-8 p-0 text-primary hover:text-primary hover:bg-primary/10"
                      onClick={() => handleEdit(tx)}
                    >
                      <Edit2 className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label="Excluir transação"
                      disabled={!canWrite}
                      className="h-8 w-8 p-0 text-destructive hover:text-destructive hover:bg-destructive/10"
                      onClick={() => handleDelete(tx.id)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>

      <TransactionDialog 
        transaction={selectedTx}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onSave={handleSave}
        onDelete={handleDelete}
      />
    </Card>
  );
}
