#!/usr/bin/env node
/*
 * Gate de vulnerabilidades do frontend, com allowlist JUSTIFICADA e datada.
 *
 * O CI rodava `npm audit --omit=dev --audit-level=high` cru, e ele está vermelho
 * por GHSA-qwww-vcr4-c8h2 (react-router). O advisory não tem correção para
 * frente: atinge 7.12.0–8.2.0 e o `--force` REGRIDE para 7.11.0, jogando fora
 * sete versões de correções por um problema que este app não tem.
 *
 * As duas saídas ruins eram: deixar o gate vermelho para sempre (todo mundo
 * aprende a ignorar) ou baixar `--audit-level` para `critical` (fica cego para o
 * PRÓXIMO high, que pode ser real). A allowlist resolve as duas: o gate segue
 * falhando em qualquer high/critical, e a exceção é uma linha versionada, com
 * motivo escrito e data de revisão — quando ela vence, o gate volta a falhar e
 * alguém decide de novo.
 *
 * `--relatorio <arquivo>` lê um relatório de arquivo em vez de rodar o npm, e
 * `--aceitos <arquivo>` substitui a lista de exceções. Ambos existem só para
 * os testes — o gate real não recebe nenhum dos dois.
 * Existe para os testes provarem que o gate falha FECHADO diante de um payload
 * ruim — a falha que ele precisa ter é a mais difícil de observar por acidente,
 * porque só acontece quando o registry está fora do ar.
 */
import { execSync } from 'node:child_process';
import { readFileSync } from 'node:fs';

/**
 * Cada entrada é uma decisão de risco explícita, não um "silencia isso".
 * `revisar_em` no passado = o gate falha e a decisão é retomada.
 */
// Vazia hoje, e é assim que deve ficar: exceção aberta é dívida de segurança.
//
// A entrada `GHSA-qwww-vcr4-c8h2` (react-router, bypass de CSRF no modo RSC)
// saiu na Onda 9. O aviso de "não corresponde a nenhuma vulnerabilidade do
// relatório" — que o próprio gate emite, logo abaixo — apontou que ela já não
// casava com nada em `react-router@7.18.2`. Uma exceção que sobrevive à
// vulnerabilidade que a justificou vira uma porta destrancada de que ninguém
// lembra.
const ACEITOS = carregarAceitos();

/**
 * A lista, ou a de um arquivo via `--aceitos <arquivo>`.
 *
 * Mesmo motivo do `--relatorio`: as regras de exceção (silenciar uma high
 * coberta, avisar de uma exceção que já não casa com nada) precisam de teste, e
 * testá-las contra a lista de PRODUÇÃO acoplava a suíte ao seu conteúdo — foi o
 * que quebrou quando a exceção do react-router saiu. A lista certa é vazia; o
 * comportamento dela tem de continuar coberto mesmo assim.
 */
function carregarAceitos() {
  const i = process.argv.indexOf('--aceitos');
  if (i === -1) return [];
  const caminho = process.argv[i + 1];
  if (!caminho) abortar('`--aceitos` exige o caminho de um arquivo.');
  try {
    return JSON.parse(readFileSync(caminho, 'utf8'));
  } catch (erro) {
    abortar(`não foi possível ler ${caminho}: ${erro.message}`);
  }
}

/** Aborta o gate com uma mensagem — nunca deixa passar verde por omissão. */
function abortar(motivo) {
  console.error(`\nNão foi possível auditar as dependências: ${motivo}`);
  console.error(
    'O gate falha FECHADO de propósito: um relatório que não é um relatório ' +
    'não é prova de que não há vulnerabilidade.\n',
  );
  process.exit(1);
}

/**
 * Valida que o payload é mesmo um relatório do `npm audit`.
 *
 * Aqui morava o buraco: o laço lia `relatorio.vulnerabilities ?? {}`, e o `??`
 * transformava "isto não é um relatório" em "nenhuma vulnerabilidade". Quando o
 * registry falha, o npm imprime um JSON de ERRO **em stdout** e sai com código
 * != 0 — ou seja, ele passa pelo `catch` abaixo, faz `JSON.parse` sem problema,
 * não tem a chave `vulnerabilities`, e o gate terminava com "Sem
 * vulnerabilidades" e código zero. Auditoria nenhuma tinha rodado.
 */
