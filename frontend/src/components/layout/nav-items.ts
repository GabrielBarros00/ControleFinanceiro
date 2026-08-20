import {
  LayoutDashboard,
  Receipt,
  CreditCard,
  Landmark,
  BarChart3,
  ReceiptText,
  Repeat,
  Users,
  FileUp,
  Settings,
  ShieldCheck,
  Wallet,
  Scale,
  type LucideIcon,
} from 'lucide-react';

/*
 * Fonte única de navegação (docs/frontend-redesign/04).
 *
 * Duas camadas desde o ADR 0020, e a separação é o ponto:
 *
 * - **Pessoal** — global e seu, sem espaço no caminho. Responde "como está o MEU
 *   mês, somando tudo".
 * - **Compartilhado** — `/w/:id/...`. Responde "como está ESTE espaço".
 *
 * Antes tudo era `/income`, `/reports`, `/debts`, e o significado dependia de um
 * `currentWorkspaceId` invisível no `localStorage`: o mesmo link abria em espaços
 * diferentes para pessoas diferentes.
 *
 * ## Vocabulário (decidido nesta rodada)
 *
 * A interface falava QUATRO línguas para duas ideias: "Meu / Global / Seus /
 * pessoal" de um lado, "workspace / casa / espaço / o nome dele" do outro. Pior,
 * havia uma colisão literal: toda conta nasce dona de um espaço chamado "Meu
 * Workspace" (backend/app/api/routes/auth.py), enquanto a seção chamada "Meu"
 * significava justamente o que NÃO está em espaço nenhum.
 *
 * Agora vale um par só: **Pessoal** × **Compartilhado**, e a palavra para o
 * contêiner é **espaço** — em toda a interface. Código, rotas `/w/:id` e o
 * contrato da API seguem dizendo `workspace`; só o que a pessoa lê mudou.
 */
export interface NavItem {
  icon: LucideIcon;
  label: string;
  to: string;
}

export interface NavSection {
  /** A palavra do escopo — "Pessoal", "Compartilhado", "Site". Vai em caixa alta. */
  label: string;
  /**
   * O NOME do espaço, separado do rótulo de propósito: junto dele herdava o
   * `uppercase` do cabeçalho e "Casa da Praia" virava "CASA DA PRAIA", que se
   * lê como mais uma palavra do rótulo em vez de um nome próprio.
   */
  subject?: string;
  /** Linha de apoio — quem vê o quê ("Só você vê", "4 pessoas"). Opcional. */
  hint?: string;
  items: NavItem[];
}

/** Tudo que é da PESSOA — não depende de espaço nenhum (ADR 0021).
 *
 * Cartões, Financiamentos e Rendas mudaram de lado na Onda 5. "Rendas" chegou a
 * viver numa seção chamada "Compartilhado", o que anunciava exatamente o oposto
 * da verdade: salário é o dado mais privado do sistema.
 */
export const GLOBAL_SECTION: NavSection = {
  label: 'Pessoal',
  hint: 'Só você vê',
  items: [
    // "Visão global" era o pior rótulo do app: para quem lê, "global" sugere "de
    // todos" — e significa o contrário, "só meu, somando meus espaços".
    { icon: LayoutDashboard, label: 'Seu mês', to: '/overview' },
    // Logo abaixo do Seu mês porque é a continuação dele: lá está o que já saiu
    // do caixa, aqui o que ainda vai sair (ADR 0029). "Contas a pagar" e não "A
    // pagar": este último já é o rótulo de um número do Seu mês — o saldo com
    // outras PESSOAS —, e dois nomes iguais para coisas diferentes foi
    // exatamente o problema que "Compromissos" resolveu.
    { icon: ReceiptText, label: 'Contas a pagar', to: '/me/payables' },
    { icon: Wallet, label: 'Rendas', to: '/me/income' },
    { icon: CreditCard, label: 'Cartões', to: '/me/cards' },
    { icon: Landmark, label: 'Financiamentos', to: '/me/financing' },
    // Cartões e financiamentos a vencer. Eixo diferente de "Acertos entre
    // pessoas" — e agora há UM item com este nome, não dois.
    { icon: Scale, label: 'Compromissos', to: '/me/commitments' },
    // Vizinho de Compromissos porque os dois respondem "o que eu devo": um a
    // bancos, outro a pessoas. O rótulo é "SEUS acertos" — o item do espaço
    // continua sendo "Acertos", e dois itens com o mesmo nome foi exatamente o
    // problema que "Compromissos" resolveu. Mesmo par de "Seus relatórios".
    { icon: Users, label: 'Seus acertos', to: '/me/settlements' },
    // Renda × consumo do PERÍODO, somando todos os espaços. Os Relatórios de
    // `/w/:id/reports` continuam existindo e são outro eixo: quanto ESTE espaço
    // gastou. Depois do ADR 0021 eles nem podem mais falar de renda.
    { icon: BarChart3, label: 'Seus relatórios', to: '/me/reports' },
    // As LINHAS por trás dos totais. O Seu mês sabia dizer "saiu R$ 4.200"
    // e de que origem, mas não tinha por onde explicar cada número.
    { icon: Receipt, label: 'Extrato', to: '/me/ledger' },
    // Perfil, senha, contas de pagamento, tema e moeda de relatório. Ficavam
    // presos em `/w/:id/settings`, inalcançáveis para quem não tivesse um
    // espaço válido — e nenhum deles pertence a espaço nenhum.
    { icon: Settings, label: 'Suas configurações', to: '/me/settings' },
  ],
};

