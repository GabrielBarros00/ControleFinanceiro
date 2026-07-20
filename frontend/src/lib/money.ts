export const formatCurrency = (value: number | string): string => {
  const amount = typeof value === 'string' ? parseFloat(value.replace(/\D/g, '')) / 100 : value;
  if (isNaN(amount)) return 'R$ 0,00';
  
  return new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency: 'BRL',
  }).format(amount);
};

export const parseCurrency = (value: string): number => {
  const digits = value.replace(/\D/g, '');
  return parseFloat(digits) / 100;
};

export const maskCurrency = (value: string): string => {
  const digits = value.replace(/\D/g, '');
  const amount = parseInt(digits) || 0;
  
  return new Intl.NumberFormat('pt-BR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount / 100);
};
