// A API devolve erros no envelope {"error": {"message": "..."}} (handler global
// do backend); "detail" cru só aparece se a resposta não passou pelo handler.
interface ApiErrorBody {
  error?: { message?: string };
  detail?: string;
}

export function getApiErrorMessage(
  err: unknown,
  fallback = 'Erro inesperado. Tente novamente.'
): string {
  if (err && typeof err === 'object' && 'response' in err) {
    const response = (err as { response?: { data?: ApiErrorBody } }).response;
    const message = response?.data?.error?.message ?? response?.data?.detail;
    if (typeof message === 'string' && message.trim()) return message;
  }
  return fallback;
}
