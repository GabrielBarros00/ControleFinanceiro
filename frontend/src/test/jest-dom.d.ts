/*
 * Religa os matchers do `@testing-library/jest-dom` ao `expect` do Vitest.
 *
 * Até o Vitest 4 isto não era preciso: `Assertion` tinha UM parâmetro de tipo
 * (`Assertion<T = any>`) e os tipos do jest-dom encaixavam sozinhos. O Vitest 5
 * mudou a assinatura para `Assertion<R extends void | Promise<void>, T>` — o
 * primeiro parâmetro passou a ser o RETORNO, para `expect.poll`/`rejects`
 * devolverem `Promise<void>` encadeável. Com as listas de parâmetros
 * diferentes, o `declare module 'vitest'` que o jest-dom 7.0.1 traz em
 * `types/vitest.d.ts` deixa de mesclar (a fusão de interfaces exige parâmetros
 * IDÊNTICOS), e os 11 matchers somem dos tipos: 454 erros TS2339
 * ("Property 'toBeInTheDocument' does not exist") em 38 arquivos de teste.
 *
 * O sintoma é só de tipo — em tempo de execução os matchers continuam
 * registrados pelo `import '@testing-library/jest-dom'` do setup, e a suíte
 * passa inteira mesmo com o `tsc` vermelho. Por isso o gate que pega isto é o
 * `npm run typecheck`, não o `vitest run`.
 *
 * A correção NÃO é mexer em `Assertion`: o Vitest 5 publica
 * `interface Matchers<R, T> {}` vazia exatamente como ponto de extensão para
 * matchers de terceiros, e `Assertion` a estende. Estendendo `Matchers`, os
 * matchers chegam a `expect(...)`, a `.not`, a `.resolves`/`.rejects` e a
 * `expect.poll` de uma vez só.
 *
 * Os parâmetros abaixo repetem LETRA POR LETRA os do Vitest 5 (incluindo o
 * `extends void | Promise<void>` e os dois padrões). Divergir de novo faz a
 * fusão falhar em silêncio — `skipLibCheck: true` engole o erro e o resultado é
 * o mesmo TS2339 de agora, sem nenhuma pista de que este arquivo é o culpado.
 *
 * Some quando o jest-dom publicar tipos para o Vitest 5. Aí este arquivo sai e
 * `types/vitest.d.ts` do próprio pacote volta a dar conta.
 */
import type { TestingLibraryMatchers } from '@testing-library/jest-dom/matchers';

declare module 'vitest' {
  /*
   * `R` é o retorno de cada matcher (o que permite encadear) e vai para o
   * SEGUNDO parâmetro de `TestingLibraryMatchers<E, R>`. `T` — o valor sob
   * asserção — não é repassado: o jest-dom já se declara sobre `HTMLElement`
   * em cada assinatura. Ele existe aqui só para a lista bater com a do Vitest.
   *
   * No lugar de `E` vai `never`, e não o `any` que o próprio jest-dom usa. `E`
   * aparece em cinco matchers como `string | RegExp | E`, para acomodar
   * asymmetric matchers; com `any` a união inteira DESABA em `any` e
   * `toHaveAccessibleName(123)` passa batido. Com `never` a união fica
   * `string | RegExp`, e `expect.stringContaining(...)` continua aceito de
   * graça — ele devolve `any` no Vitest 5, que é atribuível a qualquer coisa.
   *
   * Os dois `eslint-disable` são consequência direta disso, não descuido: a
   * interface é vazia porque todo o conteúdo vem do `extends` (forma canônica
   * de augmentation por fusão, que o `no-empty-object-type` não distingue de um
   * `interface Foo {}` esquecido), e `T` fica sem uso porque a fusão exige a
   * lista de parâmetros inteira. Renomear para `_T` não serve — os NOMES também
   * têm de bater.
   */
  // eslint-disable-next-line @typescript-eslint/no-empty-object-type, @typescript-eslint/no-unused-vars
  interface Matchers<R extends void | Promise<void> = void | Promise<void>, T = unknown>
    extends TestingLibraryMatchers<never, R> {}
}
