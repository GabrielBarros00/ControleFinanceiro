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
 */
import { execSync } from 'node:child_process';

/**
 * Cada entrada é uma decisão de risco explícita, não um "silencia isso".
 * `revisar_em` no passado = o gate falha e a decisão é retomada.
 */
const ACEITOS = [
  {
    id: 'GHSA-qwww-vcr4-c8h2',
    pacote: 'react-router',
    motivo:
      'Bypass de CSRF restrito ao modo RSC (React Server Components). Este app é ' +
      'SPA com BrowserRouter, não usa RSC nem Server Actions, e não há caminho ' +
      'explorável. A correção só existe para trás (downgrade para 7.11.0), o que ' +
      'custaria sete versões de correções por um risco que não corremos.',
    revisar_em: '2026-11-01',
  },
];

function auditar() {
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
    if (!erro.stdout) throw erro;
    return JSON.parse(erro.stdout);
  }
}

const hoje = new Date().toISOString().slice(0, 10);
const relatorio = auditar();
const graves = [];
const silenciados = [];

for (const [nome, vuln] of Object.entries(relatorio.vulnerabilities ?? {})) {
  if (!['high', 'critical'].includes(vuln.severity)) continue;

  // `via` mistura strings (dependência transitiva) e objetos (o advisory em si).
  const advisories = (vuln.via ?? []).filter((v) => typeof v === 'object');
  for (const adv of advisories) {
    const aceito = ACEITOS.find((a) => adv.url?.includes(a.id));
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