/** Administração do SITE (ADR 0026) — só aparece para quem tem o papel.
 *
 * Terceira camada, e a separação segue a mesma lógica das outras duas: "Pessoal"
 * é a pessoa, o espaço é o grupo, e isto é o SERVIDOR. Misturá-la em
 * "Configurações" faria parecer que administrar o site é uma preferência do
 * usuário — e faria o item sumir para quem não tem espaço válido.
 */
export const PLATFORM_SECTION: NavSection = {
  label: 'Site',
  hint: 'Administração da plataforma',
  items: [
    { icon: ShieldCheck, label: 'Administração', to: '/admin' },
  ],
};

/**
 * Navegação DE UM espaço. Sem id, devolve só a camada pessoal.
 *
 * `isPlatformAdmin` é opcional para não quebrar os chamadores que só conhecem o
 * espaço — e porque esconder o item é conveniência, não tranca: quem barra é
 * `require_platform_role` no servidor.
 *
 * `nome` e `hint` alimentam o rótulo da seção compartilhada. São opcionais porque
 * nem todo chamador tem a lista de espaços à mão (os testes, por exemplo); sem
 * eles a seção se chama "Compartilhado" e pronto.
 *
 * O `hint` chega PRONTO em vez de ser montado aqui: desde que ele diz de quem é o
 * espaço, depende de quem está logado (`De você`), e o mapa de navegação não tem
 * por que conhecer a sessão. Quem chama usa `rotuloDeEspaco`.
 */
export function navSections(
  workspaceId: number | null,
  isPlatformAdmin = false,
  espaco?: { nome?: string | null; hint?: string },
): NavSection[] {
  const plataforma = isPlatformAdmin ? [PLATFORM_SECTION] : [];
  if (!workspaceId) return [GLOBAL_SECTION, ...plataforma];
  const w = (path: string) => `/w/${workspaceId}${path}`;
  return [
    GLOBAL_SECTION,
    {
      label: 'Compartilhado',
      // O NOME do espaço é o que desfaz a ambiguidade dos pares homônimos:
      // "Acertos" sob "Compartilhado · Casa da Praia" não se confunde com
      // "Seus acertos" sob "Pessoal".
      subject: espaco?.nome ?? undefined,
      // Um espaço de um membro só não é compartilhado com ninguém, e dizer que é
      // seria mentira — a mesma que fez "Rendas" morar em "Compartilhado" um dia.
      hint: espaco?.hint,
      items: [
        { icon: LayoutDashboard, label: 'Painel', to: w('') },
        { icon: Receipt, label: 'Lançamentos', to: w('/transactions') },
        // Vizinho de Lançamentos: é o mesmo objeto visto por outro ângulo — o
        // que ainda não foi pago. O par homônimo em "Pessoal" soma as casas;
        // este é só desta.
        { icon: ReceiptText, label: 'Contas a pagar', to: w('/payables') },
        { icon: Repeat, label: 'Recorrência', to: w('/recurring') },
        { icon: BarChart3, label: 'Relatórios', to: w('/reports') },
        // "Dívidas" era ambíguo com o endividamento bancário: aqui é quem deve a
        // quem ENTRE MEMBROS, que se resolve com um acerto.
        { icon: Users, label: 'Acertos', to: w('/debts') },
        // Importar e Configurações moravam numa seção "Sistema" que os fazia
        // parecer globais. São do espaço: o CSV entra NESTE espaço e as
        // configurações são as DELE (as suas ficam em Pessoal).
        { icon: FileUp, label: 'Importar', to: w('/import') },
        { icon: Settings, label: 'Configurações', to: w('/settings') },
      ],
    },
    // Por último: administrar o servidor é o que menos se faz no dia a dia, e
    // vem depois do que pertence ao espaço.
    ...plataforma,
  ];
}

