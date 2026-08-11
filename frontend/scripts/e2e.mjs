/**
 * Roda a suíte E2E de DESENVOLVIMENTO com o ciclo de vida dos servidores na
 * nossa mão — e, principalmente, com garantia de que o comando ENCERRA.
 *
 * Por que não `webServer` do Playwright:
 *
 * O travamento no Windows já foi atacado duas vezes dentro do
 * `playwright.config.ts` (primeiro o `&&` que interpunha um shell, depois o
 * `reporter: 'html'` que subia um servidor de relatório) e voltou nas duas. A
 * terceira auditoria reportou o runner pendurado ATÉ QUANDO termina em "No tests
 * found" — cenário em que o Playwright aborta antes de subir servidor nenhum, o
 * que significa que o problema não estava no que a configuração vinha tratando.
 *
 * A diferença aqui não é uma teoria melhor sobre a causa: é que o encerramento
 * deixa de depender dela. Os servidores sobem com PID conhecido, morrem numa
 * cláusula `finally` que roda em qualquer saída, e o processo termina em
 * `process.exit(codigo)` — que fecha o processo mesmo com handle aberto que
 * ninguém identificou. Um gate de E2E que não devolve o terminal não é um gate:
 * ninguém o roda, e o que ele cobre apodrece (foi o que aconteceu com o
 * `smoke_prod`).
 *
 * Uso: `npm run test:e2e [-- args do playwright]`
 */
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const FRONTEND = path.resolve(import.meta.dirname, '..');
const BACKEND = path.resolve(FRONTEND, '..', 'backend');
const WINDOWS = process.platform === 'win32';

// Python do VENV do projeto, não o do PATH: numa máquina com outro Python à
// frente, o uvicorn morre no import (`MissingBackendError: argon2`) antes do
// primeiro teste. Mesma resolução de plataforma que o Makefile faz.
const PYTHON =
  process.env.E2E_PYTHON ??
  path.resolve(FRONTEND, '..', '.venv', WINDOWS ? 'Scripts/python.exe' : 'bin/python');

// Falha AQUI, e não lá dentro. Sem venv (o caso do CI, que instala global), o
// spawn abaixo estouraria com um ENOENT sem contexto, ou — pior, se houvesse um
// `python` qualquer no caminho — o uvicorn morreria no import por falta de
// dependência, com a mensagem soterrada no log do servidor.
if (!process.env.E2E_PYTHON && !fs.existsSync(PYTHON)) {
  console.error(
    `[e2e] Python do venv não encontrado em ${PYTHON}.\n` +
    `      Crie o venv do projeto ou aponte E2E_PYTHON para o interpretador certo.`,
  );
  process.exit(1);
}

const SERVIDORES = [
  {
    nome: 'backend',
    comando: PYTHON,
    args: ['-m', 'uvicorn', 'app.main:app', '--port', '8000'],
    cwd: BACKEND,
    // `127.0.0.1`, NUNCA `localhost`: no Windows o resolvedor devolve `::1`
    // primeiro, e o uvicorn escuta só em IPv4. O `fetch` batia num endereço onde
    // não havia ninguém e a espera estourava os 60 s com o servidor de pé — o
    // erro dizia "não respondeu", que é exatamente a pista errada.
    url: 'http://127.0.0.1:8000/api/v1/health',
    // Banco DESCARTÁVEL e rate limit desligado: a suíte registra vários usuários
    // em sequência, e o `dev.db` não pode ser tocado por ela. A proteção de rate
    // limit tem testes próprios no backend e é exercitada ligada pela `e2e-prod`.
    env: { RATE_LIMIT_ENABLED: 'False', DATABASE_URL: 'sqlite:///./e2e.db' },
  },
  {
    nome: 'frontend',
    // O entrypoint do vite direto: `npm run dev` e `npx vite` são wrappers que o
    // deixam como processo NETO, e o `.cmd` do Windows ainda traz um shell junto.
    comando: process.execPath,
    args: [path.join(FRONTEND, 'node_modules', 'vite', 'bin', 'vite.js'), '--port', '5173', '--strictPort'],
    cwd: FRONTEND,
    url: 'http://127.0.0.1:5173',
    env: {},
  },
];

const processos = [];

function subir({ nome, comando, args, cwd, env, url }) {
  const filho = spawn(comando, args, {
    cwd,
    env: { ...process.env, ...env },
    // `pipe`, não `inherit`: um servidor que sobrevivesse à rodada seguraria o
    // stdout HERDADO, e quem chamou este script continuaria esperando EOF muito
    // depois de o processo ter terminado — exatamente o sintoma de "roda de novo
    // e trava mesmo sem testes". O que interessa do log sai abaixo, quando falha.
    stdio: ['ignore', 'pipe', 'pipe'],
    // POSIX: o filho vira líder do próprio grupo, e aí `kill(-pid)` leva a árvore.
    // No Windows quem faz esse papel é o `taskkill /T`.
    detached: !WINDOWS,
  });

  const log = [];
  const guardar = (buf) => {
    log.push(buf.toString());
    if (log.length > 200) log.shift();
  };
  filho.stdout.on('data', guardar);
  filho.stderr.on('data', guardar);

  const registro = { nome, filho, log, url };
  processos.push(registro);
  return registro;
}