function validarRelatorio(relatorio) {
  if (!relatorio || typeof relatorio !== 'object' || Array.isArray(relatorio)) {
    abortar('a saída do npm audit não é um objeto JSON.');
  }
  if (relatorio.error) {
    const e = relatorio.error;
    abortar(`o registry respondeu com erro (${e.code ?? '?'}): ${e.summary ?? e.detail ?? ''}`);
  }
  if (typeof relatorio.vulnerabilities !== 'object' || relatorio.vulnerabilities === null) {
    abortar('o relatório não traz a seção `vulnerabilities` (formato inesperado).');
  }
  const contadores = relatorio.metadata?.vulnerabilities;
  if (typeof contadores !== 'object' || contadores === null) {
    abortar('o relatório não traz `metadata.vulnerabilities` (formato inesperado).');
  }
  for (const nivel of ['high', 'critical']) {
    if (typeof contadores[nivel] !== 'number') {
      abortar(`\`metadata.vulnerabilities.${nivel}\` ausente ou não numérico.`);
    }
  }
  return contadores;
}

function auditar() {
  const i = process.argv.indexOf('--relatorio');
  if (i !== -1) {
    const caminho = process.argv[i + 1];
    if (!caminho) abortar('`--relatorio` exige o caminho de um arquivo.');
    try {
      return JSON.parse(readFileSync(caminho, 'utf8'));
    } catch (erro) {
      abortar(`não foi possível ler ${caminho}: ${erro.message}`);
    }
  }
  try {
    // `execSync` com comando CONSTANTE: `execFileSync('npm.cmd', [...])` falha
    // com EINVAL no Node ≥20 (arquivos .cmd exigem shell) e, com `shell: true`,
    // dispara DEP0190 por concatenar argumentos sem escapar. Aqui não há
    // argumento interpolado — a string é literal —, então nenhum dos dois vale.
    return JSON.parse(
      execSync('npm audit --omit=dev --json', { encoding: 'utf8' }),
    );
  } catch (erro) {
    // `npm audit` sai com código != 0 quando ENCONTRA algo — é o caso normal
    // aqui. Sem stdout, aí sim foi falha de verdade (rede, lockfile inválido).
    if (!erro.stdout) {
      abortar(erro.message ?? String(erro));
    }
    try {
      return JSON.parse(erro.stdout);
    } catch {
      abortar('a saída do npm audit não é JSON válido.');
    }
  }
}

const hoje = new Date().toISOString().slice(0, 10);
const relatorio = auditar();
const contadores = validarRelatorio(relatorio);
const graves = [];
const silenciados = [];
const casados = new Set();
let encontradas = 0;

for (const [nome, vuln] of Object.entries(relatorio.vulnerabilities)) {
  if (!['high', 'critical'].includes(vuln.severity)) continue;
  encontradas += 1;

  // `via` mistura strings (dependência transitiva) e objetos (o advisory em si).
  const advisories = (vuln.via ?? []).filter((v) => typeof v === 'object');
  for (const adv of advisories) {
    const aceito = ACEITOS.find((a) => adv.url?.includes(a.id));
    if (aceito) casados.add(aceito.id);
    if (aceito && aceito.revisar_em > hoje) {
      silenciados.push(`${nome}: ${aceito.id} (revisar até ${aceito.revisar_em})`);
    } else if (aceito) {
      graves.push(
        `${nome}: ${aceito.id} — a exceção VENCEU em ${aceito.revisar_em}. ` +
        'Reavalie: atualize o pacote ou renove a decisão em scripts/audit-gate.mjs.',
      );
    } else {
      graves.push(`${nome} [${vuln.severity}]: ${adv.title ?? adv.url}`);
    }
  }
}

// Contagem cruzada: o laço acima anda por `vulnerabilities`, os contadores vêm
// de `metadata`. Se discordarem, o formato do relatório mudou e a varredura
// deixou de enxergar o que deveria — falhar é a única resposta honesta.
const esperadas = contadores.high + contadores.critical;
if (encontradas !== esperadas) {
  abortar(
    `o relatório declara ${esperadas} vulnerabilidade(s) high/critical em ` +
    `metadata, mas a varredura encontrou ${encontradas}. O formato do ` +
    'npm audit provavelmente mudou.',
  );
}

// Exceção que não casa com nada é lixo acumulando: ou o pacote foi corrigido (e
// a linha deve sair), ou o advisory mudou de id (e o gate está cego para ele).
for (const aceito of ACEITOS) {
  if (!casados.has(aceito.id)) {
    console.warn(
      `atenção · a exceção ${aceito.id} (${aceito.pacote}) não corresponde a ` +
      'nenhuma vulnerabilidade do relatório. Remova-a de scripts/audit-gate.mjs.',
    );
  }
}

for (const linha of silenciados) {
  console.log(`aceito · ${linha}`);
}

if (graves.length > 0) {
  console.error('\nVulnerabilidades high/critical sem decisão registrada:\n');
  for (const linha of graves) console.error(`  ✗ ${linha}`);
  console.error(
    '\nCorrija a dependência ou registre a exceção (com motivo e data) em ' +
    'frontend/scripts/audit-gate.mjs.\n',
  );
  process.exit(1);
}

console.log(`\nSem vulnerabilidades high/critical pendentes (${silenciados.length} aceita(s)).`);
