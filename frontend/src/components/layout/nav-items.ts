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
 * Fonte única de navegação (docs/frontend-redesign/04). Usada pela Sidebar
 * (desktop, agrupada) e pela BottomNav (mobile). Todos os destinos atuais
 * continuam alcançáveis — só reorganizados em seções.
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

export const NAV_SECTIONS: NavSection[] = [
  {
    label: 'Dia a dia',
    items: [
      { icon: LayoutDashboard, label: 'Início', to: '/' },
      { icon: Receipt, label: 'Lançamentos', to: '/transactions' },
      { icon: Repeat, label: 'Recorrência', to: '/recurring' },
      { icon: BarChart3, label: 'Relatórios', to: '/reports' },
    ],
  },
  {
    label: 'Crédito & metas',
    items: [
      { icon: CreditCard, label: 'Cartões', to: '/cards' },
      { icon: Landmark, label: 'Financiamentos', to: '/financing' },
      { icon: Scale, label: 'Endividamento', to: '/liabilities' },
    ],
  },
  {
    label: 'Compartilhado',
    items: [
      { icon: Wallet, label: 'Rendas', to: '/income' },
      { icon: Users, label: 'Dívidas', to: '/debts' },
    ],
  },
  {
    label: 'Sistema',
    items: [
      { icon: FileUp, label: 'Importar', to: '/import' },
      { icon: Settings, label: 'Configurações', to: '/settings' },
    ],
  },
];

export const NAV_FLAT: NavItem[] = NAV_SECTIONS.flatMap((s) => s.items);

// Slots primários da bottom-nav mobile; o restante vai no sheet "Mais".
export const MOBILE_PRIMARY_PATHS = ['/', '/transactions', '/cards'];
