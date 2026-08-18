import * as React from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { AuthShell } from '@/components/auth/AuthShell';
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Lock, ArrowLeft, KeyRound, CheckCircle2, AlertCircle } from 'lucide-react';
import { apiClient } from '@/api/client';
import { getApiErrorMessage } from '@/lib/api-error';

const resetSchema = z.object({
  password: z.string().min(6, 'A senha deve ter pelo menos 6 caracteres').max(72, 'A senha deve ter no máximo 72 caracteres'),
  confirm: z.string(),
}).refine((data) => data.password === data.confirm, {
  message: 'As senhas não coincidem',
  path: ['confirm'],
});

type ResetValues = z.infer<typeof resetSchema>;

export function ResetPasswordPage() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token');
  const [loading, setLoading] = React.useState(false);
  const [done, setDone] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const { register, handleSubmit, formState: { errors } } = useForm<ResetValues>({
    resolver: zodResolver(resetSchema),
  });

  const onSubmit = async (data: ResetValues) => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      await apiClient.post('/auth/reset-password', { token, new_password: data.password });
      setDone(true);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Link de recuperação inválido ou expirado'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthShell>
      <Card className="w-full border-border shadow-sm">
        <CardHeader className="space-y-2 text-center pt-8">
          <div className="mx-auto w-12 h-12 bg-accent rounded-xl flex items-center justify-center shadow-lg mb-4 text-primary">
            {done ? <CheckCircle2 className="h-6 w-6" /> : <KeyRound className="h-6 w-6" />}
          </div>
          <CardTitle className="text-3xl font-bold tracking-tight text-foreground">
            {done ? "Senha Redefinida" : "Nova Senha"}
          </CardTitle>
          <CardDescription className="text-muted-foreground">
            {done
              ? "Sua senha foi alterada com sucesso. Faça login com a nova senha."
              : "Escolha uma nova senha para a sua conta."}
          </CardDescription>
        </CardHeader>

        {!token ? (
          <CardContent className="pb-8 space-y-6">
            <div className="p-3 rounded-lg bg-destructive/10 border border-destructive/20 flex items-center gap-3 text-destructive text-sm font-medium">
              <AlertCircle className="h-4 w-4" />
              Link de recuperação inválido. Solicite um novo link.
            </div>
            <Link to="/forgot-password" className="flex items-center justify-center gap-2 text-sm font-medium text-primary hover:underline">
              Solicitar novo link
            </Link>
          </CardContent>
        ) : done ? (
          <CardContent className="pb-8 flex flex-col items-center">
            <Link to="/login" className="w-full">
              <Button type="button" className="w-full h-11 bg-primary hover:bg-primary/90 text-primary-foreground font-bold">
                Ir para o Login
              </Button>
            </Link>
          </CardContent>
        ) : (
          <form onSubmit={handleSubmit(onSubmit)}>
            <CardContent className="space-y-4">
              {error && (
                <div className="p-3 rounded-lg bg-destructive/10 border border-destructive/20 flex items-center gap-3 text-destructive text-sm font-medium animate-in fade-in duration-300">
                  <AlertCircle className="h-4 w-4" />
                  {error}
                </div>
              )}
              <div className="space-y-2">
                <Label htmlFor="password">Nova senha</Label>
                <div className="relative group">
                  <Lock className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground group-focus-within:text-primary transition-colors" />
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
                <Label htmlFor="confirm">Confirmar nova senha</Label>
                <div className="relative group">
                  <Lock className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground group-focus-within:text-primary transition-colors" />
                  <Input
                    id="confirm"
                    type="password"
                    autoComplete="new-password"
                    placeholder="••••••••"
                    {...register('confirm')}
                    className="pl-10 bg-background/50 border-border focus-visible:ring-primary/20"
                  />
                </div>
                {errors.confirm && <p className="text-xs text-destructive font-medium mt-1">{errors.confirm.message}</p>}
              </div>
            </CardContent>
            <CardFooter className="flex flex-col space-y-4 pb-8">
              <Button type="submit" className="w-full h-11 bg-primary hover:bg-primary/90 text-primary-foreground font-bold shadow-lg shadow-primary/20 transition-all" pending={loading}>
                {loading ? "Salvando..." : "Redefinir Senha"}
              </Button>
              <Link to="/login" className="flex items-center justify-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors">
                <ArrowLeft className="h-4 w-4" /> Voltar para o Login
              </Link>
            </CardFooter>
          </form>
        )}
      </Card>
    </AuthShell>
  );
}