function derrubar({ nome, filho }) {
  if (filho.exitCode !== null || filho.signalCode !== null) return;
  if (WINDOWS) {
    // `/T` leva os descendentes; `/F` não pede licença. Um uvicorn com WebSocket
    // aberto pode ignorar o pedido gentil de encerramento, e este script não tem
    // nada a preservar — o banco é descartável.
    spawnSync('taskkill', ['/PID', String(filho.pid), '/T', '/F'], { stdio: 'ignore' });
  } else {
    try {
      process.kill(-filho.pid, 'SIGTERM');
    } catch {
      // já morreu entre a checagem e o sinal
    }
  }
  console.log(`[e2e] ${nome} encerrado`);
}

function derrubarTodos() {
  for (const registro of processos) derrubar(registro);
}

/**
 * `127.0.0.1` E `localhost`, porque os dois servidores discordam.
 *
 * No Windows `localhost` resolve para `::1` antes de `127.0.0.1`. O uvicorn
 * escuta só em IPv4, então sondá-lo por `localhost` bate onde não há ninguém; o
 * vite faz `listen('localhost')` e atende no IPv6, então sondá-lo por
 * `127.0.0.1` falha pelo motivo simétrico. Nos dois casos o sintoma é idêntico
 * ao de servidor que não subiu — e a mensagem de erro aponta para o lugar
 * errado. Tentar os dois endereços custa uma requisição extra e acaba com a
 * classe inteira de engano.
 */
function enderecos(url) {
  const alvo = new URL(url);
  const hosts =
    alvo.hostname === '127.0.0.1' ? ['127.0.0.1', 'localhost']
    : alvo.hostname === 'localhost' ? ['localhost', '127.0.0.1']
    : [alvo.hostname];
  return hosts.map((host) => {
    const copia = new URL(url);
    copia.hostname = host;
    return copia.toString();
  });
}

// 120 s, não 60: num banco recém-apagado o backend roda a cadeia inteira de
// migrações no lifespan (ADR 0005) antes de atender a primeira requisição.
async function esperar(registro, timeoutMs = 120_000) {
  const limite = Date.now() + timeoutMs;
  const candidatos = enderecos(registro.url);
  while (Date.now() < limite) {
    if (registro.filho.exitCode !== null) {
      throw new Error(
        `${registro.nome} morreu com código ${registro.filho.exitCode}:\n${registro.log.join('')}`,
      );
    }
    for (const candidato of candidatos) {
      try {
        const resposta = await fetch(candidato);
        if (resposta.ok) return;
      } catch {
        // ainda subindo, ou é o endereço da outra família
      }
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(
    `${registro.nome} não respondeu em ${candidatos.join(' nem ')} em ${timeoutMs / 1000}s:\n${registro.log.join('')}`,
  );
}

async function main() {
  // Banco descartável apagado ANTES de o backend abrir o arquivo — depois disso
  // o SQLite segura o handle e o `rm` falha com EPERM no Windows. Os `-wal`/`-shm`
  // vão junto: sem eles o SQLite reconstrói o estado recém-apagado.
  const E2E_DB = path.join(BACKEND, 'e2e.db');
  for (const arquivo of [E2E_DB, `${E2E_DB}-wal`, `${E2E_DB}-shm`]) {
    fs.rmSync(arquivo, { force: true });
  }

  for (const servidor of SERVIDORES) {
    const registro = subir(servidor);
    await esperar(registro);
    console.log(`[e2e] ${registro.nome} de pé em ${registro.url}`);
  }

  const playwright = spawn(
    process.execPath,
    [path.join(FRONTEND, 'node_modules', '@playwright', 'test', 'cli.js'), 'test', ...process.argv.slice(2)],
    {
      cwd: FRONTEND,
      // O `cli.js` direto pelo mesmo motivo do vite: o `.bin/playwright` do
      // Windows é um `.cmd`.
      stdio: 'inherit',
      env: { ...process.env, E2E_EXTERNAL_SERVERS: '1' },
    },
  );

  return new Promise((resolve) => {
    playwright.on('exit', (codigo, sinal) => resolve(codigo ?? (sinal ? 1 : 0)));
  });
}

// Ctrl+C também passa pela limpeza: sem isto, interromper a rodada deixava os
// dois servidores vivos — e é um servidor órfão segurando porta e pipe que faz a
// rodada SEGUINTE parecer travada.
for (const sinal of ['SIGINT', 'SIGTERM']) {
  process.on(sinal, () => {
    derrubarTodos();
    process.exit(130);
  });
}

let codigo = 1;
try {
  codigo = await main();
} catch (erro) {
  console.error(`[e2e] ${erro.message}`);
} finally {
  derrubarTodos();
}
// `process.exit` explícito, e é ele o ponto deste arquivo: qualquer handle que
// tenha sobrado (socket do fetch, pipe de um filho que demorou a morrer) manteria
// o event loop vivo e o comando pendurado. Aqui o código de saída já está
// decidido e não há nada a esperar.
process.exit(codigo);
