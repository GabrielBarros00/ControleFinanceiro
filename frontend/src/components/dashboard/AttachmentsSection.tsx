import * as React from 'react';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Paperclip, FileText, Image as ImageIcon, Trash2, Loader2, Upload } from 'lucide-react';
import { useAttachments, type AttachmentMeta } from '@/hooks/use-attachments';
import { getApiErrorMessage } from '@/lib/api-error';

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

// Recibos/notas da transação: upload (JPG/PNG/WebP/PDF), visualizar e remover
export function AttachmentsSection({ transactionId }: { transactionId: number }) {
  const { attachments, upload, remove, open, isUploading } = useAttachments(transactionId);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [error, setError] = React.useState<string | null>(null);

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setError(null);
    try {
      await upload(file);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Erro ao enviar o anexo.'));
    }
  };

  const handleDelete = async (attachment: AttachmentMeta) => {
    if (!confirm(`Remover o anexo "${attachment.filename}"?`)) return;
    setError(null);
    try {
      await remove(attachment.id);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Erro ao remover o anexo.'));
    }
  };

  return (
    <div className="mt-6 space-y-3 p-4 rounded-xl bg-accent/20 border border-border/50">
      <div className="flex items-center justify-between">
        <Label className="text-sm font-bold text-foreground flex items-center gap-2">
          <Paperclip className="h-4 w-4 text-primary" /> Anexos (recibos, notas)
        </Label>
        <input
          ref={inputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp,application/pdf"
          className="hidden"
          aria-label="Enviar anexo"
          onChange={handleFileChange}
        />
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={isUploading}
          onClick={() => inputRef.current?.click()}
          className="h-8 gap-1.5 border-primary text-primary hover:bg-primary/10 font-bold"
        >
          {isUploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
          Enviar
        </Button>
      </div>

      {attachments.length === 0 ? (
        <p className="text-xs text-muted-foreground">Nenhum anexo. JPG, PNG, WebP ou PDF até 5 MB.</p>
      ) : (
        <ul className="space-y-2">
          {attachments.map((att) => (
            <li key={att.id} className="flex items-center gap-3 rounded-lg border border-border bg-background/50 px-3 py-2">
              {att.content_type === 'application/pdf'
                ? <FileText className="h-4 w-4 text-destructive shrink-0" />
                : <ImageIcon className="h-4 w-4 text-primary shrink-0" />}
              <button
                type="button"
                onClick={() => open(att).catch(() => setError('Erro ao abrir o anexo.'))}
                className="flex-1 truncate text-left text-sm font-medium text-foreground hover:text-primary hover:underline"
              >
                {att.filename}
              </button>
              <span className="text-[10px] text-muted-foreground shrink-0">{formatSize(att.size_bytes)}</span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={`Remover anexo ${att.filename}`}
                onClick={() => handleDelete(att)}
                className="h-7 w-7 p-0 text-destructive hover:bg-destructive/10"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </li>
          ))}
        </ul>
      )}
      {error && <p className="text-xs text-destructive font-medium">{error}</p>}
    </div>
  );
}
