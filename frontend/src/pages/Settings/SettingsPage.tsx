import * as React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { User, Shield, Users, Palette, LogOut, Globe, Moon, Sun, Laptop, Loader2, Trash2, LinkIcon, Copy, Check, Tag, Plus, Wallet, History, Ticket, Smartphone, Download } from 'lucide-react';
import { useAuthStore } from '@/stores';
import { useTheme } from '@/hooks/use-theme';
import { useInstallPrompt } from '@/hooks/use-install-prompt';
import { useAuth } from '@/hooks/use-auth';
import { useWorkspaces } from '@/hooks/use-workspaces';
import { workspacePath } from '@/hooks/use-workspace-id';
import { useWorkspaceRole } from '@/hooks/use-workspace-role';
import { useAudit } from '@/hooks/use-audit';
import { useMembers, type FinancialAccess, type WorkspaceRole } from '@/hooks/use-members';
import { useCategories } from '@/hooks/use-categories';
import { usePaymentAccounts, ACCOUNT_TYPE_OPTIONS, accountTypeLabel, type PaymentAccountType } from '@/hooks/use-payment-accounts';
import { useReportCurrency, useSetReportCurrency } from '@/hooks/use-report-currency';
import { useMeusConvitesDeCadastro } from '@/hooks/use-admin';
import { Skeleton } from '@/components/ui/skeleton';
import { WorkspaceCreateDialog } from '@/components/workspace/WorkspaceCreateDialog';
import { apiClient } from '@/api/client';
import { getApiErrorMessage } from '@/lib/api-error';
import { copiarTexto } from '@/lib/clipboard';
import { toast } from '@/stores/toast';
import { useConfirm } from '@/components/ui/confirm';
import { CategoryGlyph } from '@/components/money/CategoryGlyph';
import { parseApiDate } from '@/lib/date';
import type { components } from '@/types/api.gen';
import { CURRENCIES } from '@/lib/currencies';
import { PageHeader } from '@/components/layout/PageHeader';

type Tab = 'profile' | 'security' | 'members' | 'categories' | 'accounts' | 'appearance' | 'audit' | 'convites';

// Moeda-base do workspace: a lista curada de moedas do app, com o código à mostra
const BASE_CURRENCY_OPTIONS = CURRENCIES.map((c) => ({
  value: c.code,
  label: `${c.code} — ${c.name}`,
}));

// Dry-run da troca de moeda-base: o backend devolve o tamanho da reconversão e
// as datas sem cotação, para a UI avisar ANTES de reescrever o histórico.
//
// Tipo GERADO, não escrito à mão. A interface manual que morava aqui listava
// `incomes/statements/financings` — campos que o backend deixou de devolver
// quando o ADR 0021 tirou renda, fatura e financiamento do workspace. O
// TypeScript não tinha como saber, e a confirmação de uma operação destrutiva
// passou a exibir "undefined" três vezes. Agora divergir não compila.
type BaseCurrencyPreview = components['schemas']['BaseCurrencyPreviewRead'];

const ROLE_LABELS: Record<WorkspaceRole, string> = {
  owner: 'Dono',
  admin: 'Admin',
  member: 'Membro',
  viewer: 'Leitor',
};

/** O que o membro VÊ (ADR 0018) — eixo separado do que ele PODE FAZER. */
const ACCESS_LABELS: Record<FinancialAccess, string> = {
  involved_only: 'Só o que o envolve',
  full_workspace: 'Todo o espaço',
};

