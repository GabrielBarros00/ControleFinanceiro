import * as React from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
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

  return (
    <AuthShell>
      <Card className="w-full border-border shadow-sm">
        <CardHeader className="space-y-2 text-center pt-8">
          <div className="mx-auto w-12 h-12 bg-primary rounded-xl flex items-center justify-center shadow-lg shadow-primary/20 mb-4">
            <User className="h-6 w-6 text-primary-foreground" />
          </div>
          <CardTitle className="text-3xl font-bold tracking-tight text-foreground">Criar Conta</CardTitle>
          <CardDescription className="text-muted-foreground">
            Comece sua jornada financeira hoje mesmo.
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
              <Label htmlFor="name">Nome Completo</Label>
              <div className="relative group">
                <User className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground group-focus-within:text-primary transition-colors" />
                <Input 
                  id="name" 
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
              <div className="space-y-2">
                <Label htmlFor="confirmPassword">Confirmar</Label>
                <div className="relative group">
                  <ShieldCheck className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground group-focus-within:text-primary transition-colors" />
                  <Input 
                    id="confirmPassword" 
                    type="password" 
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
            <Button type="submit" className="w-full h-11 bg-primary hover:bg-primary/90 text-primary-foreground font-bold shadow-lg shadow-primary/20 transition-all active:scale-[0.98]" disabled={loading}>
              {loading ? "Criando conta..." : (
                <span className="flex items-center gap-2">
                  Cadastrar <ArrowRight className="h-4 w-4" />
                </span>
              )}
            </Button>
            <GoogleLoginButton label="Cadastrar com Google" />
            <p className="text-center text-sm text-muted-foreground">
              Já tem uma conta? <Link to="/login" className="font-bold text-primary hover:underline ml-1">Entrar</Link>
            </p>
          </CardFooter>
        </form>
      </Card>
    </AuthShell>
  );
}
