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

/** Seções que não dependem de workspace nenhum. */
export const GLOBAL_SECTION: NavSection = {
  label: 'Meu',
  items: [
    { icon: LayoutDashboard, label: 'Início', to: '/overview' },
    // "Compromissos financeiros" (antes "Endividamento"): cartões e
    // financiamentos a vencer. Eixo diferente de "Acertos entre pessoas".
    { icon: Scale, label: 'Compromissos', to: '/me/commitments' },
  ],
};

/** Navegação DE UM workspace. Sem id, devolve só a camada global. */
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
      ],
    },
    {
      label: 'Crédito & metas',
      items: [
        { icon: CreditCard, label: 'Cartões', to: w('/cards') },
        { icon: Landmark, label: 'Financiamentos', to: w('/financing') },
        { icon: Scale, label: 'Compromissos', to: w('/liabilities') },
      ],
    },
    {
      label: 'Compartilhado',
      items: [
        { icon: Wallet, label: 'Rendas', to: w('/income') },
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

/** Slots primários da bottom-nav mobile; o restante vai no sheet "Mais". */
export function mobilePrimaryPaths(workspaceId: number | null): string[] {
  if (!workspaceId) return ['/overview'];
  return ['/overview', `/w/${workspaceId}/transactions`, `/w/${workspaceId}/cards`];
}
