# Armazenamento de anexos em volume, endereçado por conteúdo

Implementa a parte de armazenamento do [ADR 0007](0007-anexos-fora-do-banco-com-hash.md), que continuava pendente: o conteúdo seguia como `LargeBinary` no banco.

## Contexto

Recibo é dado grande, imutável e que nenhuma consulta lê — o pior perfil possível para uma coluna de banco. Com `data` no Postgres, cada dump carregava todos os comprovantes já enviados, e servir um anexo significava trazer o blob inteiro pelo driver antes de escrever na resposta. A cota de 200 MB por workspace só limitava o estrago; não o evitava.

## Decisão

**Os bytes vão para um diretório** (`settings.ATTACHMENT_STORAGE_DIR`; volume `attachments_data` no Compose). O banco guarda metadados, `sha256` e `storage_key`. `app/services/attachment_storage.py` é o seam — trocar por object storage é reimplementar `save`/`read`/`delete`.

**Chave endereçada pelo conteúdo:** `{workspace}/{sha[:2]}/{sha}`. Nunca deriva do nome enviado pelo cliente (path traversal), o prefixo por workspace mantém o isolamento visível no disco, e o par de caracteres evita um diretório com milhões de entradas.

**Dedup dentro do workspace é consequência, não recurso extra:** o mesmo comprovante enviado duas vezes aponta para o mesmo objeto. Por isso apagar um anexo **não** apaga o arquivo cegamente — `keys_to_free` confere se sobrou alguma linha referenciando a chave.

**Ordem das operações:** grava-se o arquivo **antes** do commit e apaga-se **depois** dele. Um arquivo órfão é desperdício de disco, recuperável; uma linha viva apontando para um recibo que não existe é um dado quebrado que o usuário vê.

**Escrita atômica** (temporário + `os.replace` + `fsync`): uma queda no meio do upload deixaria um arquivo truncado que passaria pela validação de tamanho e corromperia o recibo em silêncio.

**Migração em dois passos, de propósito.** A migração de schema (`e3f9a17c4b28`) adiciona `storage_key` e torna `data` nullable, mas **não move bytes** — escrever no sistema de arquivos a partir de um DDL destruiria recibos se o volume não estivesse montado. `scripts/migrate_attachments_to_disk.py` faz o transporte, com verificação pós-escrita antes de zerar a coluna. Enquanto houver linha com `data`, a leitura cai nela: nenhuma janela de indisponibilidade.

## Consequências

- **O backup passa a ser DOIS artefatos**: o dump do Postgres e o volume de anexos. Restaurar só o banco devolve os lançamentos com os recibos quebrados. Está anotado no `docker-compose.yml` e no [SETUP](../../SETUP.md).
- Objeto ausente no volume responde **404 com mensagem explicável** (mais o log de erro), não 500: é falha de operação, e mandar o usuário caçar um bug de aplicação seria enganá-lo.
- A coluna `data` continua no schema até o operador rodar o script e a contagem de pendentes zerar. Dropá-la é uma migração de limpeza posterior — nunca antes.
- A cota por workspace continua valendo (`size_bytes` no banco); ela agora protege o volume em vez do banco.
