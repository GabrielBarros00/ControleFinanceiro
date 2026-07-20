import * as React from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { User, Shield, Users, Palette, LogOut, Globe, Moon, Sun, Laptop, Loader2, Trash2, LinkIcon, Copy, Check, Tag, Plus, Wallet } from 'lucide-react';
import { useAuthStore } from '@/stores';
import { useTheme } from '@/hooks/use-theme';
import { useAuth } from '@/hooks/use-auth';
import { useWorkspaces } from '@/hooks/use-workspaces';
import { useMembers, type WorkspaceRole } from '@/hooks/use-members';
import { useCategories } from '@/hooks/use-categories';
import { usePaymentAccounts, ACCOUNT_TYPE_OPTIONS, accountTypeLabel, type PaymentAccountType } from '@/hooks/use-payment-accounts';
import { WorkspaceCreateDialog } from '@/components/workspace/WorkspaceCreateDialog';
import { apiClient } from '@/api/client';
import { getApiErrorMessage } from '@/lib/api-error';

type Tab = 'profile' | 'security' | 'members' | 'categories' | 'accounts' | 'appearance';

const ROLE_LABELS: Record<WorkspaceRole, string> = {
  owner: 'Dono',
  admin: 'Admin',
  member: 'Membro',
  viewer: 'Leitor',
};

