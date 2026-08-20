import { baseURL } from '@/api/client';

/*
 * Foto de perfil — a URL, e a redução antes de subir.
 *
 * Um lugar só monta a URL: ela depende do `baseURL` do cliente (que muda entre
 * desenvolvimento e produção) e do token de cache, e espalhar essa concatenação
 * por sete componentes seria sete chances de esquecer o `?v=`.
 */

/** Máximo de 1 MiB no servidor — aqui a imagem já sai com dezenas de KB. */
export const AVATAR_LADO = 256;
export const AVATAR_ACCEPT = 'image/jpeg,image/png,image/webp';

/**
 * Endereço dos bytes da foto de alguém, ou `null` para quem não tem.
 *
 * `?v=` é o hash do conteúdo: a resposta vem com `Cache-Control: immutable`, e
 * é só por causa deste parâmetro que trocar a foto muda a URL — sem ele, a
 * imagem antiga ficaria no cache do navegador por um ano.
 */
export function urlDoAvatar(
  userId: number | null | undefined,
  version: string | null | undefined,
): string | null {
  if (!userId || !version) return null;
  return `${baseURL}/auth/users/${userId}/avatar?v=${encodeURIComponent(version)}`;
}

/**
 * Reduz a imagem escolhida para um quadrado de 256px antes de subir.
 *
 * Feito no NAVEGADOR de propósito. A alternativa seria redimensionar no
 * servidor, o que exigiria Pillow — uma dependência nova de backend, com
 * compilação e uma passada pelo `pip-compile` do CI — para resolver um problema
 * que o `<canvas>` já resolve de graça. O ganho é dobrado: a foto de 4 MB da
 * câmera do celular nunca sai do aparelho, e o que trafega e fica guardado são
 * dezenas de KB em vez de megabytes.
 *
 * Recorta pelo CENTRO em vez de espremer: o avatar é redondo, e uma foto
 * retangular achatada num quadrado deforma o rosto.
 *
 * Sai sempre em WebP, que é um dos três tipos que o servidor aceita e o mais
 * econômico dos três. Se o navegador não souber gerar WebP, `toBlob` devolve
 * PNG — também aceito.
 */
export async function reduzirImagem(file: File): Promise<Blob> {
  const bitmap = await carregarBitmap(file);
  try {
    const lado = Math.min(bitmap.width, bitmap.height);
    const canvas = document.createElement('canvas');
    canvas.width = AVATAR_LADO;
    canvas.height = AVATAR_LADO;
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('Não foi possível preparar a imagem neste navegador.');
    ctx.drawImage(
      bitmap,
      (bitmap.width - lado) / 2,
      (bitmap.height - lado) / 2,
      lado,
      lado,
      0,
      0,
      AVATAR_LADO,
      AVATAR_LADO,
    );
    return await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob(
        (blob) => (blob ? resolve(blob) : reject(new Error('Não foi possível processar a imagem.'))),
        'image/webp',
        0.85,
      );
    });
  } finally {
    if ('close' in bitmap) bitmap.close();
  }
}

/**
 * `createImageBitmap` quando existe, `<img>` quando não.
 *
 * O fallback não é zelo com navegador antigo: o jsdom dos testes não implementa
 * `createImageBitmap`, e sem o caminho alternativo qualquer teste que exercite a
 * troca de foto morreria numa API ausente em vez de exercitar o fluxo.
 */
async function carregarBitmap(file: File): Promise<ImageBitmap | HTMLImageElement> {
  if (typeof createImageBitmap === 'function') {
    return createImageBitmap(file);
  }
  const url = URL.createObjectURL(file);
  try {
    return await new Promise<HTMLImageElement>((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error('Arquivo de imagem inválido.'));
      img.src = url;
    });
  } finally {
    URL.revokeObjectURL(url);
  }
}
