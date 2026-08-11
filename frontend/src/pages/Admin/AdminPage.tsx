import * as React from 'react';
import {
  Activity, HardDrive, Mail, ShieldAlert, Ticket, Users,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { ErrorState } from '@/components/ui/error-state';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useConfirm } from '@/components/ui/confirm';
import { toast } from '@/stores/toast';
import { getApiErrorMessage } from '@/lib/api-error';
import { copiarTexto } from '@/lib/clipboard';
import { useAuthStore, type PlatformRole } from '@/stores';
import {
  useAdminAudit, useAdminOverview, useAdminSaude, useAdminSettings, useAdminUsers,
  useIsSuperadmin, useRegistrationInvites,
  type AdminUser,
} from '@/hooks/use-admin';
import { bytes, data, dia } from './formatters';

/**
 * Área de administração do SITE (ADR 0026).
 *
 * O que esta tela mostra é metadado: quantas pessoas, quanto espaço, quando
 * entraram, que papel têm. Nenhum número aqui é dinheiro de ninguém — o
 * administrador opera o servidor, e a vida financeira de cada um continua sendo
 * dela (ADRs 0018 e 0021). Se um dia aparecer "total gasto" nesta tela, o
 * teste `test_admin_sem_vazamento_financeiro.py` reprova antes do merge.
 */

/**
 * Métrica simples. Não usa o `StatTile` da casa de propósito: aquele passa o
 * valor pelo `MoneyText`, que formata como moeda — "R$ 3,00 usuários".
 */
function Metrica({
  label, valor, hint, icon: Icon,
}: {
  label: string;
  valor: React.ReactNode;
  hint?: React.ReactNode;
  icon?: React.ComponentType<{ className?: string }>;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">{label}</p>
        {Icon && <Icon className="h-4 w-4 text-muted-foreground/70" />}
      </div>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-foreground">{valor}</p>
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

const ROTULO_DE_PAPEL: Record<PlatformRole, string> = {
  user: 'Usuário',
  admin: 'Administrador',
  superadmin: 'Superadministrador',
};

// --------------------------------------------------------------------------
// Visão geral
// --------------------------------------------------------------------------

function VisaoGeral() {
  const { data: dados, isLoading, isError, refetch } = useAdminOverview();

  if (isLoading) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-xl" />)}
      </div>
    );
  }
  if (isError || !dados) {
    return <ErrorState title="Não foi possível carregar os números" onRetry={() => refetch()} />;
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <Metrica
        label="Pessoas" valor={dados.usuarios_total} icon={Users}
        hint={`${dados.usuarios_ativos} ativas · ${dados.usuarios_novos_30d} novas em 30 dias`}
      />
      <Metrica label="Workspaces" valor={dados.workspaces} />
      <Metrica label="Lançamentos" valor={dados.lancamentos} />
      <Metrica label="Sessões abertas" valor={dados.sessoes_vivas} icon={Activity} />
      <Metrica
        label="Anexos" valor={bytes(dados.anexos_bytes)} icon={HardDrive}
        hint={`${dados.anexos_qtd} arquivo(s)`}
      />
      <Metrica label="Banco de dados" valor={bytes(dados.banco_bytes)} icon={HardDrive} />
      <Metrica label="Convites pendentes" valor={dados.convites_pendentes} icon={Ticket} />
    </div>
  );
}

// --------------------------------------------------------------------------
// Usuários
// --------------------------------------------------------------------------