/** "Só você" / "2 pessoas" — a linha de apoio da seção compartilhada. */
export function rotuloDeMembros(membros?: number | null): string | undefined {
  if (membros == null) return undefined;
  return membros <= 1 ? 'Só você' : `${membros} pessoas`;
}

/** O mínimo que um espaço precisa expor para ser rotulado. */
export interface EspacoRotulavel {
  owner_name?: string | null;
  owner_user_id?: number | null;
  member_count?: number | null;
}

/**
 * "De Ana Souza · 3 pessoas" — de quem é o espaço, e com quantos.
 *
 * A API já devolvia `owner_name`/`owner_user_id` e nenhuma tela lia: a lista só
 * dizia "3 pessoas", e quem participa de dois espaços com nomes parecidos não
 * tinha como saber qual é o da Ana e qual é o do trabalho. O dono é a primeira
 * coisa que identifica um espaço compartilhado.
 *
 * Sem `owner_name` (resposta antiga em cache, ou espaço sem membership `owner`)
 * cai no rótulo de membros de antes — nunca renderiza "De undefined".
 */
export function rotuloDeEspaco(
  espaco?: EspacoRotulavel | null,
  usuarioId?: number | null,
): string | undefined {
  if (!espaco) return undefined;

  const souODono = espaco.owner_user_id != null && espaco.owner_user_id === usuarioId;
  const dono = souODono
    ? 'De você'
    : espaco.owner_name
      ? `De ${espaco.owner_name}`
      : undefined;
  if (!dono) return rotuloDeMembros(espaco.member_count);

  // Minúsculo depois do "·": é continuação da mesma frase, não um segundo rótulo.
  const membros =
    espaco.member_count == null
      ? undefined
      : espaco.member_count <= 1
        ? 'só você'
        : `${espaco.member_count} pessoas`;
  return membros ? `${dono} · ${membros}` : dono;
}

export function navFlat(workspaceId: number | null, isPlatformAdmin = false): NavItem[] {
  return navSections(workspaceId, isPlatformAdmin).flatMap((s) => s.items);
}

/**
 * Qual item da navegação está ativo para o caminho atual.
 *
 * Precisa ser calculado sobre a LISTA, não item a item: o Painel é `/w/1` e
 * `/w/1/reports` começa com ele, então um teste de prefixo por item marcava os
 * dois ao mesmo tempo — o usuário via "Painel" e "Relatórios" acesos juntos.
 * Vence o item de caminho mais LONGO que casa, o que dá match exato para o
 * Painel e prefixo para as subrotas de cada seção.
 *
 * `/me/settings` e `/me/settlements` só não colidem porque o teste é `=== to` ou
 * `startsWith(to + '/')`. Um `startsWith` cru acenderia Configurações ao abrir
 * Seus acertos — não "simplifique" para isso.
 */
export function activeNavPath(
  pathname: string,
  workspaceId: number | null,
  isPlatformAdmin = false,
): string | null {
  const candidatos = navFlat(workspaceId, isPlatformAdmin)
    .map((i) => i.to)
    .filter((to) => pathname === to || pathname.startsWith(`${to}/`));
  if (candidatos.length === 0) return null;
  return candidatos.reduce((a, b) => (b.length > a.length ? b : a));
}

/**
 * Slots primários da bottom-nav mobile; o restante vai no sheet "Mais".
 *
 * Os caminhos têm de EXISTIR em `navFlat` — a `BottomNav` casa por igualdade e
 * descarta o que não encontra, em silêncio. Era o caso de `/w/:id/cards`: os
 * cartões viraram `/me/cards` no ADR 0021, o item nunca casava e o terceiro slot
 * simplesmente sumia da barra.
 */
export function mobilePrimaryPaths(workspaceId: number | null): string[] {
  if (!workspaceId) return ['/overview', '/me/cards'];
  return ['/overview', `/w/${workspaceId}/transactions`, '/me/cards'];
}
