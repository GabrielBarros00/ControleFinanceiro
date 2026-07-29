import * as React from 'react';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Paperclip, FileText, Image as ImageIcon, Trash2, Loader2, Upload } from 'lucide-react';
import {
  ATTACHMENT_ACCEPT,
  useAttachments,
  validateAttachmentFile,
  type AttachmentMeta,
} from '@/hooks/use-attachments';
import { getApiErrorMessage } from '@/lib/api-error';
import { useConfirm } from '@/components/ui/confirm';

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

// Linha da lista — a mesma UI serve para anexo salvo e para arquivo em espera
interface Row {
  key: string;
  filename: string;
  contentType: string;
  size: number;
  onOpen: () => void;
  onRemove: () => void;
}

interface ShellProps {
  rows: Row[];
  actionLabel: string;
  busy?: boolean;
  hint?: string;
  error: string | null;
  onPick: (files: File[]) => void;
}

// Casca comum: cabeçalho + seletor de arquivo + lista
function AttachmentsShell({ rows, actionLabel, busy = false, hint, error, onPick }: ShellProps) {
  const inputRef = React.useRef<HTMLInputElement>(null);

  return (
    <div className="mt-6 space-y-3 p-4 rounded-xl bg-accent/20 border border-border/50">
      <div className="flex items-center justify-between">
        <Label className="text-sm font-bold text-foreground flex items-center gap-2">
          <Paperclip className="h-4 w-4 text-primary" /> Anexos (recibos, notas)
        </Label>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ATTACHMENT_ACCEPT}
          className="hidden"
          aria-label="Enviar anexo"
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            e.target.value = '';
            if (files.length > 0) onPick(files);
          }}
        />
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={busy}
          onClick={() => inputRef.current?.click()}
          className="h-8 gap-1.5 border-primary text-primary hover:bg-primary/10 font-bold"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
          {actionLabel}
        </Button>
      </div>

      {rows.length === 0 ? (
        <p className="text-xs text-muted-foreground">{hint ?? 'Nenhum anexo. JPG, PNG, WebP ou PDF até 5 MB.'}</p>
      ) : (
        <ul className="space-y-2">
          {rows.map((row) => (
            <li key={row.key} className="flex items-center gap-3 rounded-lg border border-border bg-background/50 px-3 py-2">
              {row.contentType === 'application/pdf'
                ? <FileText className="h-4 w-4 text-destructive shrink-0" />
                : <ImageIcon className="h-4 w-4 text-primary shrink-0" />}
              <button
                type="button"
                onClick={row.onOpen}
                className="flex-1 truncate text-left text-sm font-medium text-foreground hover:text-primary hover:underline"
              >
                {row.filename}
              </button>
              <span className="text-[10px] text-muted-foreground shrink-0">{formatSize(row.size)}</span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={`Remover anexo ${row.filename}`}
                onClick={row.onRemove}
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

// Separa o que é válido do que o backend recusaria (tipo/tamanho), já na escolha
function partition(files: File[]): { accepted: File[]; problems: string[] } {
  const accepted: File[] = [];
  const problems: string[] = [];
  for (const file of files) {
    const problem = validateAttachmentFile(file);
    if (problem) problems.push(problem);
    else accepted.push(file);
  }
  return { accepted, problems };
}

// Criação: ainda não existe transaction_id, então os arquivos esperam em memória
// no form e sobem depois do POST da despesa (ver NewTransactionDialog).
function PendingAttachments({
  files,
  onChange,
}: {
  files: File[];
  onChange: (files: File[]) => void;
}) {
  const [error, setError] = React.useState<string | null>(null);

  const handlePick = (picked: File[]) => {
    const { accepted, problems } = partition(picked);
    setError(problems.join(' ') || null);
    if (accepted.length > 0) onChange([...files, ...accepted]);
  };

  // Preview local, sem ida ao servidor (o arquivo ainda não subiu)
  const openLocal = (file: File) => {
    const url = URL.createObjectURL(file);
    window.open(url, '_blank', 'noopener');
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  };

  const rows: Row[] = files.map((file, index) => ({
    key: `${file.name}-${file.size}-${index}`,
    filename: file.name,
    contentType: file.type,
    size: file.size,
    onOpen: () => openLocal(file),
    onRemove: () => onChange(files.filter((_, i) => i !== index)),
  }));

  return (
    <AttachmentsShell
      rows={rows}
      actionLabel="Anexar"
      error={error}
      onPick={handlePick}
      hint="Nenhum anexo. JPG, PNG, WebP ou PDF até 5 MB — enviados junto com a despesa."
    />
  );
}

// Despesa já salva: upload/remoção direto no servidor
function SavedAttachments({ transactionId }: { transactionId: number }) {
  const { attachments, upload, remove, open, isUploading } = useAttachments(transactionId);
  const [error, setError] = React.useState<string | null>(null);
  const confirm = useConfirm();

  const handlePick = async (picked: File[]) => {
    const { accepted, problems } = partition(picked);
    setError(problems.join(' ') || null);
    for (const file of accepted) {
      try {
        await upload(file);
      } catch (err) {
        problems.push(getApiErrorMessage(err, `Erro ao enviar "${file.name}".`));
        setError(problems.join(' '));
      }
    }
  };

  const handleDelete = async (attachment: AttachmentMeta) => {
    const ok = await confirm({
      title: 'Remover anexo',
      description: `Remover o anexo "${attachment.filename}"? Esta ação não pode ser desfeita.`,
      confirmLabel: 'Remover',
      destructive: true,
    });
    if (!ok) return;
    setError(null);
    try {
      await remove(attachment.id);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Erro ao remover o anexo.'));
    }
  };

  const rows: Row[] = attachments.map((att) => ({
    key: String(att.id),
    filename: att.filename,
    contentType: att.content_type,
    size: att.size_bytes,
    onOpen: () => open(att).catch(() => setError('Erro ao abrir o anexo.')),
    onRemove: () => handleDelete(att),
  }));

  return (
    <AttachmentsShell
      rows={rows}
      actionLabel="Enviar"
      busy={isUploading}
      error={error}
      onPick={handlePick}
    />
  );
}

interface AttachmentsSectionProps {
  /** Despesa já salva: os anexos vão direto para o servidor. */
  transactionId?: number | null;
  /** Criação: sem id ainda, os arquivos ficam aqui e sobem depois do POST. */
  pendingFiles?: File[];
  onPendingFilesChange?: (files: File[]) => void;
}

// Recibos/notas da transação: upload (JPG/PNG/WebP/PDF), visualizar e remover.
// Sem `transactionId` (criação), a lista fica em espera até a despesa existir.
export function AttachmentsSection({
  transactionId = null,
  pendingFiles = [],
  onPendingFilesChange,
}: AttachmentsSectionProps) {
  if (transactionId == null) {
    return <PendingAttachments files={pendingFiles} onChange={onPendingFilesChange ?? (() => {})} />;
  }
  return <SavedAttachments transactionId={transactionId} />;
}
