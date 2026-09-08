# Execução do plano de produto — o que foi feito, medido e o que ficou

Companheiro de `PLANO_PRODUTO_2026-09-04.md` e `ANALISE_PRODUTO_2026-09-04.md`.
Este arquivo registra **o que saiu do plano e virou código**, com os números
medidos depois — não os estimados antes.

Branch: `fix/auditoria-ux` · PR #80

---

## 1. Ondas concluídas

| Onda | Assunto | Estado |
|---|---|---|
| 0 | A projeção contava o passado como se fosse deste mês | ✅ |
| 1 | Ruído: 12 achados que não dependiam de decisão nenhuma | ✅ |
| 2 | A primeira tela vira "Hoje" | ✅ |
| 3 | O formulário de despesa | ✅ |
| 4 | Busca, desfazer e lote | ✅ |
| 5 | Arquitetura: escopo vira filtro | ⛔ **bloqueada** — ver §4 |
| 6 | Onboarding | ✅ |

---

## 2. Métricas objetivas (§10.3 do plano)

| Métrica | Antes | Agora | Meta | |
|---|---:|---:|---:|:--:|
| Altura de `/overview` a 390px | 2.430px | **1.169px** | ≤ 1.400 | ✅ |
| Controles no formulário de despesa (simples) | 12 | **2** | ≤ 5 | ✅ |
| Telas que mostram o mesmo saldo | 3 | **1** | 1 | ✅ |
| Cabeçalho antes da 1ª linha em `/me/payables` | — | **455px** | ≤ 700 | ✅ |
| Cabeçalho antes da 1ª linha em `/me/ledger` | — | **537px** | ≤ 700 | ✅ |
| Toques para lançar despesa simples | 4 | 4 | ≤ 4 | ✅ |
| Violações axe | 0 | 0 | 0 | ✅ |
| Rotas com rolagem horizontal | 0 | 0 | 0 | ✅ |
| Itens de menu | 20 | **20** | ≤ 10 | ⛔ Onda 5 |

> A altura de `/overview` foi medida com o portão novo (`e2e/larguras.spec.ts`),
> não a olho. O número do plano (2.475–3.064px) veio de uma conta com mais
> dados; 2.430px é a mesma tela com a conta semeada do portão, que é a que
> continua sendo medida a cada execução.

### Sobre a régua de `/me/payables`

O plano pedia "altura total ≤ 3.000px". Medi **788px** com a conta semeada e
quase registrei o alvo como atingido — mas o número não significava nada: a
tela é uma **lista**, e ela era alta na auditoria (7.095px) porque a conta
tinha muitas contas a pagar, não porque o desenho fosse ruim.

A régua foi trocada por uma que não depende do volume de dados: **quantos pixels
de cabeçalho a pessoa atravessa até a primeira linha acionável**. Esse número
piora quando alguém empilha mais um bloco de resumo no topo, que é o defeito que
se quer impedir.

---

## 3. Portões novos (o que impede a regressão)

| Portão | Onde | O que tranca |
|---|---|---|
| Densidade | `e2e/larguras.spec.ts` | teto de altura por rota e de cabeçalho antes da 1ª linha |
| Sobreposição | idem | nenhum controle flutuante cobre texto no diálogo |
| Textos | `e2e/textos.spec.ts` | data ISO e enum cru em 17 rotas |
| Formulário | `e2e/nova_despesa.spec.ts` | ≤ 5 controles no modo simples; detalhar não perde dado |
| Busca e desfazer | `e2e/busca.spec.ts` | atalho, navegação, undo e lote |
| Visibilidade da busca | `tests/security/test_busca_respeita_visibilidade.py` | restrito não acha o que a lista esconde |
| Jargão | `eslint.config.js` | "ADR NNNN", "workspace", "a casa" em texto de tela |
| Cor crua | idem (já existia) | paleta do Tailwind fora dos tokens |
| Rótulos das suítes | `OnboardingModal.rotulos.test.tsx` | renomear texto que o e2e-prod digita falha em segundos |

---

## 4. Onda 5 — por que ela não foi feita

O próprio plano a bloqueia: *"Esta onda não começa sem um ADR aprovado."*

Ela contradiz a estrutura do **ADR 0020** (escopo como rota), que foi decidida
com motivo. Fundir Acertos, Relatórios, Contas a pagar e Lançamentos — e
transformar pessoal × compartilhado num filtro — muda o endereço de metade das
telas do produto. Três coisas precisam da sua palavra antes de qualquer linha:

1. **O eixo pessoal × compartilhado sai da navegação?** Ele continua existindo no
   modelo (ADR 0021), mas deixaria de organizar o menu.
2. **O que acontece com os links salvos?** O plano exige o portão de
   compatibilidade (`O5-2`) como pré-requisito, não como acabamento.
3. **O Painel do espaço fica, sai ou vira o nome do espaço?**

É a única onda cuja reversão é cara: as outras seis são telas e regras; esta é
endereço.

---

## 5. O que este ciclo ensinou (e já virou portão)

1. **Portão frouxo casa com o antes e com o depois.** A primeira versão da
   varredura de rótulos usava `/Começar/` e passava feliz com "Começar Setup" —
   exatamente o texto que estava quebrando o CI.
2. **Medir sem denominador passa vazio.** 788px em `/me/payables` e 455px de
   cabeçalho são o mesmo desenho; só o segundo número diz alguma coisa.
3. **`toISOString()` é UTC.** Três testes montavam "hoje" assim e viraram
   vermelhos quando o relógio passou das 21h, no meio da sessão. O app já
   distinguia instante de dia civil; as suítes, não (`e2e-shared/datas.ts`).
4. **Roteiro que trava não avisa.** O `npm run shots` ficou pendurado esperando
   um campo que a Onda 3 escondeu, gerando 35 de 129 capturas — e saindo com
   código 0.
5. **Um portão vermelho pode estar escondendo outro.** O `prod-stack` acusou
   "Começar Setup"; corrigido, apareceu "Sair da Conta" logo abaixo.

---

## 6. Pendente de verificação humana

- **Aparelho físico** (§10.2 do plano): barra de status nas 4 combinações de
  tema, teclado virtual, gestos e o app instalado — desinstalando antes, porque
  o WebAPK guarda o manifesto.
- **A nota subjetiva** (UI/UX/consistência): só faz sentido dada por quem usa.
- `a11y.spec.ts` (Administração) reprovou **uma vez** e passou nas duas
  execuções seguintes sem alteração no meio. Anotado como intermitente; não
  investigado.
