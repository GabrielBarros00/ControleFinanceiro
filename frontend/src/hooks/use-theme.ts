import * as React from 'react';

type Theme = 'light' | 'dark' | 'system';

export function useTheme() {
  const [theme, setThemeState] = React.useState<Theme>(() => {
    return (localStorage.getItem('theme') as Theme) || 'system';
  });

  const setTheme = (theme: Theme) => {
    localStorage.setItem('theme', theme);
    setThemeState(theme);
  };

  React.useEffect(() => {
    const root = window.document.documentElement;
    root.classList.remove('light', 'dark');

    if (theme === 'system') {
      const systemTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
      root.classList.add(systemTheme);
      return;
    }

    root.classList.add(theme);
  }, [theme]);

  return { theme, setTheme };
}
