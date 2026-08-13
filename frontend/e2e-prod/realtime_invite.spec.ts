import { test, expect } from '@playwright/test';
import { registerAndLogin, defaultWorkspace } from './helpers';

// Auditoria da stack de produção (nginx + backend production):
// 1) WebSocket através do proxy nginx: mutação de A aparece para B sem reload
//    e B ressincroniza após ficar offline (gap no seq → resync).
// 2) Convite por link aceito pela UI (/invite/:token).
const API = '/api/v1';

test.describe('Stack de produção: tempo real e convite por link', () => {
  test('WS via nginx: mutação de A chega a B sem reload e resync após offline', async ({ browser }) => {
    test.setTimeout(120_000);
    const ts = Date.now();
    const contextA = await browser.newContext();
    const contextB = await browser.newContext();

    await registerAndLogin(contextA, { name: 'Alice RT', email: `rt_a_${ts}@teste.com`, password: 'senha123' });
    await registerAndLogin(contextB, { name: 'Bruno RT', email: `rt_b_${ts}@teste.com`, password: 'senha123' });

    const wsA = await defaultWorkspace(contextA);
    await defaultWorkspace(contextB);

    const sharedWsName = `Compartilhado ${ts}`;
    await contextA.request.put(`${API}/workspaces/${wsA.id}`, { data: { name: sharedWsName } });
    const invite = await contextA.request.post(`${API}/workspaces/${wsA.id}/invites`, {
      data: { email: `rt_b_${ts}@teste.com`, role: 'member' },
    });
    // `invite_sent`, não `member_added`: convidar por e-mail deixou de adicionar
    // ninguém direto (consentimento no convite). O spec ficou preso na resposta
    // antiga e falhava AQUI, antes de chegar em qualquer asserção de WebSocket —
    // que é o que ele existe para testar.
    expect((await invite.json()).status).toBe('invite_sent');

    // E, por consequência, é preciso ACEITAR: sem isto B nunca vira membro e o
    // switcher do sidebar não teria o workspace compartilhado para escolher.
    // O token chega na notificação dentro do app.
    const avisos = await (await contextB.request.get(`${API}/notifications`)).json();
    const convite = avisos.items.find((n: { invite_token?: string }) => n.invite_token);
    expect(convite, 'B recebeu a notificação do convite').toBeTruthy();
    expect(
      (await contextB.request.post(`${API}/invites/accept/${convite.invite_token}`)).ok(),
    ).toBeTruthy();

    const pageA = await contextA.newPage();
    const pageB = await contextB.newPage();

    // Toda busca de lançamentos que B faz por HTTP.
    //
    // O teste afirma que B NÃO fica sabendo do lançamento enquanto o socket
    // está caído. Só que "não aparece na tela" é consequência, não causa: se o
    // TanStack Query resolver rebuscar por conta própria — foco de janela,
    // reconexão, montagem — o lançamento chega sem WebSocket nenhum e a
    // asserção reprova sem que nada esteja errado no produto.
    //
    // Contar as buscas transforma isso em evidência: durante a queda o número
    // não pode subir, e depois da reconexão TEM de subir (é o resync). Se o
    // teste falhar, a mensagem diz qual dos dois aconteceu.
    // QUALQUER GET da API, não apenas `/transactions`: a tela de Início monta a
    // lista "Onde você está envolvido" a partir de outros endpoints, então um
    // contador estreito diria "B não buscou nada" enquanto B buscava por outro
    // caminho — um falso negativo que apontaria a investigação para o lado
    // errado. Foi exatamente o risco na rodada anterior.
    let buscasDeB = 0;
    const urlsDeB: string[] = [];
    pageB.on('request', (r) => {
      if (r.method() === 'GET' && r.url().includes('/api/v1/')) {
        buscasDeB += 1;
        urlsDeB.push(r.url().replace(/^https?:\/\/[^/]+/, ''));
      }
    });

    // Quantas vezes a rota de WebSocket foi acionada. Se este número for ZERO,
    // a interceptação não está funcionando e todo o mecanismo de queda é
    // decorativo — o socket de B nunca passou por aqui.
    let rotasAcionadas = 0;

    // Queda de rede CONTROLADA para o socket de B.
    //
    // Aqui havia `contextB.setOffline(true)`, e ele não serve para este teste:
    // o modo offline do Chromium bloqueia conexões NOVAS, mas não derruba um
    // WebSocket JÁ ABERTO. O que a asserção seguinte media, na prática, era uma
    // corrida entre a emulação de rede e a chegada do frame — e o CI perdeu
    // essa corrida com o MESMO build de Chromium (v1217) em que ela passa
    // localmente. Teste que depende de quem chega primeiro reprova sozinho, e o
    // custo disso é um gate vermelho que ninguém confia (ver o histórico de
    // gates deste repositório).
    //
    // Derrubar o socket explicitamente é também o único jeito de GARANTIR a
    // lacuna de `seq`. Sem lacuna, o lançamento chegaria ao vivo e o teste
    // passaria sem nunca exercitar o resync — verde pelo motivo errado, que é
    // pior do que vermelho.
    //
    // Enquanto `quedaDeRede` estiver ligada, as reconexões do app também são
    // recusadas: é o que mantém B no escuro durante a janela.
    type RotaWS = Parameters<Parameters<typeof contextB.routeWebSocket>[1]>[0];
    let quedaDeRede = false;
    const socketsDeB = new Set<RotaWS>();
    await contextB.routeWebSocket(/\/ws\/workspaces\//, (ws) => {
      rotasAcionadas += 1;
      if (quedaDeRede) {
        ws.close();
        return;
      }
      socketsDeB.add(ws);
      ws.onClose(() => socketsDeB.delete(ws));
      ws.connectToServer();
    });

    await pageA.goto('/');
    await expect(pageA.getByRole('heading', { name: 'Início' })).toBeVisible({ timeout: 15_000 });
    await pageB.goto('/');
    await expect(pageB.getByRole('heading', { name: 'Início' })).toBeVisible({ timeout: 15_000 });

    await pageB.getByRole('button', { name: /Workspace/i }).click();
    await pageB.getByRole('button', { name: sharedWsName }).click();
    await expect(pageB.getByRole('button', { name: new RegExp(sharedWsName) })).toBeVisible();

    // Rateado com B: como `member` + `involved_only` (ADR 0018), B não vê despesa
    // que é só de A — e este spec mede entrega ao vivo, não privacidade.
    const meA = await (await contextA.request.get(`${API}/auth/me`)).json();
    const meB = await (await contextB.request.get(`${API}/auth/me`)).json();
    const createTxAs = (title: string) =>
      contextA.request.post(`${API}/workspaces/${wsA.id}/transactions/`, {
        data: {
          title,
          total_amount: '90.00',
          transaction_date: new Date().toISOString(),
          payers: [{ user_id: meA.id, amount: '90.00' }],
          splits: [
            { user_id: meA.id, split_method: 'equal', input_value: '0' },
            { user_id: meB.id, split_method: 'equal', input_value: '0' },
          ],
        },
      });

    const titleLive = `Jantar Tempo Real ${ts}`;
    expect((await createTxAs(titleLive)).ok()).toBeTruthy();
    await expect(pageB.getByText(titleLive)).toBeVisible({ timeout: 15_000 });

    // `close()` do WebSocketRoute devolve Promise, e o `for` abaixo descartava
    // essas promises: o teste seguia para o POST com os sockets possivelmente
    // ainda ABERTOS. O lançamento então chegava ao vivo em B e a asserção de
    // ausência reprovava — a mesma falha que este spec já tinha, só que agora
    // por falta de `await` em vez de por `setOffline`. Passava aqui e reprovava
    // no runner do CI, que é mais rápido: 2 de 9 execuções.
    // Antes de derrubar: a interceptação está mesmo de pé? Sem esta asserção, um
    // `routeWebSocket` que não casou a URL deixaria `socketsDeB` vazio, o
    // `close()` não fecharia nada, e o teste reprovaria lá embaixo culpando a
    // entrega ao vivo — quando a causa seria a queda que nunca aconteceu.
    expect(
      rotasAcionadas,
      'a rota de WebSocket nunca foi acionada — a interceptação não pegou o socket de B',
    ).toBeGreaterThan(0);
    expect(
      socketsDeB.size,
      `nenhum socket vivo de B para derrubar (rota acionada ${rotasAcionadas}x)`,
    ).toBeGreaterThan(0);

    quedaDeRede = true;
    await Promise.all([...socketsDeB].map((ws) => ws.close()));
    socketsDeB.clear();

    // A linha de base vem ANTES de criar o lançamento.
    //
    // Estava depois da espera por A renderizar, e isso deixava um buraco: entre
    // o POST e A aparecer na tela passam segundos, e uma busca de B nesse
    // intervalo não entrava na conta. O contador então dizia "B não buscou
    // nada" medindo o pedaço errado do tempo — e a investigação apontava para o
    // WebSocket quando a entrega tinha vindo por HTTP.
    const buscasAntes = buscasDeB;

    const titleOffline = `Offline ${ts}`;
    expect((await createTxAs(titleOffline)).ok()).toBeTruthy();

    // Ponto de sincronização, e não um `waitForTimeout`: espera A — que segue
    // ONLINE — renderizar o lançamento. Quando isso acontece, o evento
    // comprovadamente saiu do servidor e percorreu um caminho MAIS LONGO que o
    // de B (frame → invalidação → refetch → render). Só então faz sentido
    // afirmar que B não o tem.
    //
    // Sem esta espera a asserção seguinte não vale nada: `not.toBeVisible()`
    // resolve na PRIMEIRA checagem, e logo após o POST o lançamento ainda não
    // teria aparecido nem com o socket de B intacto. Verificado por
    // falsificação — desligando a queda de rede, o teste continuava verde.
    await expect(pageA.getByText(titleOffline)).toBeVisible({ timeout: 15_000 });
    // A e B correm em PARALELO: A renderizar primeiro é questão de milissegundos
    // e não diz nada sobre B. Provar uma ausência exige uma janela — esta é a
    // margem em que B, se o socket estivesse vivo, teria renderizado com folga
    // (o `titleLive` acima aparece em bem menos que isso).
    await pageB.waitForTimeout(3_000);

    // Antes de olhar a tela: B buscou lançamentos por HTTP nesta janela? Se
    // buscou, o lançamento chegou por um caminho que não é o WebSocket, e a
    // asserção visual abaixo estaria medindo outra coisa.
    expect(
      buscasDeB,
      `B buscou lançamentos por HTTP com o socket caído — o dado não veio do WS.
` +
        `URLs: ${urlsDeB.slice(buscasAntes).join(', ')}`,
    ).toBe(buscasAntes);

    await expect(
      pageB.getByText(titleOffline),
      `B mostrou o lançamento sem buscar nada por HTTP (rota WS acionada ${rotasAcionadas}x). ` +
        `Últimas URLs: ${urlsDeB.slice(-6).join(', ')}`,
    ).not.toBeVisible();

    // Religa a rede. O app reconecta sozinho (backoff exponencial com jitter,
    // 1s → 30s, que zera no `hello`), vê `hello.seq` à frente do último seq que
    // conhecia e faz resync completo — é esse caminho, e não a entrega ao vivo,
    // que a asserção abaixo prova. O timeout é folgado de propósito: a janela
    // acima já custou algumas tentativas de reconexão, e cada uma empurra o
    // backoff para cima.
    quedaDeRede = false;
    await expect(pageB.getByText(titleOffline)).toBeVisible({ timeout: 45_000 });

    // E o lançamento apareceu porque houve RESYNC, não por outro caminho: a
    // reconexão vê `hello.seq` à frente e invalida as queries, o que
    // obrigatoriamente gera busca HTTP. Sem esta asserção, "apareceu na tela"
    // não distinguiria resync de qualquer outra rebusca.
    expect(
      buscasDeB,
      'B não buscou lançamentos após reconectar — o resync não aconteceu',
    ).toBeGreaterThan(buscasAntes);

    await contextA.close();
    await contextB.close();
  });

  test('convite por link: usuário novo aceita pela UI e entra no workspace', async ({ browser }) => {
    test.setTimeout(120_000);
    const ts = Date.now();
    const contextA = await browser.newContext();
    const contextC = await browser.newContext();

    await registerAndLogin(contextA, { name: 'Alice Link', email: `link_a_${ts}@teste.com`, password: 'senha123' });
    const wsA = await defaultWorkspace(contextA);
    const linkWsName = `Via Link ${ts}`;
    await contextA.request.put(`${API}/workspaces/${wsA.id}`, { data: { name: linkWsName } });

    const linkRes = await contextA.request.post(`${API}/workspaces/${wsA.id}/invites/link`, {
      data: { role: 'member', expires_days: 7 },
    });
    expect(linkRes.ok()).toBeTruthy();
    const { token } = await linkRes.json();
    expect(token).toBeTruthy();

    await registerAndLogin(contextC, { name: 'Carla Link', email: `link_c_${ts}@teste.com`, password: 'senha123' });
    await defaultWorkspace(contextC);

    const pageC = await contextC.newPage();
    await pageC.goto(`/invite/${token}`);
    await pageC.getByRole('button', { name: 'Aceitar Convite' }).click();

    // Depois de aceitar, o workspace convidado aparece para Carla
    await pageC.goto('/');
    await expect(pageC.getByRole('heading', { name: 'Início' })).toBeVisible({ timeout: 15_000 });
    const wsListC = await (await contextC.request.get(`${API}/workspaces/`)).json();
    expect(wsListC.some((w: { name: string }) => w.name === linkWsName)).toBeTruthy();

    await contextA.close();
    await contextC.close();
  });
});
