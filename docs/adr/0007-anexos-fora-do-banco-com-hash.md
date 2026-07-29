> **IMPLEMENTADO** em 2026-07-29 — ver [ADR 0016](0016-armazenamento-de-anexos-em-volume.md)
> para o desenho do armazenamento (endereçamento por conteúdo, dedup, fallback do legado)
> e `scripts/migrate_attachments_to_disk.py` para a migração dos anexos já existentes.

# Anexos: metadados + hash no banco; conteúdo fora do banco em produção

Anexos eram blobs `LargeBinary` no banco, lidos integralmente em RAM antes da validação e sem verificação de conteúdo. Decidimos: upload validado em chunks com limite, assinatura de conteúdo (magic bytes de PNG/JPEG/PDF/WebP) além do Content-Type, hash SHA-256 armazenado, quota por workspace; em produção o conteúdo vai para disco/volume (object storage no futuro) e o banco guarda apenas metadados + hash. O hardening de validação entra na Onda 1; a mudança de armazenamento, quando o modelo de anexo for revisitado.
