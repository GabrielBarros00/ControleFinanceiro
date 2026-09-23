# Política de privacidade — integração com agentes de IA (MODELO)

> **Modelo a preencher e revisar.** Não é aconselhamento jurídico. Os trechos entre
> `[colchetes]` dependem de decisões do responsável pelo serviço (controlador,
> contato, base legal, retenção). Publique a versão final numa página pública e
> informe a URL em `integrations/controle-financeiro-plugin/plugin.json`.

**Responsável:** [nome/razão social], [contato do encarregado de dados/DPO]
**Última atualização:** [data]

## 1. O que é a integração

O Controle Financeiro permite conectar agentes de IA de terceiros (como ChatGPT,
Claude, Codex e Gemini) à sua conta, por meio do protocolo MCP, para consultar e
registrar informações financeiras por conversa. A conexão só existe depois que
você a autoriza, na tela de consentimento do próprio Controle Financeiro, e pode
ser desfeita a qualquer momento.

## 2. Quais dados o agente acessa

Somente os dados que você já vê no Controle Financeiro, limitados às permissões
que você marcar ao autorizar: lançamentos, faturas de cartão, contas e saldos,
rendas, dívidas e acertos com pessoas dos seus espaços, orçamentos e recorrências.
Nomes de outras pessoas aparecem quando fazem parte de um lançamento compartilhado
com você. O agente não acessa senhas, anexos (recibos), dados de outros usuários
nem funções administrativas.

## 3. Para onde os dados vão

Ao usar a integração, as informações devolvidas ao agente passam a ser tratadas
também pelo **provedor do agente** que você escolheu, conforme a política de
privacidade dele: [links: OpenAI, Anthropic, Google, …]. O Controle Financeiro não
controla esse tratamento.

## 4. O que registramos

- Um registro técnico de cada ação do agente: qual função foi usada, qual
  aplicativo, quando, quanto tempo levou, se deu certo e quais registros foram
  afetados — **sem** o conteúdo da conversa nem os valores enviados. Guardado por
  [180 dias].
- As alterações feitas pelo agente entram no histórico de auditoria do espaço,
  identificadas como "via IA".
- Credenciais da conexão são guardadas apenas de forma cifrada por hash e
  descartadas após o vencimento.

**Base legal:** [execução de contrato / consentimento — definir].

## 5. Como revogar

- Em **Configurações › Integrações com IA › Desconectar**, com efeito imediato.
- Trocar a senha desconecta todos os agentes.
- Remover o conector no aplicativo do agente apaga as credenciais do lado dele.

## 6. Seus direitos

[Direitos do titular conforme a LGPD — acesso, correção, eliminação, portabilidade,
informação sobre compartilhamento, revogação do consentimento — e como exercê-los.]

## 7. Contato

[e-mail/canal de contato]
