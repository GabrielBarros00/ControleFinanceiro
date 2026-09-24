# Privacidade na integração com IA

## O que o agente vê

Só o que a própria pessoa vê no app, dentro das permissões que ela marcou ao
autorizar. Leituras respeitam o acesso de cada espaço (quem só vê "o que o
envolve" continua vendo só isso). O agente **não** vê: outras contas, espaços de
que a pessoa não participa, anexos (só a contagem), senhas, sessões, a trilha de
auditoria de outros membros, nem nada da administração do site.

No anexo pelo terminal, o arquivo vai do computador direto para o app pelo link de
envio: ele não passa pela conversa nem pelo provedor do agente. O agente recebe de
volta só o nome, o tipo e o tamanho.

## Para onde vai

O que uma tool devolve entra na conversa com o agente e passa a estar sob a
política de privacidade do **provedor do agente** (OpenAI, Anthropic, Google…).
As respostas são mínimas de propósito: a busca devolve linhas resumidas e paginadas
(≤ 50), valores vêm como texto decimal e os nomes de outras pessoas aparecem só
quando fazem parte do lançamento consultado.

## O que fica registrado no app

- `mcptoolcall`: qual tool, qual cliente, quando, quanto demorou, se deu certo e
  quais ids foram afetados. **Sem argumentos, valores, títulos ou tokens.** Expurgo
  após 180 dias (`scripts/purge_old_records.py`).
- `auditlog`: as mudanças feitas pelo agente, como qualquer mudança do app, com a
  origem `mcp:<cliente>` (a tela de auditoria mostra "via IA").
- Credenciais OAuth: só o SHA-256; códigos, tokens vencidos e confirmações saem no
  expurgo logo depois de vencer.

## Como revogar

- **Configurações › Integrações com IA › Desconectar** (vale na hora).
- Trocar a senha desconecta todos os agentes.
- No próprio cliente (ex.: remover o conector no ChatGPT/Claude) — isso apaga o
  token do lado dele; para cortar também do lado do app, use Desconectar.
