import * as React from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { useQuery } from '@tanstack/react-query';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import { apiClient } from '@/api/client';
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { AuthShell } from '@/components/auth/AuthShell';
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from '@/hooks/use-auth';
import { getApiErrorMessage } from '@/lib/api-error';
import { GoogleLoginButton } from '@/components/auth/GoogleLoginButton';
import { Lock, Mail, User, ArrowRight, ShieldCheck, AlertCircle } from 'lucide-react';

const registerSchema = z.object({
  name: z.string().min(2, 'Nome muito curto'),
  email: z.string().email('E-mail inválido'),
  password: z.string().min(6, 'A senha deve ter pelo menos 6 caracteres').max(72, 'A senha deve ter no máximo 72 caracteres'),
  confirmPassword: z.string()
}).refine((data) => data.password === data.confirmPassword, {
  message: "As senhas não coincidem",
  path: ["confirmPassword"],
});

type RegisterValues = z.infer<typeof registerSchema>;

export function RegisterPage() {
  const navigate = useNavigate();
  const { register: signup, login } = useAuth();
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  // O convite por e-mail manda o novo usuário para /register?invite=<token>.
  // O token era simplesmente IGNORADO aqui: o convite só funcionava porque o
  // backend aceitava, no cadastro, todo convite pendente para aquele e-mail —
  // ou seja, quem se cadastrasse por conta própria entrava sem consentir.
  // Agora o token viaja no POST e é o consentimento explícito.
  const [searchParams] = useSearchParams();
  const inviteToken = searchParams.get('invite') ?? undefined;

  // A política é consultada ANTES do formulário (ADR 0026). Sem isto, quem
  // chegasse a `/register` num site fechado preencheria nome, e-mail e senha
  // duas vezes para só então levar um 403 — e não teria como saber o que fazer
  // a seguir.
  const { data: politica } = useQuery({
    queryKey: ['registration-policy'],
    queryFn: async () => (await apiClient.get('/auth/registration-policy')).data as {
      mode: string;
      aceita_cadastro: boolean;
      exige_convite: boolean;
      primeiro_acesso: boolean;
    },
    // Falha de rede não pode esconder o formulário: sem resposta, mostra o
    // cadastro e deixa o servidor decidir no POST, que é a decisão que vale.
    retry: false,
  });

  // `primeiro_acesso` manda em tudo, e é a correção de um deploy que nascia
  // inutilizável: num site recém-instalado o modo é `invite_only`, ninguém tem
  // convite e não existe quem o emita, então esta tela escondia o formulário e
  // o primeiro acesso descrito no SETUP.md era impossível pelo navegador. O
  // backend sempre aceitou (a janela de bootstrap do `SUPERADMIN_EMAIL` roda
  // ANTES da checagem de modo, inclusive com o cadastro `closed`) — faltava a
  // tela deixar a pessoa digitar. Mostrar o formulário não abre nada: quem não
  // for o `SUPERADMIN_EMAIL` leva 403 no POST.
  const primeiroAcesso = politica?.primeiro_acesso === true;
  const cadastroBloqueado =
    politica != null
    && !primeiroAcesso
    && (!politica.aceita_cadastro || (politica.exige_convite && !inviteToken));

  const { register, handleSubmit, formState: { errors } } = useForm<RegisterValues>({
    resolver: zodResolver(registerSchema),
  });

  const onSubmit = async (data: RegisterValues) => {
    setLoading(true);
    setError(null);
    try {
      // 1. Create account
      await signup({
        name: data.name,
        email: data.email,
        password: data.password,
        invite_token: inviteToken,
      });
      
      // 2. Auto login
      await login({
        email: data.email,
        password: data.password
      });

      navigate('/');
    } catch (err) {
      setError(getApiErrorMessage(err, 'Erro ao criar conta. Tente novamente.'));
    } finally {
      setLoading(false);
    }
  };

  if (cadastroBloqueado) {
    const soPorConvite = politica!.exige_convite;
    return (
      <AuthShell>
        <Card className="w-full border-border shadow-sm">
          <CardHeader className="space-y-2 text-center pt-8">
            <div className="mx-auto w-12 h-12 bg-muted rounded-xl flex items-center justify-center mb-4">
              <ShieldCheck className="h-6 w-6 text-muted-foreground" />
            </div>
            <CardTitle className="text-2xl font-bold tracking-tight text-foreground">
              {soPorConvite ? 'Cadastro por convite' : 'Cadastro fechado'}
            </CardTitle>
            <CardDescription className="text-muted-foreground">
              {soPorConvite
                ? 'Este sistema é de uso restrito. Peça um convite a alguém que já o utiliza — '
                  + 'o link do convite abre esta mesma página, já liberada.'
                : 'No momento não é possível criar novas contas neste sistema.'}
            </CardDescription>
          </CardHeader>
          <CardFooter className="flex justify-center pb-8">
            <Link
              to="/login"
              className="text-sm font-medium text-primary hover:underline inline-flex items-center gap-1"
            >
              Já tenho uma conta <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </CardFooter>
        </Card>
      </AuthShell>
    );
  }

  return (
    <AuthShell>
      <Card className="w-full border-border shadow-sm">
        <CardHeader className="space-y-2 text-center pt-8">
          <div className="mx-auto w-12 h-12 bg-primary rounded-xl flex items-center justify-center shadow-lg shadow-primary/20 mb-4">
            <User className="h-6 w-6 text-primary-foreground" />
          </div>
          <CardTitle className="text-3xl font-bold tracking-tight text-foreground">
            {primeiroAcesso && !inviteToken ? 'Primeiro acesso' : 'Criar Conta'}
          </CardTitle>
          <CardDescription className="text-muted-foreground">
            {primeiroAcesso && !inviteToken
              ? 'Este sistema ainda não tem administrador.'
              : inviteToken
                ? 'Você foi convidado. Complete o cadastro abaixo.'
                : 'Comece sua jornada financeira hoje mesmo.'}
          </CardDescription>
        </CardHeader>
        {/* `noValidate`: o `type="email"` serve ao teclado do celular, não à
            validação — quem valida é o zod, que já mostra a mensagem estilizada. */}
        <form onSubmit={handleSubmit(onSubmit)} noValidate>
          <CardContent className="space-y-4">
            {/* Dizer QUAL e-mail é esperado poupa a rodada de tentativa e erro:
                sem isto a pessoa preenche o formulário com o endereço de sempre,
                leva 403 e não tem como saber que a causa é uma variável de
                ambiente que ela mesma definiu meia hora antes. */}
            {primeiroAcesso && !inviteToken && (
              <div className="p-3 rounded-lg bg-muted border border-border text-sm text-muted-foreground">
                Cadastre-se com o e-mail que você definiu em{' '}
                <code className="font-mono text-foreground">SUPERADMIN_EMAIL</code>. Essa
                conta nasce administradora do site — e é a única que entra sem convite.
              </div>
            )}
            {error && (
              <div className="p-3 rounded-lg bg-destructive/10 border border-destructive/20 flex items-center gap-3 text-destructive text-sm font-medium animate-in fade-in duration-300">
                <AlertCircle className="h-4 w-4" />
                {error}
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="name">Nome Completo</Label>
              <div className="relative group">
                <User className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground group-focus-within:text-primary transition-colors" />
                <Input
                  id="name"
                  autoComplete="name"
                  placeholder="Seu nome"
                  {...register('name')}
                  className="pl-10 bg-background/50 border-border focus-visible:ring-primary/20"
                />
              </div>
              {errors.name && <p className="text-xs text-destructive font-medium mt-1">{errors.name.message}</p>}
            </div>

            <div className="space-y-2">
              <Label htmlFor="email">E-mail</Label>
              <div className="relative group">
                <Mail className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground group-focus-within:text-primary transition-colors" />
                <Input
                  id="email"
                  type="email"
                  autoComplete="email"
                  placeholder="exemplo@email.com"
                  {...register('email')}
                  className="pl-10 bg-background/50 border-border focus-visible:ring-primary/20"
                />
              </div>
              {errors.email && <p className="text-xs text-destructive font-medium mt-1">{errors.email.message}</p>}
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="password">Senha</Label>
                <div className="relative group">
                  <Lock className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground group-focus-within:text-primary transition-colors" />
                  {/* `new-password` nos DOIS campos: sem isto o gerenciador de
                      senhas não oferece gerar uma, e o Chrome reclama no
                      console. Nunca `current-password` aqui — é cadastro. */}
                  <Input
                    id="password"
                    type="password"
                    autoComplete="new-password"
                    placeholder="••••••••"
                    {...register('password')}
                    className="pl-10 bg-background/50 border-border focus-visible:ring-primary/20"
                  />
                </div>
                {errors.password && <p className="text-xs text-destructive font-medium mt-1">{errors.password.message}</p>}
              </div>
              <div className="space-y-2">
                <Label htmlFor="confirmPassword">Confirmar</Label>
                <div className="relative group">
                  <ShieldCheck className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground group-focus-within:text-primary transition-colors" />
                  <Input
                    id="confirmPassword"
                    type="password"
                    autoComplete="new-password"
                    placeholder="••••••••"
                    {...register('confirmPassword')}
                    className="pl-10 bg-background/50 border-border focus-visible:ring-primary/20"
                  />
                </div>
                {errors.confirmPassword && <p className="text-xs text-destructive font-medium mt-1">{errors.confirmPassword.message}</p>}
              </div>
            </div>
          </CardContent>
          <CardFooter className="flex flex-col space-y-4 pb-8">
            <Button type="submit" className="w-full h-11 bg-primary hover:bg-primary/90 text-primary-foreground font-bold shadow-lg shadow-primary/20 transition-all active:scale-[0.98]" pending={loading}>
              {loading ? "Criando conta..." : (
                <span className="flex items-center gap-2">
                  Cadastrar <ArrowRight className="h-4 w-4" />
                </span>
              )}
            </Button>
            <GoogleLoginButton label="Cadastrar com Google" inviteToken={inviteToken} />
            <p className="text-center text-sm text-muted-foreground">
              Já tem uma conta? <Link to="/login" className="font-bold text-primary hover:underline ml-1">Entrar</Link>
            </p>
          </CardFooter>
        </form>
      </Card>
    </AuthShell>
  );
}
