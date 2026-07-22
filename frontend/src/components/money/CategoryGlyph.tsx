import {
  Utensils,
  ShoppingCart,
  Car,
  Home,
  HeartPulse,
  Gamepad2,
  GraduationCap,
  Repeat,
  Tag,
  type LucideIcon,
} from 'lucide-react';
import { cn } from '@/lib/utils';

/*
 * CategoryGlyph — chip redondo com o ícone da categoria tingido na cor dela
 * (docs/frontend-redesign/05 §3). Dá escaneabilidade ao extrato (vs. o texto
 * UPPERCASE 10px de antes). Mapeia os `icon` que o back já envia para lucide.
 */
const ICONS: Record<string, LucideIcon> = {
  utensils: Utensils,
  'shopping-cart': ShoppingCart,
  car: Car,
  home: Home,
  'heart-pulse': HeartPulse,
  'gamepad-2': Gamepad2,
  'graduation-cap': GraduationCap,
  repeat: Repeat,
  tag: Tag,
};

export interface CategoryLike {
  name?: string | null;
  color?: string | null;
  icon?: string | null;
}

const SIZE = {
  sm: 'h-8 w-8 [&_svg]:h-4 [&_svg]:w-4',
  md: 'h-10 w-10 [&_svg]:h-5 [&_svg]:w-5',
};

export function CategoryGlyph({
  category,
  size = 'sm',
  className,
}: {
  category?: CategoryLike | null;
  size?: 'sm' | 'md';
  className?: string;
}) {
  const Icon = (category?.icon && ICONS[category.icon]) || Tag;
  const color = category?.color || undefined;
  // tint = cor da categoria a ~12% (hex 8-dígitos). Sem cor, cai no neutro do tema.
  const style = color ? { color, backgroundColor: `${color}1f` } : undefined;
  return (
    <span
      aria-hidden
      style={style}
      className={cn(
        'flex shrink-0 items-center justify-center rounded-full',
        !color && 'bg-muted text-muted-foreground',
        SIZE[size],
        className,
      )}
    >
      <Icon />
    </span>
  );
}