function LinhaDeUsuario({
  usuario, souSuperadmin, meuId, acoes,
}: {
  usuario: AdminUser;
  souSuperadmin: boolean;
  meuId: number | undefined;
  acoes: ReturnType<typeof useAdminUsers>;
}) {
  const confirm = useConfirm();
  // Um admin não mexe em superadmin. O servidor recusa de qualquer forma (403);
  // desabilitar aqui evita oferecer um botão que só produz erro.
  const podeMexer = souSuperadmin || usuario.platform_role !== 'superadmin';
  const souEu = usuario.id === meuId;

  const trocarPapel = async (papel: PlatformRole) => {
    try {
      await acoes.patch.mutateAsync({ userId: usuario.id, platform_role: papel });
      toast.success(`${usuario.name} agora é ${ROTULO_DE_PAPEL[papel].toLowerCase()}.`);
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  };

  const alternarAtivo = async () => {
    const desativando = usuario.is_active;
    if (desativando) {
      const ok = await confirm({
        title: `Desativar ${usuario.name}?`,
        description:
          'A pessoa perde o acesso imediatamente e todas as sessões abertas são derrubadas. '
          + 'Os dados dela continuam no sistema e voltam se você reativar.',
        confirmLabel: 'Desativar',
        destructive: true,
      });
      if (!ok) return;
    }
    try {
      await acoes.patch.mutateAsync({ userId: usuario.id, is_active: !usuario.is_active });
      toast.success(desativando ? 'Conta desativada.' : 'Conta reativada.');
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  };

  const derrubarSessoes = async () => {
    const ok = await confirm({
      title: `Derrubar as sessões de ${usuario.name}?`,
      description: 'A pessoa precisará entrar de novo em todos os dispositivos.',
      confirmLabel: 'Derrubar',
    });
    if (!ok) return;
    try {
      const r = await acoes.revogarSessoes.mutateAsync(usuario.id);
      toast.success(`${r.revogadas} sessão(ões) derrubada(s).`);
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  };

  return (
    <TableRow className={usuario.is_active ? undefined : 'opacity-60'}>
      <TableCell>
        <div className="font-medium text-foreground">{usuario.name}</div>
        <div className="text-xs text-muted-foreground">{usuario.email}</div>
      </TableCell>
      <TableCell>
        {podeMexer && !souEu ? (
          // `<select>` nativo: o Select do Base UI é usado no resto do app, mas
          // aqui a tabela pode viver dentro de um Dialog e o popup dele escapa do
          // focus-trap do Radix.
          //
          // A condição é `podeMexer`, não `souSuperadmin`: um admin comum PODE
          // promover alguém a administrador — o servidor aceita — e a tela
          // simplesmente não oferecia, deixando a função só alcançável por quem
          // chamasse a API na mão. O que ele não pode é criar um superadmin, e
          // é isso que a opção condicional abaixo reflete (o servidor recusa com
          // 403 de qualquer forma).
          <select
            className="h-8 rounded-md border border-input bg-background px-2 text-sm"
            value={usuario.platform_role}
            disabled={acoes.patch.isPending}
            onChange={(e) => trocarPapel(e.target.value as PlatformRole)}
            aria-label={`Papel de ${usuario.name}`}
          >
            <option value="user">Usuário</option>
            <option value="admin">Administrador</option>
            {souSuperadmin && <option value="superadmin">Superadministrador</option>}
          </select>
        ) : (
          <Badge variant={usuario.platform_role === 'user' ? 'secondary' : 'default'}>
            {ROTULO_DE_PAPEL[usuario.platform_role]}
          </Badge>
        )}
      </TableCell>
      <TableCell className="text-sm tabular-nums">{usuario.workspaces}</TableCell>
      <TableCell className="text-sm tabular-nums">{usuario.lancamentos}</TableCell>
      <TableCell className="text-sm tabular-nums">{bytes(usuario.anexos_bytes)}</TableCell>
      <TableCell className="text-sm text-muted-foreground">{data(usuario.last_login_at)}</TableCell>
      <TableCell>
        <div className="flex flex-wrap items-center gap-2">
          {/* `souEu`: desativar a própria conta derruba a sessão e o login
              seguinte é recusado — a volta dependeria de outro administrador. O
              servidor recusa com 409; aqui o botão nem se oferece. */}
          <Switch
            checked={usuario.is_active}
            disabled={!podeMexer || souEu || acoes.patch.isPending}
            onCheckedChange={alternarAtivo}
            aria-label={`${usuario.is_active ? 'Desativar' : 'Reativar'} ${usuario.name}`}
          />
          <Button
            variant="ghost" size="sm"
            disabled={!podeMexer || acoes.revogarSessoes.isPending}
            onClick={derrubarSessoes}
          >
            Sair de tudo
          </Button>
        </div>
      </TableCell>
    </TableRow>
  );
}

function Usuarios() {
  const [busca, setBusca] = React.useState('');
  const [buscaAplicada, setBuscaAplicada] = React.useState('');
  const acoes = useAdminUsers({ busca: buscaAplicada });
  const souSuperadmin = useIsSuperadmin();
  const meuId = useAuthStore((s) => s.user?.id);

  // Busca só ao submeter: a cada tecla seria uma consulta com JOIN e três
  // agregações por página.
  const submeter = (e: React.FormEvent) => {
    e.preventDefault();
    setBuscaAplicada(busca);
  };

  return (
    <div className="space-y-4">
      <form onSubmit={submeter} className="flex gap-2">
        <Input
          value={busca}
          onChange={(e) => setBusca(e.target.value)}
          placeholder="Buscar por nome ou e-mail"
          className="max-w-sm"
          aria-label="Buscar pessoa"
        />
        <Button type="submit" variant="secondary">Buscar</Button>
      </form>

      {acoes.isLoading && <Skeleton className="h-64 rounded-xl" />}
      {acoes.isError && (
        <ErrorState title="Não foi possível carregar as pessoas" onRetry={() => acoes.refetch()} />
      )}
      {acoes.data && acoes.data.items.length === 0 && (
        <EmptyState title="Ninguém encontrado" description="Nenhuma pessoa corresponde à busca." />
      )}
      {acoes.data && acoes.data.items.length > 0 && (
        <Card className="overflow-x-auto p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Pessoa</TableHead>
                <TableHead>Papel no site</TableHead>
                <TableHead>Workspaces</TableHead>
                <TableHead>Lançamentos</TableHead>
                <TableHead>Anexos</TableHead>
                <TableHead>Último acesso</TableHead>
                <TableHead>Ações</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {acoes.data.items.map((u) => (
                <LinhaDeUsuario
                  key={u.id} usuario={u} souSuperadmin={souSuperadmin} meuId={meuId} acoes={acoes}
                />
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
      {acoes.data && (
        <p className="text-xs text-muted-foreground">
          {acoes.data.total} pessoa(s) no total.
        </p>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
// Convites de cadastro
// --------------------------------------------------------------------------

function Convites() {
  const { data: convites, isLoading, criar, revogar } = useRegistrationInvites();
  const [email, setEmail] = React.useState('');
  const confirm = useConfirm();

  const gerar = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const convite = await criar.mutateAsync({ email: email.trim() || undefined });
      setEmail('');
      // A mensagem depende de a cópia ter funcionado: num deploy sem HTTPS a
      // área de transferência não existe, e prometer um link que não está lá
      // faria a pessoa colar outra coisa em cima do convite.
      const copiou = await copiarTexto(convite.link);
      toast.success(
        convite.email
          ? `Convite enviado para ${convite.email}.${copiou ? ' O link foi copiado.' : ''}`
          : copiou
            ? 'Convite criado e link copiado para a área de transferência.'
            : 'Convite criado. Use "Copiar link" na lista abaixo.',
      );
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  };

  const revogarConvite = async (id: number) => {
    const ok = await confirm({
      title: 'Revogar este convite?',
      description: 'O link para de funcionar imediatamente.',
      confirmLabel: 'Revogar',
      destructive: true,
    });
    if (!ok) return;
    try {
      await revogar.mutateAsync(id);
      toast.success('Convite revogado.');
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  };

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <form onSubmit={gerar} className="flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[16rem]">
            <Label htmlFor="convite-email">E-mail (opcional)</Label>
            <Input
              id="convite-email" type="email" value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="deixe vazio para gerar um link aberto"
            />
            <p className="mt-1 text-xs text-muted-foreground">
              Com e-mail, o convite vale só para aquele endereço e é enviado por e-mail.
              Sem e-mail, vira um link que qualquer pessoa pode usar uma vez.
            </p>
          </div>
          <Button type="submit" disabled={criar.isPending}>Gerar convite</Button>
        </form>
      </Card>

      {isLoading && <Skeleton className="h-40 rounded-xl" />}
      {convites && convites.length === 0 && (
        <EmptyState
          title="Nenhum convite ainda"
          description="Gere um convite acima para permitir que alguém crie uma conta."
        />
      )}
      {convites && convites.length > 0 && (
        <Card className="overflow-x-auto p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Para</TableHead>
                <TableHead>Situação</TableHead>
                <TableHead>Usos</TableHead>
                <TableHead>Expira</TableHead>
                <TableHead>Ações</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {convites.map((c) => (
                <TableRow key={c.id}>
                  <TableCell className="text-sm">{c.email ?? 'Link aberto'}</TableCell>
                  <TableCell>
                    <Badge variant={c.status === 'pending' ? 'default' : 'secondary'}>
                      {c.status === 'pending' ? 'Pendente'
                        : c.status === 'accepted' ? 'Usado' : 'Revogado'}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-sm tabular-nums">
                    {c.uses}{c.max_uses ? ` / ${c.max_uses}` : ''}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">{data(c.expires_at)}</TableCell>
                  <TableCell>
                    <div className="flex gap-2">
                      <Button
                        variant="ghost" size="sm"
                        onClick={async () => {
                          const ok = await copiarTexto(c.link);
                          if (ok) toast.success('Link copiado.');
                          else toast.error('Não foi possível copiar. Selecione o link manualmente.');
                        }}
                      >
                        Copiar link
                      </Button>
                      {c.status === 'pending' && (
                        <Button variant="ghost" size="sm" onClick={() => revogarConvite(c.id)}>
                          Revogar
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
// Configurações
// --------------------------------------------------------------------------

const ROTULOS_DE_CADASTRO: Record<string, string> = {
  open: 'Aberto — qualquer pessoa cria conta',
  invite_only: 'Somente por convite (recomendado)',
  closed: 'Fechado — ninguém cria conta',
};

function Configuracoes() {
  const { data: dados, isLoading, salvar, testarEmail } = useAdminSettings();
  const [rascunho, setRascunho] = React.useState<Record<string, unknown>>({});
  const [emailTeste, setEmailTeste] = React.useState('');

  const valor = (chave: string) => rascunho[chave] ?? dados?.valores[chave];
  const mudar = (chave: string, v: unknown) => setRascunho((r) => ({ ...r, [chave]: v }));
  const sujo = Object.keys(rascunho).length > 0;

  const gravar = async () => {
    try {
      await salvar.mutateAsync(rascunho);
      setRascunho({});
      toast.success('Configuração salva.');
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  };

  const enviarTeste = async () => {
    try {
      const r = await testarEmail.mutateAsync(emailTeste);
      if (r.enviado) toast.success('E-mail enviado. Confira a caixa de entrada.');
      else if (!r.configurado) toast.warning(r.detalhe ?? 'SMTP não configurado.');
      else toast.error(`Falhou: ${r.detalhe}`);
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  };

  if (isLoading || !dados) return <Skeleton className="h-96 rounded-xl" />;

  const porNome = Object.fromEntries(dados.chaves.map((c) => [c.nome, c]));
  const doAmbiente = (chave: string) =>
    !porNome[chave]?.sobrescrito && porNome[chave]?.origem_ambiente
      ? `Acompanha ${porNome[chave].origem_ambiente} do .env`
      : undefined;

  return (
    <div className="space-y-4">
      <Card className="space-y-4 p-4">
        <h3 className="font-medium text-foreground">Cadastro</h3>

        <div>
          <Label htmlFor="cfg-registro">Quem pode criar conta</Label>
          <select
            id="cfg-registro"
            className="mt-1 h-9 w-full max-w-md rounded-md border border-input bg-background px-2 text-sm"
            value={String(valor('registration_mode'))}
            onChange={(e) => mudar('registration_mode', e.target.value)}
          >
            {Object.entries(ROTULOS_DE_CADASTRO).map(([v, rotulo]) => (
              <option key={v} value={v}>{rotulo}</option>
            ))}
          </select>
        </div>

        <div>
          <Label htmlFor="cfg-quem-convida">Quem pode convidar</Label>
          <select
            id="cfg-quem-convida"
            className="mt-1 h-9 w-full max-w-md rounded-md border border-input bg-background px-2 text-sm"
            value={String(valor('who_can_invite'))}
            onChange={(e) => mudar('who_can_invite', e.target.value)}
          >
            <option value="all_users">Qualquer pessoa já cadastrada</option>
            <option value="admins_only">Somente administradores</option>
          </select>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <Label htmlFor="cfg-expira">Validade do convite (dias)</Label>
            <Input
              id="cfg-expira" type="number" min={1} max={365}
              value={String(valor('invite_expiry_days') ?? '')}
              onChange={(e) => mudar('invite_expiry_days', Number(e.target.value))}
            />
          </div>
          <div>
            <Label htmlFor="cfg-cota">Convites por pessoa, por mês</Label>
            <Input
              id="cfg-cota" type="number" min={1} max={1000}
              value={String(valor('user_invite_quota_per_month') ?? '')}
              onChange={(e) => mudar('user_invite_quota_per_month', Number(e.target.value))}
            />
            <p className="mt-1 text-xs text-muted-foreground">
              Não vale para administradores.
            </p>
          </div>
        </div>
      </Card>

      <Card className="space-y-4 p-4">
        <h3 className="font-medium text-foreground">Limites</h3>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <Label htmlFor="cfg-quota">Anexos por workspace (MB)</Label>
            <Input
              id="cfg-quota" type="number" min={1}
              value={String(Math.round(Number(valor('attachment_quota_bytes') ?? 0) / 1048576))}
              onChange={(e) => mudar('attachment_quota_bytes', Number(e.target.value) * 1048576)}
            />
            <p className="mt-1 text-xs text-muted-foreground">{doAmbiente('attachment_quota_bytes')}</p>
          </div>
          <div>
            <Label htmlFor="cfg-upload">Tamanho máximo por arquivo (MB)</Label>
            <Input
              id="cfg-upload" type="number" min={1}
              max={Math.floor(dados.limite_nginx_bytes / 1048576)}
              value={String(Math.round(Number(valor('upload_max_bytes') ?? 0) / 1048576))}
              onChange={(e) => mudar('upload_max_bytes', Number(e.target.value) * 1048576)}
            />
            {/* O teto não é preferência: é o `client_max_body_size` do nginx, que
                fica NA FRENTE do backend. Um valor maior aqui não liberaria nada
                — o nginx corta com 413 antes de o app ver o arquivo. */}
            <p className="mt-1 text-xs text-muted-foreground">
              Máximo de {Math.floor(dados.limite_nginx_bytes / 1048576)} MB — acima disso o
              servidor web recusa antes de o aplicativo receber o arquivo.
            </p>
          </div>
          <div>
            <Label htmlFor="cfg-linhas">Linhas por importação</Label>
            <Input
              id="cfg-linhas" type="number" min={1}
              value={String(valor('import_max_rows') ?? '')}
              onChange={(e) => mudar('import_max_rows', Number(e.target.value))}
            />
            <p className="mt-1 text-xs text-muted-foreground">{doAmbiente('import_max_rows')}</p>
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <Label htmlFor="cfg-rl-ip">Tentativas de login por minuto (por IP)</Label>
            <Input
              id="cfg-rl-ip" type="number" min={1}
              value={String(valor('rate_limit_auth_per_minute') ?? '')}
              onChange={(e) => mudar('rate_limit_auth_per_minute', Number(e.target.value))}
            />
            <p className="mt-1 text-xs text-muted-foreground">
              Um IP é compartilhado por todo mundo atrás do mesmo Wi-Fi — apertar demais
              tranca gente legítima sem impedir ataque.
            </p>
          </div>
          <div>
            <Label htmlFor="cfg-rl-conta">Tentativas por minuto (por conta)</Label>
            <Input
              id="cfg-rl-conta" type="number" min={1}
              value={String(valor('rate_limit_account_per_minute') ?? '')}
              onChange={(e) => mudar('rate_limit_account_per_minute', Number(e.target.value))}
            />
            <p className="mt-1 text-xs text-muted-foreground">
              É este que barra força bruta num alvo. Deve continuar sendo o menor dos dois.
            </p>
          </div>
        </div>
      </Card>

      <Card className="space-y-3 p-4">
        <h3 className="flex items-center gap-2 font-medium text-foreground">
          <ShieldAlert className="h-4 w-4" /> Manutenção
        </h3>
        <div className="flex items-center gap-3">
          <Switch
            checked={Boolean(valor('maintenance_mode'))}
            onCheckedChange={(v) => mudar('maintenance_mode', v)}
            aria-label="Modo manutenção"
          />
          <span className="text-sm text-muted-foreground">
            Com o modo ligado, só administradores usam o sistema. Você continua entrando
            por esta tela para desligar.
          </span>
        </div>
      </Card>

      <Card className="space-y-3 p-4">
        <h3 className="flex items-center gap-2 font-medium text-foreground">
          <Mail className="h-4 w-4" /> Testar envio de e-mail
        </h3>
        <p className="text-sm text-muted-foreground">
          As credenciais de SMTP ficam no <code>.env</code> por segurança. Aqui você
          confere se o envio funciona — sem isso, a única pista seria o log do servidor.
        </p>
        <div className="flex flex-wrap items-end gap-2">
          <Input
            type="email" value={emailTeste} onChange={(e) => setEmailTeste(e.target.value)}
            placeholder="seu@email.com" className="max-w-xs" aria-label="E-mail de teste"
          />
          <Button
            variant="secondary" onClick={enviarTeste}
            disabled={!emailTeste || testarEmail.isPending}
          >
            Enviar teste
          </Button>
        </div>
      </Card>

      {sujo && (
        <div className="sticky bottom-4 flex items-center justify-between gap-4 rounded-xl border border-border bg-card p-3 shadow-lg">
          <span className="text-sm text-muted-foreground">Há alterações não salvas.</span>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => setRascunho({})}>Descartar</Button>
            <Button onClick={gravar} disabled={salvar.isPending}>Salvar</Button>
          </div>
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
// Saúde
// --------------------------------------------------------------------------

function Saude() {
  const { data: dados, isLoading } = useAdminSaude();
  if (isLoading || !dados) return <Skeleton className="h-48 rounded-xl" />;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Metrica
          label="Última cotação de câmbio" valor={dia(dados.cambio_ultima_data)}
          hint={`${dados.cambio_cotacoes} cotação(ões) guardadas`}
        />
        <Metrica label="Banco de dados" valor={bytes(dados.banco_bytes)} icon={HardDrive} />
        <Metrica label="Anexos" valor={bytes(dados.anexos_bytes)} icon={HardDrive} />
        <Metrica
          label="Linhas de auditoria" valor={dados.auditoria_linhas}
          hint={`desde ${data(dados.auditoria_mais_antiga)}`}
        />
      </div>
      <Card className="p-4 text-sm text-muted-foreground">
        <p>
          A cotação é atualizada de hora em hora pelo serviço <code>cron</code>. Se a data
          acima estiver muito atrasada, esse serviço parou — e recorrências em moeda
          estrangeira deixam de nascer sem emitir erro nenhum.
        </p>
        <p className="mt-2">
          {dados.sessoes_expiradas_pendentes_de_expurgo} sessão(ões) expirada(s) aguardando
          o expurgo diário.
        </p>
      </Card>
    </div>
  );
}

// --------------------------------------------------------------------------
// Auditoria
// --------------------------------------------------------------------------

function Auditoria() {
  const { data: linhas, isLoading } = useAdminAudit();
  if (isLoading) return <Skeleton className="h-64 rounded-xl" />;
  if (!linhas || linhas.length === 0) {
    return <EmptyState title="Nada registrado ainda" description="As ações aparecerão aqui." />;
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Quem fez o quê, e em qual recurso. O conteúdo do que mudou não aparece aqui —
        num lançamento isso incluiria o valor, e a trilha administrativa não é uma porta
        para os dados de ninguém.
      </p>
      <Card className="overflow-x-auto p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Quando</TableHead>
              <TableHead>Ação</TableHead>
              <TableHead>Recurso</TableHead>
              <TableHead>Pessoa</TableHead>
              <TableHead>Origem</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {linhas.map((l) => (
              <TableRow key={l.id}>
                <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                  {data(l.created_at)}
                </TableCell>
                <TableCell className="text-sm">{l.action}</TableCell>
                <TableCell className="text-sm">
                  {l.resource_type ?? '—'}{l.resource_id ? ` #${l.resource_id}` : ''}
                </TableCell>
                <TableCell className="text-sm tabular-nums">{l.user_id ?? '—'}</TableCell>
                <TableCell className="text-sm text-muted-foreground">{l.ip_address ?? '—'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}

// --------------------------------------------------------------------------

export function AdminPage() {
  return (
    <Tabs defaultValue="visao" className="space-y-4">
      <TabsList>
        <TabsTrigger value="visao">Visão geral</TabsTrigger>
        <TabsTrigger value="usuarios">Pessoas</TabsTrigger>
        <TabsTrigger value="convites">Convites</TabsTrigger>
        <TabsTrigger value="config">Configurações</TabsTrigger>
        <TabsTrigger value="saude">Saúde</TabsTrigger>
        <TabsTrigger value="auditoria">Auditoria</TabsTrigger>
      </TabsList>

      <TabsContent value="visao"><VisaoGeral /></TabsContent>
      <TabsContent value="usuarios"><Usuarios /></TabsContent>
      <TabsContent value="convites"><Convites /></TabsContent>
      <TabsContent value="config"><Configuracoes /></TabsContent>
      <TabsContent value="saude"><Saude /></TabsContent>
      <TabsContent value="auditoria"><Auditoria /></TabsContent>
    </Tabs>
  );
}

export default AdminPage;
