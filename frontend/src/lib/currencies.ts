// Moedas suportadas no seletor. `ptax: true` = cotada oficialmente pelo BCB
// (taxa que bate com o cartão). As demais usam fonte de mercado (referência).
// A lista é curada (majores + comuns de viagem); o backend aceita qualquer
// código que a fonte de mercado (fawazahmed0, 200+) tenha.
export interface CurrencyOption {
  code: string;
  name: string;
  ptax?: boolean;
}

export const CURRENCIES: CurrencyOption[] = [
  { code: 'BRL', name: 'Real brasileiro' },
  // Majores — PTAX oficial
  { code: 'USD', name: 'Dólar americano', ptax: true },
  { code: 'EUR', name: 'Euro', ptax: true },
  { code: 'GBP', name: 'Libra esterlina', ptax: true },
  { code: 'JPY', name: 'Iene japonês', ptax: true },
  { code: 'CHF', name: 'Franco suíço', ptax: true },
  { code: 'CAD', name: 'Dólar canadense', ptax: true },
  { code: 'AUD', name: 'Dólar australiano', ptax: true },
  { code: 'DKK', name: 'Coroa dinamarquesa', ptax: true },
  { code: 'NOK', name: 'Coroa norueguesa', ptax: true },
  { code: 'SEK', name: 'Coroa sueca', ptax: true },
  // Comuns de viagem / mundo — referência de mercado
  { code: 'ARS', name: 'Peso argentino' },
  { code: 'CLP', name: 'Peso chileno' },
  { code: 'UYU', name: 'Peso uruguaio' },
  { code: 'PYG', name: 'Guarani paraguaio' },
  { code: 'BOB', name: 'Boliviano' },
  { code: 'COP', name: 'Peso colombiano' },
  { code: 'PEN', name: 'Sol peruano' },
  { code: 'MXN', name: 'Peso mexicano' },
  { code: 'CNY', name: 'Yuan chinês' },
  { code: 'HKD', name: 'Dólar de Hong Kong' },
  { code: 'THB', name: 'Baht tailandês' },
  { code: 'INR', name: 'Rúpia indiana' },
  { code: 'IDR', name: 'Rupia indonésia' },
  { code: 'MYR', name: 'Ringgit malaio' },
  { code: 'SGD', name: 'Dólar de Singapura' },
  { code: 'KRW', name: 'Won sul-coreano' },
  { code: 'PHP', name: 'Peso filipino' },
  { code: 'VND', name: 'Dong vietnamita' },
  { code: 'ZAR', name: 'Rand sul-africano' },
  { code: 'TRY', name: 'Lira turca' },
  { code: 'AED', name: 'Dirham dos Emirados' },
  { code: 'ILS', name: 'Novo shekel israelense' },
  { code: 'EGP', name: 'Libra egípcia' },
  { code: 'NZD', name: 'Dólar neozelandês' },
  { code: 'RUB', name: 'Rublo russo' },
  { code: 'PLN', name: 'Zloty polonês' },
  { code: 'CZK', name: 'Coroa tcheca' },
  { code: 'HUF', name: 'Florim húngaro' },
];

export function currencyName(code: string): string {
  return CURRENCIES.find((c) => c.code === code)?.name ?? code;
}
