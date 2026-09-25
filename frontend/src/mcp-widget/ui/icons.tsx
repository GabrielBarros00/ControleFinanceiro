/** @jsxImportSource preact */
/**
 * Ícones do componente: SVG embutido, traço de 1,6 px, 16 px por padrão.
 *
 * Nada de fonte de ícones nem de caracteres como "↗" ou "✓": no Windows eles
 * viram emoji colorido, e fonte externa a CSP vazia do recurso bloqueia.
 */
import type { JSX } from 'preact';

type Props = { size?: number; class?: string };

function Base({ size = 16, class: cls, children }: Props & { children: JSX.Element | JSX.Element[] }) {
  return (
    <svg
      aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class={cls}
    >
      {children}
    </svg>
  );
}

export const IconCard = (p: Props) => <Base {...p}><rect x="2.5" y="5" width="19" height="14" rx="2.5" /><path d="M2.5 10h19M6.5 15h3" /></Base>;
export const IconBank = (p: Props) => <Base {...p}><path d="M3 10 12 4l9 6M5 10v8M9.5 10v8M14.5 10v8M19 10v8M3 20h18" /></Base>;
export const IconWallet = (p: Props) => <Base {...p}><path d="M19 7V5.5A1.5 1.5 0 0 0 17.5 4h-12A2.5 2.5 0 0 0 3 6.5v11A2.5 2.5 0 0 0 5.5 20h13a2.5 2.5 0 0 0 2.5-2.5V9a2 2 0 0 0-2-2H5.5" /><circle cx="16.5" cy="13.5" r="1.2" /></Base>;
export const IconCalendar = (p: Props) => <Base {...p}><rect x="3" y="4.5" width="18" height="16" rx="2.5" /><path d="M3 9.5h18M8 3v3M16 3v3" /></Base>;
export const IconTag = (p: Props) => <Base {...p}><path d="M3 12.2V4.5A1.5 1.5 0 0 1 4.5 3h7.7l8.3 8.3a1.6 1.6 0 0 1 0 2.2l-6.9 6.9a1.6 1.6 0 0 1-2.2 0Z" /><circle cx="8" cy="8" r="1.3" /></Base>;
export const IconUsers = (p: Props) => <Base {...p}><circle cx="9" cy="8.5" r="3.2" /><path d="M3.5 19.5c.6-3 2.8-4.8 5.5-4.8s4.9 1.8 5.5 4.8" /><path d="M16 5.6a3 3 0 0 1 0 5.8M17.5 14.9c1.5.6 2.6 2 3 4.1" /></Base>;
export const IconReceipt = (p: Props) => <Base {...p}><path d="M6 3h12v18l-3-2-3 2-3-2-3 2Z" /><path d="M9 8h6M9 12h6" /></Base>;
export const IconClip = (p: Props) => <Base {...p}><path d="m20.5 11.5-8.2 8.2a5 5 0 0 1-7-7l8.8-8.8a3.3 3.3 0 0 1 4.7 4.7l-8.8 8.8a1.7 1.7 0 0 1-2.4-2.4l8-8" /></Base>;
export const IconPencil = (p: Props) => <Base {...p}><path d="M4 20h4L19.5 8.5a2.1 2.1 0 0 0-3-3L5 17v3Z" /><path d="m14.5 7.5 3 3" /></Base>;
export const IconTrash = (p: Props) => <Base {...p}><path d="M4 7h16M10 11v6M14 11v6M6 7l1 12.5A1.5 1.5 0 0 0 8.5 21h7a1.5 1.5 0 0 0 1.5-1.5L18 7M9 7V4.5h6V7" /></Base>;
export const IconUndo = (p: Props) => <Base {...p}><path d="M9 14 4 9l5-5" /><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11" /></Base>;
export const IconChevron = (p: Props) => <Base {...p}><path d="m9 6 6 6-6 6" /></Base>;
export const IconExpand = (p: Props) => <Base {...p}><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" /></Base>;
export const IconShrink = (p: Props) => <Base {...p}><path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7" /></Base>;
export const IconExternal = (p: Props) => <Base {...p}><path d="M14 4h6v6M20 4l-9 9M18 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10" /></Base>;
export const IconCheck = (p: Props) => <Base {...p}><path d="m5 12.5 4.5 4.5L19 7.5" /></Base>;
export const IconX = (p: Props) => <Base {...p}><path d="M6 6l12 12M18 6 6 18" /></Base>;
export const IconPlus = (p: Props) => <Base {...p}><path d="M12 5v14M5 12h14" /></Base>;
export const IconHistory = (p: Props) => <Base {...p}><path d="M3.5 12a8.5 8.5 0 1 0 2.5-6L3.5 8.5" /><path d="M3.5 4v4.5H8M12 7.5V12l3 2" /></Base>;
export const IconRepeat = (p: Props) => <Base {...p}><path d="m17 2.5 3 3-3 3" /><path d="M4 11.5v-1a5 5 0 0 1 5-5h11M7 21.5l-3-3 3-3" /><path d="M20 12.5v1a5 5 0 0 1-5 5H4" /></Base>;
export const IconChart = (p: Props) => <Base {...p}><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></Base>;
export const IconAlert = (p: Props) => <Base {...p}><path d="M12 9v4M12 17h.01" /><path d="M10.3 3.9 2.4 17.5A2 2 0 0 0 4.1 20.5h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" /></Base>;
export const IconArrowRight = (p: Props) => <Base {...p}><path d="M5 12h14M13 6l6 6-6 6" /></Base>;
export const IconSparkle = (p: Props) => <Base {...p}><path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6" /></Base>;
export const IconInbox = (p: Props) => <Base {...p}><path d="M3 13.5 5.8 5.2A1.5 1.5 0 0 1 7.2 4h9.6a1.5 1.5 0 0 1 1.4 1.2L21 13.5V19a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 19Z" /><path d="M3 13.5h5l1.5 2.5h5l1.5-2.5h5" /></Base>;
export const IconUpload = (p: Props) => <Base {...p}><path d="M12 16V4M7 9l5-5 5 5M4 16v2.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V16" /></Base>;
