/**
 * Copiar para a área de transferência sem mentir sobre o resultado.
 *
 * Existe por dois motivos, e o segundo é o que importa neste projeto:
 *
 * 1. `navigator.clipboard.writeText` devolve uma Promise que REJEITA (aba sem
 *    foco, permissão negada). Chamá-la sem `await` e mostrar "Link copiado" em
 *    seguida produz um aviso de rejeição não tratada no console e uma mensagem
 *    de sucesso para uma coisa que não aconteceu.
 *
 * 2. `navigator.clipboard` **não existe** fora de um contexto seguro — e o
 *    "Cenário B" do SETUP.md é exatamente isso: `http://192.168.x.x` numa rede
 *    local, sem TLS. Nesse deploy, todo botão "Copiar link" do sistema era um
 *    botão que não fazia nada e dizia que tinha feito. Daí o recuo para
 *    `execCommand('copy')`, que é obsoleto e continua sendo a única coisa que
 *    funciona ali.
 *
 * Devolve se copiou de verdade. Quem chama decide a mensagem — e agora tem como
 * escolher a certa.
 */
export async function copiarTexto(texto: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(texto);
      return true;
    }
  } catch {
    // Cai no recuo abaixo: a API existe mas recusou (foco, permissão).
  }

  try {
    const area = document.createElement('textarea');
    area.value = texto;
    // Fora da tela e sem rolagem: `execCommand` exige que o elemento esteja no
    // documento e selecionado, e um textarea visível piscaria na página.
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.top = '-9999px';
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(area);
    return ok;
  } catch {
    return false;
  }
}
