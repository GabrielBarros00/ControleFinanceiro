import { Button } from "@/components/ui/button";
import { baseURL } from '@/api/client';

/**
 * `inviteToken` viaja até o backend, que o guarda ASSINADO dentro do `state` do
 * OAuth e o lê de volta no callback (ADR 0026). O Google não devolve query
 * string nossa, então sem este caminho o token se perderia no salto — e quem
 * fosse convidado para um site em `invite_only` seria recusado justamente no
 * botão que a tela de cadastro oferece ao lado do formulário que funciona.
 */
export function GoogleLoginButton({
  label = "Entrar com Google",
  inviteToken,
}: { label?: string; inviteToken?: string }) {
  const destino = inviteToken
    ? `${baseURL}/auth/google/login?invite=${encodeURIComponent(inviteToken)}`
    : `${baseURL}/auth/google/login`;
  return (
    <div className="w-full space-y-4">
      <div className="relative flex items-center">
        <div className="grow border-t border-border" />
        <span className="mx-3 text-[10px] uppercase tracking-widest text-muted-foreground font-bold">ou</span>
        <div className="grow border-t border-border" />
      </div>
      <Button
        type="button"
        variant="outline"
        className="w-full h-11 font-bold gap-2 bg-background/50"
        onClick={() => { window.location.href = destino; }}
      >
        <svg className="h-4 w-4" viewBox="0 0 24 24" aria-hidden="true">
          <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.27-4.74 3.27-8.1z" />
          <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23z" />
          <path fill="#FBBC05" d="M5.84 14.1a6.6 6.6 0 0 1 0-4.2V7.06H2.18a11 11 0 0 0 0 9.88l3.66-2.84z" />
          <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15A11 11 0 0 0 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z" />
        </svg>
        {label}
      </Button>
    </div>
  );
}
