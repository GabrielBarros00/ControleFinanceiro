import * as React from 'react';
import { useNavigate, useLocation, Link, useSearchParams } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from '@/hooks/use-auth';
import { getApiErrorMessage } from '@/lib/api-error';
import { GoogleLoginButton } from '@/components/auth/GoogleLoginButton';
import { AuthShell } from '@/components/auth/AuthShell';
import { Landmark, Lock, Mail, ArrowRight, AlertCircle } from 'lucide-react';

const GOOGLE_ERRORS: Record<string, string> = {
  google_cancelado: 'Login com Google cancelado.',
  google_state_invalido: 'Sessão de login com Google expirou. Tente novamente.',
  google_falha_autenticacao: 'Não foi possível autenticar com o Google. Tente novamente.',
  google_email_nao_verificado: 'Sua conta Google não tem email verificado.',
  google_nao_configurado: 'Login com Google não está disponível no momento.',
};

const loginSchema = z.object({
  email: z.string().email('E-mail inválido'),
  password: z.string().min(6, 'A senha deve ter pelo menos 6 caracteres').max(72, 'A senha deve ter no máximo 72 caracteres'),
});

type LoginValues = z.infer<typeof loginSchema>;

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login } = useAuth();
  const [searchParams] = useSearchParams();
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(() => {
    const code = searchParams.get('error');
    return code ? (GOOGLE_ERRORS[code] ?? 'Não foi possível entrar com o Google.') : null;
  });

  const { register, handleSubmit, formState: { errors } } = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
  });

  const onSubmit = async (data: LoginValues) => {
    setLoading(true);
    setError(null);
    try {
      await login(data);
      // Volta para a rota original (ex: link de convite) se houver
      navigate((location.state as { from?: string } | null)?.from ?? '/');
    } catch (err) {
      setError(getApiErrorMessage(err, 'Email ou senha incorretos.'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthShell>
      <Card className="w-full border-border shadow-sm">
        <CardHeader className="space-y-2 text-center pt-8">
          <div className="mx-auto w-12 h-12 bg-primary rounded-xl flex items-center justify-center shadow-lg shadow-primary/20 mb-4 animate-in slide-in-from-top duration-700">
            <Landmark className="h-6 w-6 text-primary-foreground" />
          </div>
          <CardTitle className="text-3xl font-bold tracking-tight text-foreground">Bem-vindo</CardTitle>
          <CardDescription className="text-muted-foreground">
            Entre com suas credenciais para acessar o painel.
          </CardDescription>
        </CardHeader>
        <form onSubmit={handleSubmit(onSubmit)}>
          <CardContent className="space-y-4">
            {error && (
              <div className="p-3 rounded-lg bg-destructive/10 border border-destructive/20 flex items-center gap-3 text-destructive text-sm font-medium animate-in fade-in duration-300">
                <AlertCircle className="h-4 w-4" />
                {error}
              </div>
            )}

            <div className="space-y-2">
              <Label htmlFor="email">E-mail</Label>
              <div className="relative group">
                <Mail className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground group-focus-within:text-primary transition-colors" />
                <Input 
                  id="email" 
                  placeholder="exemplo@email.com" 
                  {...register('email')} 
                  className="pl-10 bg-background/50 border-border focus-visible:ring-primary/20"
                />
              </div>
              {errors.email && <p className="text-xs text-destructive font-medium mt-1">{errors.email.message}</p>}
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="password">Senha</Label>
                <Link to="/forgot-password" title="Esqueceu a senha?" className="text-xs font-medium text-primary hover:text-primary/80 hover:underline transition-all">
                  Esqueceu a senha?
                </Link>
              </div>
              <div className="relative group">
                <Lock className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground group-focus-within:text-primary transition-colors" />
                <Input 
                  id="password" 
                  type="password" 
                  placeholder="••••••••" 
                  {...register('password')} 
                  className="pl-10 bg-background/50 border-border focus-visible:ring-primary/20"
                />
              </div>
              {errors.password && <p className="text-xs text-destructive font-medium mt-1">{errors.password.message}</p>}
            </div>
          </CardContent>
          <CardFooter className="flex flex-col space-y-4 pb-8">
            <Button type="submit" className="w-full h-11 bg-primary hover:bg-primary/90 text-primary-foreground font-bold shadow-lg shadow-primary/20 transition-all active:scale-[0.98]" disabled={loading}>
              {loading ? "Autenticando..." : (
                <span className="flex items-center gap-2">
                  Acessar Conta <ArrowRight className="h-4 w-4" />
                </span>
              )}
            </Button>
            <GoogleLoginButton />
            <p className="text-center text-sm text-muted-foreground">
              Não tem uma conta? <Link to="/register" className="font-bold text-primary hover:underline ml-1">Cadastre-se</Link>
            </p>
          </CardFooter>
        </form>
      </Card>
    </AuthShell>
  );
}