function ProfileTab() {
  const { user, setUser } = useAuthStore();
  const { workspaces, currentWorkspaceId, switchWorkspace } = useWorkspaces();
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
      alert('Erro ao salvar o perfil');
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
          <CardTitle>Workspaces</CardTitle>
          <CardDescription>Workspaces ativos vinculados a esta conta. Clique para trocar.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {workspaces.map((ws) => (
            <button
              key={ws.id}
              type="button"
              onClick={() => switchWorkspace(ws.id)}
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
      <WorkspaceCreateDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
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
              <Input id="current-pass" type="password" placeholder="••••••••" value={currentPass} onChange={(e) => setCurrentPass(e.target.value)} className="bg-background/50 border-border" />
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="new-pass">Nova Senha</Label>
                <Input id="new-pass" type="password" placeholder="••••••••" value={newPass} onChange={(e) => setNewPass(e.target.value)} className="bg-background/50 border-border" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="confirm-pass">Confirmar Nova Senha</Label>
                <Input id="confirm-pass" type="password" placeholder="••••••••" value={confirmPass} onChange={(e) => setConfirmPass(e.target.value)} className="bg-background/50 border-border" />
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
    changeRole, removeMember, leaveWorkspace,
  } = useMembers();

  const myRole = members.find((m) => m.user_id === user?.id)?.role;
  const isAdmin = myRole === 'admin' || myRole === 'owner';
  const isOwner = myRole === 'owner';

  const [wsName, setWsName] = React.useState('');
  const [inviteEmail, setInviteEmail] = React.useState('');
  const [inviteRole, setInviteRole] = React.useState<WorkspaceRole>('member');
  const [feedback, setFeedback] = React.useState<{ ok: boolean; text: string } | null>(null);
  const [inviteLink, setInviteLink] = React.useState<string | null>(null);
  const [copied, setCopied] = React.useState(false);

  React.useEffect(() => {
    setWsName(currentWorkspace?.name ?? '');
  }, [currentWorkspace?.name]);

  const showError = (err: unknown, fallback: string) => {
    setFeedback({ ok: false, text: getApiErrorMessage(err, fallback) });
  };

  const handleInvite = async () => {
    setFeedback(null);
    try {
      const res = await inviteByEmail({ email: inviteEmail.trim(), role: inviteRole });
      setInviteEmail('');
      setFeedback({
        ok: true,
        text: res.status === 'member_added'
          ? 'Usuário adicionado ao workspace!'
          : 'Convite enviado! Será aceito quando a pessoa se registrar.',
      });
    } catch (err) {
      showError(err, 'Erro ao convidar.');
    }
  };

  const handleCreateLink = async () => {
    setFeedback(null);
    try {
      const res = await createInviteLink({ role: inviteRole, expires_days: 7 });
      setInviteLink(res.url);
    } catch (err) {
      showError(err, 'Erro ao gerar link.');
    }
  };

  const copyLink = async () => {
    if (!inviteLink) return;
    await navigator.clipboard.writeText(inviteLink);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const pendingInvites = invites.filter((i) => i.status === 'pending');

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
      {isAdmin && (
        <Card className="bg-card border-border shadow-xl">
          <CardHeader>
            <CardTitle>Workspace</CardTitle>
            <CardDescription>Nome e configurações de "{currentWorkspace?.name}".</CardDescription>
          </CardHeader>
          <CardContent className="flex gap-3">
            <Input value={wsName} onChange={(e) => setWsName(e.target.value)} className="bg-background/50 border-border" />
            <Button
              onClick={async () => {
                try {
                  await updateWorkspace({ id: currentWorkspace!.id, data: { name: wsName } });
                  setFeedback({ ok: true, text: 'Workspace renomeado!' });
                } catch (err) { showError(err, 'Erro ao renomear.'); }
              }}
              disabled={!wsName.trim() || wsName === currentWorkspace?.name}
              className="bg-primary font-bold"
            >
              Renomear
            </Button>
          </CardContent>
        </Card>
      )}

      <Card className="bg-card border-border shadow-xl">
        <CardHeader>
          <CardTitle>Membros ({members.length})</CardTitle>
          <CardDescription>Quem tem acesso a este workspace.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {members.map((m) => (
            <div key={m.user_id} className="flex items-center justify-between p-3 rounded-xl bg-accent/30 border border-border/50">
              <div className="flex items-center gap-3 min-w-0">
                <div className="w-9 h-9 rounded-full bg-primary/10 flex items-center justify-center font-bold text-primary shrink-0">
                  {m.user_name[0]}
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-bold truncate">{m.user_name} {m.user_id === user?.id && <span className="text-muted-foreground font-normal">(você)</span>}</p>
                  <p className="text-xs text-muted-foreground truncate">{m.user_email}</p>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {isAdmin && m.role !== 'owner' && m.user_id !== user?.id ? (
                  <>
                    <select
                      value={m.role}
                      onChange={async (e) => {
                        try { await changeRole({ userId: m.user_id, role: e.target.value as WorkspaceRole }); }
                        catch (err) { showError(err, 'Erro ao alterar papel.'); }
                      }}
                      className="h-8 rounded-md border border-border bg-background px-2 text-xs font-semibold text-foreground"
                    >
                      <option value="viewer">Leitor</option>
                      <option value="member">Membro</option>
                      {isOwner && <option value="admin">Admin</option>}
                    </select>
                    <Button
                      variant="ghost" size="sm"
                      onClick={async () => {
                        if (!confirm(`Remover ${m.user_name} do workspace?`)) return;
                        try { await removeMember(m.user_id); }
                        catch (err) { showError(err, 'Erro ao remover.'); }
                      }}
                      className="h-8 w-8 p-0 text-destructive hover:bg-destructive/10"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </>
                ) : (
                  <Badge variant="outline" className="border-border text-muted-foreground">{ROLE_LABELS[m.role]}</Badge>
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
              <Input
                placeholder="email@exemplo.com"
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                className="bg-background/50 border-border flex-1"
              />
              <select
                value={inviteRole}
                onChange={(e) => setInviteRole(e.target.value as WorkspaceRole)}
                className="h-10 rounded-md border border-border bg-background px-3 text-sm font-semibold text-foreground"
              >
                <option value="viewer">Leitor</option>
                <option value="member">Membro</option>
                {isOwner && <option value="admin">Admin</option>}
              </select>
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
                if (!confirm('Sair deste workspace? Você perderá o acesso.')) return;
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
                if (!confirm(`Excluir o workspace "${currentWorkspace?.name}"? Esta ação não pode ser desfeita.`)) return;
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
          <div className="flex gap-3">
            <Input
              placeholder="Nova categoria..."
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
              className="bg-background/50 border-border"
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
                    <div className="flex items-center gap-2 min-w-0">
                      <span
                        className="w-3 h-3 rounded-full shrink-0"
                        style={{ backgroundColor: cat.color ?? '#64748b' }}
                      />
                      <span className="text-sm font-bold truncate">{cat.name}</span>
                    </div>
                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                      <Button
                        variant="ghost" size="sm"
                        className="h-7 text-xs"
                        onClick={() => { setEditingId(cat.id); setEditName(cat.name); }}
                      >
                        Renomear
                      </Button>
                      <Button
                        variant="ghost" size="sm"
                        className="h-7 w-7 p-0 text-destructive hover:bg-destructive/10"
                        onClick={async () => {
                          if (!confirm(`Excluir a categoria "${cat.name}"?`)) return;
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
          <div className="flex gap-3">
            <Input
              placeholder="Nova conta... (ex: Nubank)"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
              className="bg-background/50 border-border"
            />
            <select
              aria-label="Tipo da conta"
              value={newType}
              onChange={(e) => setNewType(e.target.value as PaymentAccountType)}
              className="h-10 rounded-md border border-border bg-background px-3 text-sm text-foreground"
            >
              {ACCOUNT_TYPE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value} className="bg-card">{o.label}</option>
              ))}
            </select>
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
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
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
                    className="h-7 w-7 p-0 text-destructive hover:bg-destructive/10"
                    onClick={async () => {
                      if (!confirm(`Excluir a conta "${account.name}"? Pagamentos antigos preservam o histórico.`)) return;
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
    </div>
  );
}

export function SettingsPage() {
  const { logout } = useAuth();
  const [activeTab, setActiveTab] = React.useState<Tab>('profile');

  const menuItems = [
    { id: 'profile', label: 'Perfil', icon: User },
    { id: 'security', label: 'Segurança', icon: Shield },
    { id: 'members', label: 'Membros', icon: Users },
    { id: 'categories', label: 'Categorias', icon: Tag },
    { id: 'accounts', label: 'Contas', icon: Wallet },
    { id: 'appearance', label: 'Aparência', icon: Palette },
  ];

  const renderTab = () => {
    switch (activeTab) {
      case 'profile': return <ProfileTab />;
      case 'security': return <SecurityTab />;
      case 'members': return <MembersTab />;
      case 'categories': return <CategoriesTab />;
      case 'accounts': return <AccountsTab />;
      case 'appearance': return <AppearanceTab />;
      default: return null;
    }
  };

  return (
    <div className="space-y-8 animate-in slide-in-from-bottom-4 duration-700 pb-20">
      <div className="grid gap-6 md:grid-cols-[240px_1fr]">
        <aside className="space-y-2">
          {menuItems.map((item) => (
            <Button
              key={item.id}
              variant="ghost"
              className={`w-full justify-start gap-3 transition-all ${
                activeTab === item.id
                  ? 'bg-primary text-primary-foreground font-bold shadow-lg shadow-primary/20'
                  : 'text-muted-foreground hover:text-foreground hover:bg-accent'
              }`}
              onClick={() => setActiveTab(item.id as Tab)}
            >
              <item.icon className={`h-4 w-4 ${activeTab === item.id ? 'text-primary-foreground' : ''}`} />
              {item.label}
            </Button>
          ))}
          <div className="pt-4 border-t border-border mt-4">
            <Button variant="ghost" className="w-full justify-start gap-3 text-destructive hover:bg-destructive/10 transition-colors" onClick={() => logout()}>
              <LogOut className="h-4 w-4" /> Sair da Conta
            </Button>
          </div>
        </aside>

        <main className="min-h-[500px]">
          {renderTab()}
        </main>
      </div>
    </div>
  );
}