function ProfileTab() {
  const { user, setUser } = useAuthStore();
  const { workspaces, currentWorkspaceId, switchWorkspace } = useWorkspaces();
  const navigate = useNavigate();
  const location = useLocation();

  /**
   * Trocar de workspace tem de mexer na URL, não só na store.
   *
   * `switchWorkspace` sozinho deixava dois contextos vivos ao mesmo tempo: a
   * store (e o `currentWorkspace` exibido aqui) apontando para a casa nova, e a
   * URL — de onde membros, categorias e todos os demais hooks leem o id — ainda
   * na antiga. Bastava mudar de aba dentro de Configurações para ver o nome e a
   * moeda de uma casa ao lado dos membros de outra, com risco real de
   * administrar a errada. A Sidebar sempre fez os dois; esta aba, não.
   */
  const trocar = (id: number) => {
    switchWorkspace(id);
    navigate(workspacePath(id, location.pathname));
  };
  const [name, setName] = React.useState(user?.name ?? '');
  const [saving, setSaving] = React.useState(false);
  const [saved, setSaved] = React.useState(false);
  const [createOpen, setCreateOpen] = React.useState(false);

  const saveProfile = async () => {
    setSaving(true);
    try {
      const res = await apiClient.patch('/auth/me', { name });
      setUser(res.data);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch {
      toast.error('Erro ao salvar o perfil');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
      <Card className="bg-card border-border shadow-xl">
        <CardHeader>
          <CardTitle>Informações do Perfil</CardTitle>
          <CardDescription>Gerencie como você é visto no sistema.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-6 pb-6 border-b border-border">
            <div className="w-20 h-20 rounded-full bg-primary/10 border-2 border-primary/20 flex items-center justify-center text-3xl font-bold text-primary shadow-inner">
              {user?.name?.[0] || 'U'}
            </div>
            <div>
              <p className="font-bold">{user?.name}</p>
              <p className="text-xs text-muted-foreground">{user?.email}</p>
            </div>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="name">Nome Completo</Label>
              <Input id="name" value={name} onChange={(e) => setName(e.target.value)} className="bg-background/50 border-border focus:ring-primary/20" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="email">E-mail</Label>
              <Input id="email" defaultValue={user?.email} disabled className="bg-background/50 opacity-50 border-border" />
            </div>
          </div>
        </CardContent>
        <CardFooter className="bg-accent/30 border-t border-border py-4 justify-end gap-3">
          {saved && <span className="text-emerald-500 text-sm font-bold flex items-center gap-1"><Check className="h-4 w-4" /> Salvo!</span>}
          <Button onClick={saveProfile} disabled={saving || name.trim().length < 1} className="bg-primary hover:bg-primary/90 text-primary-foreground font-bold shadow-lg shadow-primary/20">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Salvar Alterações'}
          </Button>
        </CardFooter>
      </Card>

      <Card className="bg-card border-border shadow-xl">
        <CardHeader>
          <CardTitle>Espaços</CardTitle>
          <CardDescription>Espaços ativos vinculados a esta conta. Clique para trocar.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {workspaces.map((ws) => (
            <button
              key={ws.id}
              type="button"
              onClick={() => trocar(ws.id)}
              className="w-full flex items-center justify-between p-4 rounded-xl bg-accent/30 border border-border/50 hover:bg-accent/40 transition-colors group text-left"
            >
              <div className="flex items-center gap-4">
                <div className="w-10 h-10 bg-primary/20 rounded-lg flex items-center justify-center group-hover:scale-110 transition-transform">
                  <Globe className="h-5 w-5 text-primary" />
                </div>
                <div>
                  <p className="text-sm font-bold">{ws.name}</p>
                  {ws.description && <p className="text-xs text-muted-foreground">{ws.description}</p>}
                </div>
              </div>
              {ws.id === currentWorkspaceId && (
                <Badge className="bg-primary/10 text-primary border-none">Atual</Badge>
              )}
            </button>
          ))}
          <Button
            variant="outline"
            onClick={() => setCreateOpen(true)}
            className="w-full border-dashed border-2 hover:bg-accent/50 text-muted-foreground hover:text-foreground h-12"
          >
            + Criar Novo Workspace
          </Button>
        </CardContent>
      </Card>

      <ReportCurrencyCard />

      <WorkspaceCreateDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  );
}

/**
 * Moeda em que os números PESSOAIS aparecem.
 *
 * O `useSetReportCurrency` existia e não era chamado por tela nenhuma: a moeda
 * de relatório só podia ser trocada batendo direto na API. Quem participa de
 * workspaces com moedas-base diferentes precisa dela — é o destino de conversão
 * da Visão global, e sem escolher fica no padrão para sempre.
 *
 * Não confundir com a moeda-base, que é do workspace e vive nas configurações
 * dele: trocar esta NÃO reescreve nada, só muda a moeda em que os totais
 * pessoais são expressos.
 */
function ReportCurrencyCard() {
  const atual = useReportCurrency();
  const setReportCurrency = useSetReportCurrency();
  const [moeda, setMoeda] = React.useState(atual);

  React.useEffect(() => setMoeda(atual), [atual]);

  return (
    <Card className="bg-card border-border shadow-xl">
      <CardHeader>
        <CardTitle>Moeda de relatório</CardTitle>
        <CardDescription>
          Moeda em que os seus números aparecem: renda, cartões, financiamentos e a
          Visão global, que soma workspaces de moedas-base diferentes. Não altera
          nenhum lançamento — só a moeda em que os totais são expressos.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap items-end gap-3">
        <div className="min-w-[240px] flex-1 space-y-2">
          <Label htmlFor="report-currency">Sua moeda</Label>
          <Select
            items={BASE_CURRENCY_OPTIONS}
            value={moeda}
            onValueChange={(v) => setMoeda(v as string)}
          >
            <SelectTrigger id="report-currency"><SelectValue /></SelectTrigger>
            <SelectContent>
              {BASE_CURRENCY_OPTIONS.map((o) => (
                <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button
          className="bg-primary font-bold"
          disabled={moeda === atual || setReportCurrency.isPending}
          onClick={async () => {
            try {
              await setReportCurrency.mutateAsync(moeda);
              toast.success('Moeda de relatório atualizada.');
            } catch (err) {
              toast.error(getApiErrorMessage(err, 'Não foi possível trocar a moeda.'));
            }
          }}
        >
          {setReportCurrency.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Salvar'}
        </Button>
      </CardContent>
    </Card>
  );
}

function SecurityTab() {
  const [currentPass, setCurrentPass] = React.useState('');
  const [newPass, setNewPass] = React.useState('');
  const [confirmPass, setConfirmPass] = React.useState('');
  const [saving, setSaving] = React.useState(false);
  const [message, setMessage] = React.useState<{ ok: boolean; text: string } | null>(null);

  const changePassword = async () => {
    if (newPass.length < 6) {
      setMessage({ ok: false, text: 'A nova senha deve ter pelo menos 6 caracteres.' });
      return;
    }
    if (newPass !== confirmPass) {
      setMessage({ ok: false, text: 'As senhas não coincidem.' });
      return;
    }
    setSaving(true);
    setMessage(null);
    try {
      await apiClient.post('/auth/change-password', {
        current_password: currentPass,
        new_password: newPass,
      });
      setMessage({ ok: true, text: 'Senha alterada com sucesso!' });
      setCurrentPass(''); setNewPass(''); setConfirmPass('');
    } catch (err) {
      setMessage({ ok: false, text: getApiErrorMessage(err, 'Erro ao alterar a senha.') });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
      <Card className="bg-card border-border shadow-xl">
        <CardHeader>
          <CardTitle>Segurança da Conta</CardTitle>
          <CardDescription>Proteja seu acesso e gerencie senhas.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="current-pass">Senha Atual</Label>
              <Input id="current-pass" type="password" autoComplete="current-password" placeholder="••••••••" value={currentPass} onChange={(e) => setCurrentPass(e.target.value)} className="bg-background/50 border-border" />
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="new-pass">Nova Senha</Label>
                <Input id="new-pass" type="password" autoComplete="new-password" placeholder="••••••••" value={newPass} onChange={(e) => setNewPass(e.target.value)} className="bg-background/50 border-border" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="confirm-pass">Confirmar Nova Senha</Label>
                <Input id="confirm-pass" type="password" autoComplete="new-password" placeholder="••••••••" value={confirmPass} onChange={(e) => setConfirmPass(e.target.value)} className="bg-background/50 border-border" />
              </div>
            </div>
          </div>
          {message && (
            <p className={`text-sm font-medium ${message.ok ? 'text-emerald-500' : 'text-destructive'}`}>{message.text}</p>
          )}
        </CardContent>
        <CardFooter className="bg-accent/30 border-t border-border py-4 justify-end">
          <Button onClick={changePassword} disabled={saving || !currentPass || !newPass} className="bg-primary hover:bg-primary/90 text-primary-foreground font-bold shadow-lg shadow-primary/20">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Atualizar Senha'}
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}

function MembersTab() {
  const { user } = useAuthStore();
  const { currentWorkspace, update: updateWorkspace, remove: removeWorkspace } = useWorkspaces();
  const {
    members, invites, inviteByEmail, createInviteLink, revokeInvite,
    updateMemberRole, updateMemberAccess, removeMember, leaveWorkspace,
  } = useMembers();

  const confirm = useConfirm();
  const myRole = members.find((m) => m.user_id === user?.id)?.role;
  const isAdmin = myRole === 'admin' || myRole === 'owner';
  const isOwner = myRole === 'owner';

  const [wsName, setWsName] = React.useState('');
  const [inviteEmail, setInviteEmail] = React.useState('');
  const [inviteRole, setInviteRole] = React.useState<WorkspaceRole>('member');
  // Default FECHADO, igual ao do backend (ADR 0018): quem entra vê o que o
  // envolve, e abrir para os números da casa é ato explícito de quem convida.
  const [inviteAccess, setInviteAccess] = React.useState<FinancialAccess>('involved_only');
  const [feedback, setFeedback] = React.useState<{ ok: boolean; text: string } | null>(null);
  const [inviteLink, setInviteLink] = React.useState<string | null>(null);
  const [copied, setCopied] = React.useState(false);

  React.useEffect(() => {
    setWsName(currentWorkspace?.name ?? '');
  }, [currentWorkspace?.name]);

  const [baseCurrency, setBaseCurrency] = React.useState('BRL');
  React.useEffect(() => {
    setBaseCurrency(currentWorkspace?.base_currency ?? 'BRL');
  }, [currentWorkspace?.base_currency]);

  const showError = (err: unknown, fallback: string) => {
    setFeedback({ ok: false, text: getApiErrorMessage(err, fallback) });
  };

  const handleInvite = async () => {
    setFeedback(null);
    try {
      await inviteByEmail({
        email: inviteEmail.trim(), role: inviteRole, financial_access: inviteAccess,
      });
      setInviteEmail('');
      // Ninguém mais entra sem aceitar — nem quem já tem conta. Quem já tem
      // recebe o aviso dentro do app (sino) além do e-mail.
      setFeedback({
        ok: true,
        text: 'Convite enviado! A pessoa entra assim que aceitar — por e-mail ou pelo aviso dentro do app.',
      });
    } catch (err) {
      showError(err, 'Erro ao convidar.');
    }
  };

  const handleCreateLink = async () => {
    setFeedback(null);
    try {
      const res = await createInviteLink({
        role: inviteRole, financial_access: inviteAccess, expires_days: 7,
      });
      setInviteLink(res.url);
    } catch (err) {
      showError(err, 'Erro ao gerar link.');
    }
  };

  const copyLink = async () => {
    if (!inviteLink) return;
    // `navigator.clipboard` é `undefined` fora de contexto seguro, e o próprio
    // SETUP.md documenta um deploy em `http://` na rede local: a chamada direta
    // estourava um TypeError ali, e o "Copiado!" nunca aparecia.
    const ok = await copiarTexto(inviteLink);
    if (!ok) {
      toast.error('Não foi possível copiar. Selecione o link manualmente.');
      return;
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const pendingInvites = invites.filter((i) => i.status === 'pending');

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
      {isAdmin && (
        <Card className="bg-card border-border shadow-xl">
          <CardHeader>
            <CardTitle>Espaço</CardTitle>
            <CardDescription>Nome e configurações de "{currentWorkspace?.name}".</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* `items-end` para o botão continuar alinhado à base do campo agora
                que ele ganhou um rótulo acima. */}
            <div className="flex items-end gap-3">
              {/* Rótulo visível, não só o título do cartão: o campo de renomear
                  o workspace não tinha nome acessível nenhum — um leitor de tela
                  anunciava "caixa de texto" com o nome do espaço dentro e nada que
                  dissesse o que ele edita. Era a única violação CRÍTICA de axe da
                  tela, e ninguém a via porque a aba de Membros nunca era
                  renderizada por teste. */}
              <div className="flex-1 space-y-2">
                <Label htmlFor="workspace-name">Nome do espaço</Label>
                <Input
                  id="workspace-name"
                  value={wsName}
                  onChange={(e) => setWsName(e.target.value)}
                  className="bg-background/50 border-border"
                />
              </div>
              <Button
                onClick={async () => {
                  try {
                    await updateWorkspace({ id: currentWorkspace!.id, data: { name: wsName } });
                    setFeedback({ ok: true, text: 'Espaço renomeado!' });
                  } catch (err) { showError(err, 'Erro ao renomear.'); }
                }}
                disabled={!wsName.trim() || wsName === currentWorkspace?.name}
                className="bg-primary font-bold"
              >
                Renomear
              </Button>
            </div>

            <div className="space-y-2">
              <Label htmlFor="base-currency">Moeda-base</Label>
              <p className="text-xs text-muted-foreground">
                Moeda em que todos os totais são somados. Lançamentos em outra moeda
                são convertidos na entrada. Trocar <strong>reconverte todo o histórico</strong>{' '}
                pela cotação da data de cada lançamento.
              </p>
              <div className="flex gap-3">
                <Select
                  items={BASE_CURRENCY_OPTIONS}
                  value={baseCurrency}
                  onValueChange={(value) => setBaseCurrency(value as string)}
                >
                  <SelectTrigger id="base-currency" className="w-full sm:w-[220px]">
                    <SelectValue placeholder="Moeda-base" />
                  </SelectTrigger>
                  <SelectContent>
                    {BASE_CURRENCY_OPTIONS.map((o) => (
                      <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  variant="outline"
                  disabled={!baseCurrency || baseCurrency === currentWorkspace?.base_currency}
                  onClick={async () => {
                    // Dry-run primeiro: a troca REESCREVE todo o histórico
                    // financeiro do workspace, então o usuário precisa ver o
                    // tamanho da operação (e as cotações que faltam) antes.
                    let preview: BaseCurrencyPreview;
                    try {
                      const res = await apiClient.get(
                        `/workspaces/${currentWorkspace!.id}/base-currency/preview`,
                        { params: { to: baseCurrency } },
                      );
                      preview = res.data;
                    } catch (err) {
                      showError(err, 'Não foi possível simular a troca de moeda.');
                      return;
                    }

                    if (preview.missing_rates.length > 0) {
                      showError(
                        null,
                        `Faltam cotações para ${preview.missing_rates.length} data(s) do ` +
                        `histórico (${preview.missing_rates.slice(0, 3).join(', ')}` +
                        `${preview.missing_rates.length > 3 ? '…' : ''}). ` +
                        'Rode o backfill de câmbio antes de trocar a moeda.',
                      );
                      return;
                    }

                    // Os quatro números que o backend realmente devolve. A versão
                    // anterior listava renda, fatura e financiamento — que saíram
                    // do workspace no ADR 0021 — e imprimia "undefined" três
                    // vezes na confirmação de uma operação destrutiva.
                    const itens = [
                      [preview.transactions, 'lançamento(s)'],
                      [preview.settlements, 'acerto(s)'],
                      [preview.estimates, 'orçamento(s)'],
                      [preview.recurring, 'recorrência(s)'],
                    ] as const;
                    const afetados = itens
                      .filter(([n]) => n > 0)
                      .map(([n, rotulo]) => `${n} ${rotulo}`);

                    const ok = await confirm({
                      title: 'Trocar a moeda-base',
                      description:
                        `Isto reconverte o histórico de ${preview.from_currency} para ` +
                        `${preview.to_currency} pela cotação da data de cada registro: ` +
                        `${afetados.length > 0 ? afetados.join(', ') : 'nenhum registro'}. ` +
                        'Cartões, contas, financiamentos e rendas são pessoais e não mudam. ' +
                        'Faça backup do banco antes — não há desfazer automático.',
                      confirmLabel: 'Reconverter e trocar',
                      destructive: true,
                    });
                    if (!ok) return;
                    try {
                      await updateWorkspace({
                        id: currentWorkspace!.id,
                        data: { base_currency: baseCurrency },
                      });
                      setFeedback({ ok: true, text: 'Moeda-base trocada e histórico reconvertido!' });
                    } catch (err) { showError(err, 'Erro ao trocar a moeda-base.'); }
                  }}
                >
                  Salvar moeda
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      <Card className="bg-card border-border shadow-xl">
        <CardHeader>
          <CardTitle>Membros ({members.length})</CardTitle>
          <CardDescription>Quem tem acesso a este espaço.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {members.map((m) => (
            // Empilha abaixo de `sm`: os dois seletores fixos (112px + 168px) e
            // o botão de remover somam 328px que se recusavam a encolher
            // (`shrink-0`), contra ~272px disponíveis num telefone de 393px — o
            // seletor de visibilidade e a exclusão ficavam cortados fora do
            // cartão, sem rolagem que os alcançasse.
            <div key={m.user_id} className="flex flex-col gap-3 p-3 rounded-xl bg-accent/30 border border-border/50 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-3 min-w-0">
                <div className="w-9 h-9 rounded-full bg-primary/10 flex items-center justify-center font-bold text-primary shrink-0">
                  {m.user_name[0]}
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-bold truncate">{m.user_name} {m.user_id === user?.id && <span className="text-muted-foreground font-normal">(você)</span>}</p>
                  <p className="text-xs text-muted-foreground truncate">{m.user_email}</p>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2 sm:shrink-0">
                {isAdmin && m.role !== 'owner' && m.user_id !== user?.id ? (
                  <>
                    <Select
                      items={ROLE_LABELS}
                      value={m.role}
                      onValueChange={async (value) => {
                        const papel = value as WorkspaceRole;
                        try {
                          // `updateMemberRole` não aceita `financial_access` — e é
                          // por isso que ele existe separado (ver `use-members`):
                          // esta chamada mandava o acesso EFETIVO do admin de
                          // volta como configuração, e rebaixar AMPLIAVA a visão.
                          await updateMemberRole({ userId: m.user_id, role: papel });
                          if (m.role === 'admin') {
                            setFeedback({
                              ok: true,
                              text: `${m.user_name} agora é ${ROLE_LABELS[papel]} e vê só o que o envolve — abra a visibilidade ao lado se quiser.`,
                            });
                          }
                        } catch (err) { showError(err, 'Erro ao alterar papel.'); }
                      }}
                    >
                      {/* Rótulo por LINHA, como o irmão de visibilidade ao lado:
                          são N seletores iguais numa tabela, e sem nome
                          acessível o leitor de tela anuncia só o valor atual
                          ("Membro") — sem dizer de quem nem do quê. */}
                      <SelectTrigger
                        aria-label={`Papel de ${m.user_name}`}
                        className="h-9 w-[112px] text-xs font-semibold"
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="viewer">Leitor</SelectItem>
                        <SelectItem value="member">Membro</SelectItem>
                        {isOwner && <SelectItem value="admin">Admin</SelectItem>}
                      </SelectContent>
                    </Select>
                    {/* Visibilidade financeira — o eixo que existia só na API.
                        `admin`/`owner` veem tudo pelo cargo, então para eles o
                        controle não é editável. Não some, porém: sumindo, o eixo
                        parecia não existir para admin, e quem rebaixava não
                        imaginava que a visibilidade era assunto do rebaixamento. */}
                    {m.role === 'admin' ? (
                      <Badge
                        variant="outline"
                        className="h-9 px-3 border-border text-muted-foreground font-semibold"
                        title="Admin vê os números do espaço pelo cargo. Ao rebaixar, a visibilidade volta a 'Só o que o envolve'."
                      >
                        Todo o espaço (admin)
                      </Badge>
                    ) : (
                      <Select
                        items={ACCESS_LABELS}
                        value={m.financial_access}
                        onValueChange={async (value) => {
                          try {
                            await updateMemberAccess({
                              userId: m.user_id,
                              role: m.role,
                              financial_access: value as FinancialAccess,
                            });
                          } catch (err) { showError(err, 'Erro ao alterar a visibilidade.'); }
                        }}
                      >
                        <SelectTrigger
                          aria-label={`Visibilidade financeira de ${m.user_name}`}
                          className="h-9 w-[168px] text-xs font-semibold"
                        >
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="involved_only">Só o que o envolve</SelectItem>
                          <SelectItem value="full_workspace">Todo o espaço</SelectItem>
                        </SelectContent>
                      </Select>
                    )}
                    {/* `aria-label` pelo mesmo motivo dos dois seletores acima
                        (linha 561): é um botão só de ícone, repetido por linha,
                        e sem nome acessível o leitor de tela anuncia "botão" —
                        numa ação destrutiva. Aqui ele tinha passado batido. */}
                    <Button
                      variant="ghost" size="sm"
                      aria-label={`Remover ${m.user_name} do workspace`}
                      onClick={async () => {
                        const ok = await confirm({
                          title: 'Remover membro',
                          description: `Remover ${m.user_name} do workspace?`,
                          confirmLabel: 'Remover',
                          destructive: true,
                        });
                        if (!ok) return;
                        try { await removeMember(m.user_id); }
                        catch (err) { showError(err, 'Erro ao remover.'); }
                      }}
                      className="h-9 w-9 p-0 text-destructive hover:bg-destructive/10"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </>
                ) : (
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="border-border text-muted-foreground">{ROLE_LABELS[m.role]}</Badge>
                    <Badge variant="outline" className="border-border text-muted-foreground">
                      {ACCESS_LABELS[m.financial_access] ?? ACCESS_LABELS.involved_only}
                    </Badge>
                  </div>
                )}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      {isAdmin && (
        <Card className="bg-card border-border shadow-xl">
          <CardHeader>
            <CardTitle>Convidar Pessoas</CardTitle>
            <CardDescription>Por email (direto) ou por link compartilhável (expira em 7 dias).</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-col md:flex-row gap-3">
              {/* `placeholder` não é rótulo: some ao digitar e não é anunciado
                  como nome do campo. Os seletores ao lado já tinham `aria-label`;
                  o e-mail, que é o campo principal do formulário, não tinha. */}
              <Input
                aria-label="E-mail de quem você quer convidar"
                placeholder="email@exemplo.com"
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                className="bg-background/50 border-border flex-1"
              />
              <Select items={ROLE_LABELS} value={inviteRole} onValueChange={(value) => setInviteRole(value as WorkspaceRole)}>
                <SelectTrigger aria-label="Papel do convidado" className="h-10 w-[130px] text-sm font-semibold"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="viewer">Leitor</SelectItem>
                  <SelectItem value="member">Membro</SelectItem>
                  {isOwner && <SelectItem value="admin">Admin</SelectItem>}
                </SelectContent>
              </Select>
              {/* Visibilidade do convidado: vale tanto para o convite por e-mail
                  quanto para o link. Sem este controle, a permissão só existia
                  por chamada direta à API. */}
              {inviteRole !== 'admin' && (
                <Select
                  items={ACCESS_LABELS}
                  value={inviteAccess}
                  onValueChange={(value) => setInviteAccess(value as FinancialAccess)}
                >
                  <SelectTrigger aria-label="Visibilidade financeira do convidado" className="h-10 w-[186px] text-sm font-semibold"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="involved_only">Só o que o envolve</SelectItem>
                    <SelectItem value="full_workspace">Todo o espaço</SelectItem>
                  </SelectContent>
                </Select>
              )}
              <Button onClick={handleInvite} disabled={!inviteEmail.includes('@')} className="bg-primary font-bold">
                Convidar
              </Button>
              <Button variant="outline" onClick={handleCreateLink} className="gap-2">
                <LinkIcon className="h-4 w-4" /> Gerar link
              </Button>
            </div>

            {inviteLink && (
              <div className="flex items-center gap-2 p-3 rounded-lg bg-accent/40 border border-border">
                <code className="text-xs flex-1 truncate">{inviteLink}</code>
                <Button variant="ghost" size="sm" onClick={copyLink} className="h-8 gap-1 shrink-0">
                  {copied ? <Check className="h-3.5 w-3.5 text-emerald-500" /> : <Copy className="h-3.5 w-3.5" />}
                  {copied ? 'Copiado' : 'Copiar'}
                </Button>
              </div>
            )}

            {feedback && (
              <p className={`text-sm font-medium ${feedback.ok ? 'text-emerald-500' : 'text-destructive'}`}>{feedback.text}</p>
            )}

            {pendingInvites.length > 0 && (
              <div className="space-y-2 pt-2 border-t border-border">
                <p className="text-xs uppercase tracking-widest font-bold text-muted-foreground">Convites pendentes</p>
                {pendingInvites.map((inv) => (
                  <div key={inv.id} className="flex items-center justify-between p-2 rounded-lg hover:bg-accent/30">
                    <div className="flex items-center gap-2 text-sm min-w-0">
                      {inv.email
                        ? <span className="truncate">{inv.email}</span>
                        : <span className="flex items-center gap-1 text-muted-foreground"><LinkIcon className="h-3 w-3" /> Link de convite</span>}
                      <Badge variant="outline" className="border-border text-muted-foreground text-[10px]">{ROLE_LABELS[inv.role]}</Badge>
                    </div>
                    <Button
                      variant="ghost" size="sm"
                      onClick={async () => { try { await revokeInvite(inv.id); } catch (err) { showError(err, 'Erro ao revogar.'); } }}
                      className="h-7 text-xs text-destructive hover:bg-destructive/10"
                    >
                      Revogar
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <Card className="bg-card border-destructive/30 shadow-xl">
        <CardHeader>
          <CardTitle className="text-destructive">Zona de Perigo</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col md:flex-row gap-3">
          {!isOwner && (
            <Button
              variant="outline"
              className="border-destructive/40 text-destructive hover:bg-destructive/10"
              onClick={async () => {
                const ok = await confirm({
                  title: 'Sair do espaço',
                  description: 'Sair deste espaço? Você perderá o acesso.',
                  confirmLabel: 'Sair',
                  destructive: true,
                });
                if (!ok) return;
                try { await leaveWorkspace(); } catch (err) { showError(err, 'Erro ao sair.'); }
              }}
            >
              Sair do workspace
            </Button>
          )}
          {isOwner && (
            <Button
              variant="outline"
              className="border-destructive/40 text-destructive hover:bg-destructive/10"
              onClick={async () => {
                const ok = await confirm({
                  title: 'Excluir espaço',
                  description: `Excluir o espaço "${currentWorkspace?.name}"? Esta ação não pode ser desfeita.`,
                  confirmLabel: 'Excluir',
                  destructive: true,
                });
                if (!ok) return;
                try { await removeWorkspace(currentWorkspace!.id); } catch (err) { showError(err, 'Erro ao excluir.'); }
              }}
            >
              Excluir workspace
            </Button>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function CategoriesTab() {
  const { categories, create, update, remove } = useCategories();
  const confirm = useConfirm();
  const [newName, setNewName] = React.useState('');
  const [editingId, setEditingId] = React.useState<number | null>(null);
  const [editName, setEditName] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);

  const handleCreate = async () => {
    if (newName.trim().length < 2) return;
    setError(null);
    try {
      await create({ name: newName.trim() });
      setNewName('');
    } catch {
      setError('Erro ao criar categoria.');
    }
  };

  const handleRename = async (id: number) => {
    if (editName.trim().length < 2) return;
    setError(null);
    try {
      await update({ id, data: { name: editName.trim() } });
      setEditingId(null);
    } catch {
      setError('Erro ao renomear categoria.');
    }
  };

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
      <Card className="bg-card border-border shadow-xl">
        <CardHeader>
          <CardTitle>Categorias</CardTitle>
          <CardDescription>
            Usadas para classificar despesas e alimentar o gráfico por categoria nos relatórios.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-3">
            <Input
              placeholder="Nova categoria..."
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
              className="min-w-48 flex-1 bg-background/50 border-border"
            />
            <Button onClick={handleCreate} disabled={newName.trim().length < 2} className="bg-primary font-bold gap-2">
              <Plus className="h-4 w-4" /> Criar
            </Button>
          </div>
          {error && <p className="text-xs text-destructive font-medium">{error}</p>}

          <div className="grid gap-2 md:grid-cols-2">
            {categories.map((cat) => (
              <div key={cat.id} className="flex items-center justify-between p-3 rounded-xl bg-accent/30 border border-border/50 group">
                {editingId === cat.id ? (
                  <div className="flex items-center gap-2 flex-1">
                    <Input
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleRename(cat.id)}
                      className="h-8 bg-background/50"
                      autoFocus
                    />
                    <Button size="sm" className="h-8" onClick={() => handleRename(cat.id)}>OK</Button>
                  </div>
                ) : (
                  <>
                    <div className="flex items-center gap-2.5 min-w-0">
                      <CategoryGlyph category={cat} size="sm" />
                      <span className="text-sm font-medium truncate">{cat.name}</span>
                    </div>
                    <div className="flex items-center gap-1 transition-opacity sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100 shrink-0">
                      <Button
                        variant="ghost" size="sm"
                        className="h-7 text-xs"
                        onClick={() => { setEditingId(cat.id); setEditName(cat.name); }}
                      >
                        Renomear
                      </Button>
                      <Button
                        variant="ghost" size="sm"
                        aria-label={`Excluir a categoria ${cat.name}`}
                        className="h-7 w-7 p-0 text-destructive hover:bg-destructive/10"
                        onClick={async () => {
                          const ok = await confirm({
                            title: 'Excluir categoria',
                            description: `Excluir a categoria "${cat.name}"?`,
                            confirmLabel: 'Excluir',
                            destructive: true,
                          });
                          if (!ok) return;
                          try { await remove(cat.id); } catch { setError('Erro ao excluir.'); }
                        }}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </>
                )}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function AccountsTab() {
  const { accounts, create, update, remove, isError } = usePaymentAccounts();
  const confirm = useConfirm();
  const [newName, setNewName] = React.useState('');
  const [newType, setNewType] = React.useState<PaymentAccountType>('checking');
  const [error, setError] = React.useState<string | null>(null);

  const handleCreate = async () => {
    if (newName.trim().length < 2) return;
    setError(null);
    try {
      await create({ name: newName.trim(), type: newType });
      setNewName('');
    } catch (err) {
      setError(getApiErrorMessage(err, 'Erro ao criar conta.'));
    }
  };

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
      <Card className="bg-card border-border shadow-xl">
        <CardHeader>
          <CardTitle>Contas e Carteiras</CardTitle>
          <CardDescription>
            De onde sai o dinheiro: contas bancárias, carteiras digitais e dinheiro vivo.
            Cada pagador de uma despesa pode informar a origem do pagamento.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-3">
            <Input
              placeholder="Nova conta... (ex: Nubank)"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
              className="min-w-48 flex-1 bg-background/50 border-border"
            />
            <Select items={ACCOUNT_TYPE_OPTIONS} value={newType} onValueChange={(value) => setNewType(value as PaymentAccountType)}>
              <SelectTrigger aria-label="Tipo da conta" className="h-10 w-full text-sm sm:w-[150px]"><SelectValue /></SelectTrigger>
              <SelectContent>
                {ACCOUNT_TYPE_OPTIONS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button onClick={handleCreate} disabled={newName.trim().length < 2} className="bg-primary font-bold gap-2">
              <Plus className="h-4 w-4" /> Criar
            </Button>
          </div>
          {error && <p className="text-xs text-destructive font-medium">{error}</p>}
          {isError && <p className="text-xs text-destructive font-medium">Erro ao carregar as contas.</p>}

          <div className="grid gap-2 md:grid-cols-2">
            {accounts.map((account) => (
              <div key={account.id} className="flex items-center justify-between p-3 rounded-xl bg-accent/30 border border-border/50 group">
                <div className="flex items-center gap-2 min-w-0">
                  <Wallet className={`h-4 w-4 shrink-0 ${account.active ? 'text-primary' : 'text-muted-foreground'}`} />
                  <div className="min-w-0">
                    <span className={`text-sm font-bold truncate block ${account.active ? '' : 'text-muted-foreground line-through'}`}>
                      {account.name}
                    </span>
                    <span className="text-[10px] text-muted-foreground">{accountTypeLabel(account.type)}</span>
                  </div>
                </div>
                <div className="flex items-center gap-1 transition-opacity sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100 shrink-0">
                  <Button
                    variant="ghost" size="sm"
                    className="h-7 text-xs"
                    onClick={async () => {
                      try { await update({ id: account.id, data: { active: !account.active } }); }
                      catch (err) { setError(getApiErrorMessage(err, 'Erro ao atualizar conta.')); }
                    }}
                  >
                    {account.active ? 'Desativar' : 'Reativar'}
                  </Button>
                  <Button
                    variant="ghost" size="sm"
                    aria-label={`Excluir a conta ${account.name}`}
                    className="h-7 w-7 p-0 text-destructive hover:bg-destructive/10"
                    onClick={async () => {
                      const ok = await confirm({
                        title: 'Excluir conta',
                        description: `Excluir a conta "${account.name}"? Pagamentos antigos preservam o histórico.`,
                        confirmLabel: 'Excluir',
                        destructive: true,
                      });
                      if (!ok) return;
                      try { await remove(account.id); }
                      catch (err) { setError(getApiErrorMessage(err, 'Erro ao excluir conta.')); }
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            ))}
            {accounts.length === 0 && (
              <p className="text-sm text-muted-foreground col-span-2">
                Nenhuma conta cadastrada ainda.
              </p>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function AppearanceTab() {
  const { theme, setTheme } = useTheme();
  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
      <Card className="bg-card border-border shadow-xl">
        <CardHeader>
          <CardTitle>Tema e Aparência</CardTitle>
          <CardDescription>Personalize a interface do seu jeito.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="grid grid-cols-3 gap-4">
            {[
              { id: 'light', name: 'Claro', icon: Sun },
              { id: 'dark', name: 'Escuro', icon: Moon },
              { id: 'system', name: 'Sistema', icon: Laptop },
            ].map((t) => (
              <button
                key={t.id}
                onClick={() => setTheme(t.id as 'light' | 'dark' | 'system')}
                className={`flex flex-col items-center gap-3 p-4 rounded-xl border-2 transition-all ${
                  theme === t.id
                    ? 'border-primary bg-primary/5'
                    : 'border-border bg-accent/30 hover:border-border/80'
                }`}
              >
                <t.icon className={`h-8 w-8 ${theme === t.id ? 'text-primary' : 'text-muted-foreground'}`} />
                <span className={`text-xs font-bold ${theme === t.id ? 'text-primary' : 'text-muted-foreground'}`}>
                  {t.name}
                </span>
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      <InstalarAppCard />
    </div>
  );
}

/**
 * "Instalar aplicativo" — em Aparência porque é disso que se trata: onde e como
 * o app aparece, ao lado da escolha de tema.
 *
 * Os quatro estados vêm de `useInstallPrompt`, e cada um mostra coisa
 * diferente. O caso que mais importa é o **iOS**: lá não existe evento de
 * instalação, e um botão que não faz nada seria pior do que nenhum — então o
 * cartão vira instrução, com o caminho exato do Safari.
 */
function InstalarAppCard() {
  const { estado, instalar } = useInstallPrompt();

  if (estado === 'indisponivel') return null;

  return (
    <Card className="bg-card border-border shadow-xl">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Smartphone className="h-5 w-5 text-primary" />
          Aplicativo no celular
        </CardTitle>
        <CardDescription>
          Instale para abrir em tela cheia, com ícone próprio, sem a barra de endereço.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {estado === 'instalado' && (
          <p className="text-sm text-muted-foreground">
            Você já está usando o aplicativo instalado. ✅
          </p>
        )}

        {estado === 'disponivel' && (
          <Button type="button" onClick={() => void instalar()} className="h-11 w-full gap-2 sm:w-auto">
            <Download className="h-4 w-4" /> Instalar aplicativo
          </Button>
        )}

        {estado === 'manual-ios' && (
          <div className="space-y-2 text-sm text-muted-foreground">
            <p>No iPhone e no iPad a instalação é pelo Safari, em dois toques:</p>
            <ol className="ml-4 list-decimal space-y-1">
              <li>Toque em <strong className="text-foreground">Compartilhar</strong> (o quadrado com a seta para cima).</li>
              <li>Escolha <strong className="text-foreground">Adicionar à Tela de Início</strong>.</li>
            </ol>
            <p className="text-xs">
              Só funciona no Safari — em outros navegadores do iPhone a opção não aparece.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

const AUDIT_ACTION_LABELS: Record<string, string> = {
  create: 'Criou',
  update: 'Alterou',
  delete: 'Removeu',
  login: 'Entrou',
  logout: 'Saiu',
};

const AUDIT_RESOURCE_LABELS: Record<string, string> = {
  Transaction: 'lançamento',
  Income: 'renda',
  Workspace: 'espaço',
  Settlement: 'acerto',
  Category: 'categoria',
  CreditCard: 'cartão',
  Financing: 'financiamento',
  Tag: 'tag',
  PaymentAccount: 'conta',
};

// Trilha de auditoria (read-only) — só admin/owner chegam aqui (o backend também
// recusa com 403). Mostra quando, quem, ação e recurso das 100 ações recentes.
function AuditTab() {
  const { entries, isLoading } = useAudit();
  const { members } = useMembers();

  const who = (id?: number | null) =>
    id == null ? 'Sistema' : members.find((m) => m.user_id === id)?.user_name ?? `#${id}`;
  const resource = (type?: string | null, resId?: number | null) => {
    if (!type) return '—';
    const label = AUDIT_RESOURCE_LABELS[type] ?? type;
    return resId != null ? `${label} #${resId}` : label;
  };

  return (
    <Card className="bg-card border-border shadow-xl">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <History className="h-5 w-5 text-primary" /> Auditoria
        </CardTitle>
        <CardDescription>Ações recentes neste espaço (as 100 últimas). Visível só para admins.</CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        {isLoading ? (
          <div className="flex h-32 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
          </div>
        ) : entries.length === 0 ? (
          <p className="py-12 text-center text-sm text-muted-foreground">Nenhuma ação registrada ainda.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="border-border hover:bg-transparent">
                <TableHead className="text-xs font-semibold text-muted-foreground">Quando</TableHead>
                <TableHead className="text-xs font-semibold text-muted-foreground">Quem</TableHead>
                <TableHead className="text-xs font-semibold text-muted-foreground">Ação</TableHead>
                <TableHead className="text-xs font-semibold text-muted-foreground">Recurso</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {entries.map((e) => (
                <TableRow key={e.id} className="border-border hover:bg-accent/30">
                  <TableCell className="text-sm text-muted-foreground">
                    {parseApiDate(e.created_at).toLocaleString('pt-BR')}
                  </TableCell>
                  <TableCell className="text-sm font-medium text-foreground">{who(e.user_id)}</TableCell>
                  <TableCell className="text-sm">{AUDIT_ACTION_LABELS[e.action] ?? e.action}</TableCell>
                  <TableCell className="text-sm text-foreground">{resource(e.resource_type, e.resource_id)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

interface MenuItem {
  id: Tab;
  label: string;
  icon: typeof User;
}

/** Casca das duas telas de configuração: menu lateral + conteúdo da aba. */
function SettingsShell({
  title,
  subtitle,
  menuItems,
  activeTab,
  onSelect,
  children,
}: {
  title: string;
  subtitle: string;
  menuItems: MenuItem[];
  activeTab: Tab;
  onSelect: (tab: Tab) => void;
  children: React.ReactNode;
}) {
  const { logout } = useAuth();
  return (
    <div className="space-y-8 animate-in slide-in-from-bottom-4 duration-700 pb-20">
      <PageHeader title={title} subtitle={subtitle} />
      <div className="grid gap-6 md:grid-cols-[240px_1fr]">
        {/*
          Faixa rolável no celular, coluna no desktop.
          A pilha de botões de largura total custava ~280px de altura antes do
          primeiro campo — mais de um terço da tela de um aparelho de 844px, só
          para escolher uma aba. Na horizontal ela ocupa 44px e continua
          mostrando que há mais opções à direita (a borda cortada é a pista).

          Aqui houve um `-mx-4 px-4` para sangrar a faixa até a borda da tela.
          Saiu: ele deixa o elemento com EXATAMENTE a largura da viewport, e aí
          qualquer discrepância de 1px em qualquer lugar da página vira rolagem
          horizontal. Foi o que aconteceu — `mobile_layout.mobile.spec.ts`
          reprovou no CI do Linux com "/w/:id/settings rola 4px", numa
          combinação que a mesma execução no Windows não produzia. O ganho era
          estético; o custo era uma tela quebrada em metade dos aparelhos.
        */}
        <aside className="flex gap-2 overflow-x-auto pb-1 scrollbar-none md:flex-col md:space-y-2 md:overflow-visible md:pb-0">
          {menuItems.map((item) => (
            <Button
              key={item.id}
              variant="ghost"
              className={`h-10 shrink-0 justify-start gap-2 transition-all md:w-full md:gap-3 ${
                activeTab === item.id
                  ? 'bg-primary text-primary-foreground font-bold shadow-lg shadow-primary/20'
                  : 'text-muted-foreground hover:text-foreground hover:bg-accent'
              }`}
              onClick={() => onSelect(item.id)}
            >
              <item.icon className={`h-4 w-4 ${activeTab === item.id ? 'text-primary-foreground' : ''}`} />
              {item.label}
            </Button>
          ))}
          {/* "Sair da Conta" fica FORA da faixa no celular: a gaveta "Mais" já
              tem o mesmo botão, e aqui ele viraria uma sexta aba vermelha
              disputando espaço com as opções que a pessoa veio usar. */}
          <div className="hidden pt-4 border-t border-border mt-4 md:block">
            <Button variant="ghost" className="w-full justify-start gap-3 text-destructive hover:bg-destructive/10 transition-colors" onClick={() => logout()}>
              <LogOut className="h-4 w-4" /> Sair da Conta
            </Button>
          </div>
        </aside>

        <main className="min-h-[500px]">{children}</main>
      </div>
    </div>
  );
}

const MENU_PESSOAL: MenuItem[] = [
  { id: 'profile', label: 'Perfil', icon: User },
  { id: 'security', label: 'Segurança', icon: Shield },
  { id: 'accounts', label: 'Contas', icon: Wallet },
  // Convidar alguém para o SITE (ADR 0026) — diferente de convidar para um
  // workspace, que vive em `/w/:id/settings`. Fica aqui porque é um ato da
  // pessoa, não de uma casa: o convite não põe ninguém dentro do seu workspace.
  { id: 'convites', label: 'Convidar alguém', icon: Ticket },
  { id: 'appearance', label: 'Aparência', icon: Palette },
];

/**
 * Convite de cadastro no site, emitido por usuário comum.
 *
 * Sujeito a `who_can_invite` e à cota mensal — quando o administrador restringe
 * a emissão a administradores, o servidor recusa com 403 e a mensagem explica.
 */
function ConvitesDeCadastroTab() {
  const { data: convites, isLoading, convidar } = useMeusConvitesDeCadastro();
  const [email, setEmail] = React.useState('');

  const enviar = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const convite = await convidar.mutateAsync({ email: email.trim() || undefined });
      setEmail('');
      const copiou = await copiarTexto(convite.link);
      toast.success(
        convite.email
          ? `Convite enviado para ${convite.email}.${copiou ? ' O link também foi copiado.' : ''}`
          : copiou
            ? 'Link de convite criado e copiado.'
            : 'Convite criado. Use "Copiar link" na lista abaixo.',
      );
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-foreground">Convidar alguém para o sistema</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Gera um link de cadastro. Quem entrar por ele terá o próprio espaço, separado do
          seu — para dividir despesas, convide a pessoa para um workspace depois.
        </p>
      </div>

      <form onSubmit={enviar} className="flex flex-wrap items-end gap-3">
        <div className="min-w-[16rem] flex-1">
          <Label htmlFor="convite-site-email">E-mail (opcional)</Label>
          <Input
            id="convite-site-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="deixe vazio para gerar só o link"
          />
        </div>
        <Button type="submit" disabled={convidar.isPending}>Gerar convite</Button>
      </form>

      {isLoading && <Skeleton className="h-24 rounded-xl" />}
      {convites && convites.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-foreground">Seus convites</h3>
          {convites.map((c) => (
            <div
              key={c.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-card p-3"
            >
              <div className="text-sm">
                <span className="text-foreground">{c.email ?? 'Link aberto'}</span>
                <span className="ml-2 text-xs text-muted-foreground">
                  {c.status === 'pending' ? 'pendente' : c.status === 'accepted' ? 'usado' : 'revogado'}
                  {' · expira em '}
                  {/* `parseApiDate`: o instante vem sem fuso do backend, e o
                      `new Date()` cru o lia como hora local — o que adiantava a
                      validade em três horas e podia mostrar o dia seguinte. */}
                  {parseApiDate(c.expires_at).toLocaleDateString('pt-BR')}
                </span>
              </div>
              {c.status === 'pending' && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={async () => {
                    const ok = await copiarTexto(c.link);
                    if (ok) toast.success('Link copiado.');
                    else toast.error('Não foi possível copiar. Selecione o link manualmente.');
                  }}
                >
                  Copiar link
                </Button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Configurações da PESSOA — em `/me/settings`, sem workspace no caminho.
 *
 * Perfil, senha, contas de pagamento e tema não têm nada a ver com uma casa
 * específica, e mesmo assim só existiam dentro de `/w/:id/settings`. Quem não
 * tem workspace válido — acabou de sair do último, ou o link quebrou — não
 * alcançava a própria senha pela interface. As contas de pagamento eram o caso
 * mais estranho: pessoais desde o ADR 0021, listadas em `/me/payment-accounts`,
 * e administráveis só de dentro de um workspace.
 */
export function PersonalSettingsPage() {
  const [activeTab, setActiveTab] = React.useState<Tab>('profile');

  const renderTab = () => {
    switch (activeTab) {
      case 'profile': return <ProfileTab />;
      case 'security': return <SecurityTab />;
      case 'accounts': return <AccountsTab />;
      case 'convites': return <ConvitesDeCadastroTab />;
      case 'appearance': return <AppearanceTab />;
      default: return null;
    }
  };

  return (
    <SettingsShell
      title="Suas configurações"
      subtitle="Perfil, segurança, contas e aparência — seus, em qualquer espaço."
      menuItems={MENU_PESSOAL}
      activeTab={activeTab}
      onSelect={setActiveTab}
    >
      {renderTab()}
    </SettingsShell>
  );
}

/**
 * Configurações DO WORKSPACE — em `/w/:id/settings`.
 *
 * Só o que pertence a esta casa: nome, moeda-base, membros e permissões,
 * categorias e a trilha de auditoria. O que é da pessoa mudou-se para
 * `/me/settings`.
 */
export function SettingsPage() {
  const { isAdmin } = useWorkspaceRole();
  const [activeTab, setActiveTab] = React.useState<Tab>('members');

  const menuItems: MenuItem[] = [
    { id: 'members', label: 'Espaço e membros', icon: Users },
    { id: 'categories', label: 'Categorias', icon: Tag },
    // Auditoria é sensível (AUD-001): só admin/owner
    ...(isAdmin ? [{ id: 'audit' as Tab, label: 'Auditoria', icon: History }] : []),
  ];

  // Não-admin nunca fica preso na aba de auditoria (ex.: perdeu o papel)
  React.useEffect(() => {
    if (activeTab === 'audit' && !isAdmin) setActiveTab('members');
  }, [activeTab, isAdmin]);

  const renderTab = () => {
    switch (activeTab) {
      case 'members': return <MembersTab />;
      case 'categories': return <CategoriesTab />;
      case 'audit': return isAdmin ? <AuditTab /> : null;
      default: return null;
    }
  };

  return (
    <SettingsShell
      title="Configurações do espaço"
      subtitle="Este espaço, quem participa dele e o que cada um vê."
      menuItems={menuItems}
      activeTab={activeTab}
      onSelect={setActiveTab}
    >
      {renderTab()}
    </SettingsShell>
  );
}
