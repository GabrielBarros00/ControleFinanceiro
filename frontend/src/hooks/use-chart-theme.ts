import * as React from 'react';

/*
 * useChartTheme — lê as cores do tema atual (CSS vars) para o Recharts, e
 * reage à troca claro/escuro (observa a classe do <html>). Resolve o B3: sem
 * isso, tooltip/grid ficam com cores fixas do escuro e quebram no tema claro.
 */
export interface ChartTheme {
  grid: string;
  axis: string;
  tooltipBg: string;
  tooltipBorder: string;
  tooltipText: string;
  /** paleta de séries/categorias (--chart-1..6) */
  series: string[];
}

const SERIES_VARS = ['--chart-1', '--chart-2', '--chart-3', '--chart-4', '--chart-5', '--chart-6'];

function readVar(name: string, fallback = ''): string {
  if (typeof window === 'undefined') return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

function compute(): ChartTheme {
  return {
    grid: readVar('--chart-grid', 'rgba(0,0,0,0.08)'),
    axis: readVar('--muted-foreground', '#888'),
    tooltipBg: readVar('--popover', readVar('--card', '#fff')),
    tooltipBorder: readVar('--border', 'rgba(0,0,0,0.1)'),
    tooltipText: readVar('--popover-foreground', readVar('--foreground', '#111')),
    series: SERIES_VARS.map((v) => readVar(v)),
  };
}

export function useChartTheme(): ChartTheme {
  const [theme, setTheme] = React.useState<ChartTheme>(compute);

  React.useEffect(() => {
    setTheme(compute());
    const observer = new MutationObserver(() => setTheme(compute()));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  return theme;
}
