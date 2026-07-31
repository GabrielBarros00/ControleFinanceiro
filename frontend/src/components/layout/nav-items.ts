import {
  LayoutDashboard,
  Receipt,
  CreditCard,
  Landmark,
  BarChart3,
  Repeat,
  Users,
  FileUp,
  Settings,
  Wallet,
  Scale,
  type LucideIcon,
} from 'lucide-react';

/*
 * Fonte única de navegação (docs/frontend-redesign/04).
 *
 * Duas camadas desde o ADR 0020, e a separação é o ponto:
 *
 * - **Meu** — global e pessoal, sem workspace no caminho. Responde "como está o
 *   MEU mês, somando tudo".
 * - **Workspace** — `/w/:id/...`. Responde "como está ESTA casa".
 *
 * Antes tudo era `/income`, `/reports`, `/debts`, e o significado dependia de um
 * `currentWorkspaceId` invisível no `localStorage`: o mesmo link abria em casas
 * diferentes para pessoas diferentes.
 */
export interface NavItem {
  icon: LucideIcon;
  label: string;
  to: string;
}

export interface NavSection {
  label: string;
  items: NavItem[];
}

/** Tudo que é da PESSOA — não depende de workspace nenhum (ADR 0021).
 *
 * Cartões, Financiamentos e Rendas mudaram de lado na Onda 5. "Rendas" chegou a
 * viver numa seção chamada "Compartilhado", o que anunciava exatamente o oposto
 * da verdade: salário é o dado mais privado do sistema.
 */
export const GLOBAL_SECTION: NavSection = {
  label: 'Meu',
  items: [
    { icon: LayoutDashboard, label: 'Visão global', to: '/overview' },
    { icon: Wallet, label: 'Rendas', to: '/me/income' },
    { icon: CreditCard, label: 'Cartões', to: '/me/cards' },
    { icon: Landmark, label: 'Financiamentos', to: '/me/financing' },
    // Cartões e financiamentos a vencer. Eixo diferente de "Acertos entre
    // pessoas" — e agora há UM item com este nome, não dois.
    { icon: Scale, label: 'Compromissos', to: '/me/commitments' },
    // Renda × consumo do PERÍODO, somando todas as casas. Os Relatórios de
    // `/w/:id/reports` continuam existindo e são outro eixo: quanto ESTA casa
    // gastou. Depois do ADR 0021 eles nem podem mais falar de renda.
    { icon: BarChart3, label: 'Seus relatórios', to: '/me/reports' },
    // Perfil, senha, contas de pagamento, tema e moeda de relatório. Ficavam
    // presos em `/w/:id/settings`, inalcançáveis para quem não tivesse um
    // workspace válido — e nenhum deles pertence a workspace nenhum.
    { icon: Settings, label: 'Suas configurações', to: '/me/settings' },
  ],
};

/** Navegação DE UM workspace. Sem id, devolve só a camada pessoal. */
export function navSections(workspaceId: number | null): NavSection[] {
  if (!workspaceId) return [GLOBAL_SECTION];
  const w = (path: string) => `/w/${workspaceId}${path}`;
  return [
    GLOBAL_SECTION,
    {
      label: 'Dia a dia',
      items: [
        { icon: LayoutDashboard, label: 'Painel', to: w('') },
        { icon: Receipt, label: 'Lançamentos', to: w('/transactions') },
        { icon: Repeat, label: 'Recorrência', to: w('/recurring') },
        { icon: BarChart3, label: 'Relatórios', to: w('/reports') },
        // "Dívidas" era ambíguo com o endividamento bancário: aqui é quem deve a
        // quem ENTRE MEMBROS, que se resolve com um acerto.
        { icon: Users, label: 'Acertos', to: w('/debts') },
      ],
    },
    {
      label: 'Sistema',
      items: [
        { icon: FileUp, label: 'Importar', to: w('/import') },
        { icon: Settings, label: 'Configurações', to: w('/settings') },
      ],
    },
  ];
}

export function navFlat(workspaceId: number | null): NavItem[] {
  return navSections(workspaceId).flatMap((s) => s.items);
}

/**
 * Qual item da navegação está ativo para o caminho atual.
 *
 * Precisa ser calculado sobre a LISTA, não item a item: o Painel é `/w/1` e
 * `/w/1/reports` começa com ele, então um teste de prefixo por item marcava os
 * dois ao mesmo tempo — o usuário via "Painel" e "Relatórios" acesos juntos.
 * Vence o item de caminho mais LONGO que casa, o que dá match exato para o
 * Painel e prefixo para as subrotas de cada seção.
 */
export function activeNavPath(pathname: string, workspaceId: number | null): string | null {
  const candidatos = navFlat(workspaceId)
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
