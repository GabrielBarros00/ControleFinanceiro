import * as React from 'react';
import { Link } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { AuthShell } from '@/components/auth/AuthShell';
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Mail, ArrowLeft, Send, CheckCircle2 } from 'lucide-react';
import { apiClient } from '@/api/client';

const forgotSchema = z.object({
  email: z.string().email('E-mail inválido'),
});

type ForgotValues = z.infer<typeof forgotSchema>;

export function ForgotPasswordPage() {
  const [loading, setLoading] = React.useState(false);
  const [submitted, setSubmitted] = React.useState(false);

  const { register, handleSubmit, formState: { errors } } = useForm<ForgotValues>({
    resolver: zodResolver(forgotSchema),
  });

  const onSubmit = async (data: ForgotValues) => {
    setLoading(true);
    try {
      await apiClient.post('/auth/forgot-password', { email: data.email });
      setSubmitted(true);
    } catch (err) {
      // O backend sempre responde 200; erros aqui são de rede
      setSubmitted(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthShell>
      <Card className="w-full border-border shadow-sm">
        <CardHeader className="space-y-2 text-center pt-8">
          <div className="mx-auto w-12 h-12 bg-accent rounded-xl flex items-center justify-center shadow-lg mb-4 text-primary">
            {submitted ? <CheckCircle2 className="h-6 w-6" /> : <Mail className="h-6 w-6" />}
          </div>
          <CardTitle className="text-3xl font-bold tracking-tight text-foreground">
            {submitted ? "E-mail Enviado" : "Recuperar Senha"}
          </CardTitle>
          <CardDescription className="text-muted-foreground">
            {submitted 
              ? "Enviamos as instruções de recuperação para o seu e-mail." 
              : "Informe seu e-mail e enviaremos um link para resetar sua senha."}
          </CardDescription>
        </CardHeader>
        
        {!submitted ? (
          <form onSubmit={handleSubmit(onSubmit)}>
            <CardContent className="space-y-4">
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
            </CardContent>
            <CardFooter className="flex flex-col space-y-4 pb-8">
              <Button type="submit" className="w-full h-11 bg-primary hover:bg-primary/90 text-primary-foreground font-bold shadow-lg shadow-primary/20 transition-all" pending={loading}>
                {loading ? "Enviando..." : (
                  <span className="flex items-center gap-2">
                    Enviar Link <Send className="h-4 w-4" />
                  </span>
                )}
              </Button>
              <Link to="/login" className="flex items-center justify-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors">
                <ArrowLeft className="h-4 w-4" /> Voltar para o Login
              </Link>
            </CardFooter>
          </form>
        ) : (
          <CardContent className="pb-8 flex flex-col items-center">
            <p className="text-sm text-center text-muted-foreground mb-6">
              Não recebeu o e-mail? Verifique sua caixa de spam ou tente novamente.
            </p>
            <Button variant="outline" className="w-full" onClick={() => setSubmitted(false)}>
              Tentar outro e-mail
            </Button>
            <Link to="/login" className="mt-4 flex items-center justify-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors">
              <ArrowLeft className="h-4 w-4" /> Voltar para o Login
            </Link>
          </CardContent>
        )}
      </Card>
    </AuthShell>
  );
}
