# Telas

Catálogo completo da interface, **em tema claro e escuro**. Gerado por
`npm run shots` (ver [como regerar](#como-regerar)), com dados semeados via API —
nada aqui é montagem ou protótipo: são as telas do aplicativo rodando.

Os três blocos seguem os eixos do produto: o que é **pessoal** e acompanha a
pessoa ([ADR 0021](adr/0021-recursos-pessoais-sem-workspace.md)), o que é de
**colaboração** dentro de um workspace, e o que é de **plataforma** — quem opera
o site ([ADR 0026](adr/0026-papel-de-plataforma-e-cadastro-por-convite.md)).

## Pessoal

| Tela | Claro | Escuro |
|---|:---:|:---:|
| **Início** — o mês somando todos os workspaces | [![](images/inicio-global-light.png)](images/inicio-global-light.png) | [![](images/inicio-global-dark.png)](images/inicio-global-dark.png) |
| **Rendas** — entradas do mês e recorrentes | [![](images/rendas-light.png)](images/rendas-light.png) | [![](images/rendas-dark.png)](images/rendas-dark.png) |
| **Cartões** — limite, fatura e ciclo | [![](images/cartoes-light.png)](images/cartoes-light.png) | [![](images/cartoes-dark.png)](images/cartoes-dark.png) |
| **Financiamentos** — cronograma SAC/PRICE | [![](images/financiamentos-light.png)](images/financiamentos-light.png) | [![](images/financiamentos-dark.png)](images/financiamentos-dark.png) |
| **Compromissos** — panorama de endividamento | [![](images/compromissos-light.png)](images/compromissos-light.png) | [![](images/compromissos-dark.png)](images/compromissos-dark.png) |
| **Seus acertos** — com quem me acerto, somando as casas | [![](images/meus-acertos-light.png)](images/meus-acertos-light.png) | [![](images/meus-acertos-dark.png)](images/meus-acertos-dark.png) |
| **Seus relatórios** | [![](images/meus-relatorios-light.png)](images/meus-relatorios-light.png) | [![](images/meus-relatorios-dark.png)](images/meus-relatorios-dark.png) |
| **Extrato** — ledger de linhas do caixa | [![](images/extrato-light.png)](images/extrato-light.png) | [![](images/extrato-dark.png)](images/extrato-dark.png) |
| **Suas configurações** | [![](images/configuracoes-pessoais-light.png)](images/configuracoes-pessoais-light.png) | [![](images/configuracoes-pessoais-dark.png)](images/configuracoes-pessoais-dark.png) |

## Colaboração — o workspace

| Tela | Claro | Escuro |
|---|:---:|:---:|
| **Painel** | [![](images/painel-workspace-light.png)](images/painel-workspace-light.png) | [![](images/painel-workspace-dark.png)](images/painel-workspace-dark.png) |
| **Lançamentos** | [![](images/lancamentos-light.png)](images/lancamentos-light.png) | [![](images/lancamentos-dark.png)](images/lancamentos-dark.png) |
| **Relatórios** — a tela mais densa em cor | [![](images/relatorios-light.png)](images/relatorios-light.png) | [![](images/relatorios-dark.png)](images/relatorios-dark.png) |
| **Recorrência** | [![](images/recorrencia-light.png)](images/recorrencia-light.png) | [![](images/recorrencia-dark.png)](images/recorrencia-dark.png) |
| **Acertos** — quem deve para quem NESTA casa | [![](images/acertos-light.png)](images/acertos-light.png) | [![](images/acertos-dark.png)](images/acertos-dark.png) |
| **Importar CSV** | [![](images/importar-light.png)](images/importar-light.png) | [![](images/importar-dark.png)](images/importar-dark.png) |
| **Configurações do workspace** | [![](images/configuracoes-workspace-light.png)](images/configuracoes-workspace-light.png) | [![](images/configuracoes-workspace-dark.png)](images/configuracoes-workspace-dark.png) |

## Avisos de vencimento

| Tela | Claro | Escuro |
|---|:---:|:---:|
| **O convite** — explica o que se ganha ANTES de pedir a permissão | [![](images/aviso-convite-light.png)](images/aviso-convite-light.png) | [![](images/aviso-convite-dark.png)](images/aviso-convite-dark.png) |
| **Contas a pagar** — a oferta fica onde a falta do aviso dói | [![](images/aviso-contas-a-pagar-light.png)](images/aviso-contas-a-pagar-light.png) | [![](images/aviso-contas-a-pagar-dark.png)](images/aviso-contas-a-pagar-dark.png) |

O prompt do navegador só aparece depois do clique em **Ativar avisos**: negado,
ele não pode ser pedido de novo, e um "não" por reflexo custaria o canal para
sempre ([ADR 0033](adr/0033-aviso-de-vencimento.md)).

## Plataforma

| Tela | Claro | Escuro |
|---|:---:|:---:|
| **Administração** — pessoas, convites e configuração do site | [![](images/administracao-light.png)](images/administracao-light.png) | [![](images/administracao-dark.png)](images/administracao-dark.png) |

O administrador vê contagem, espaço em disco e papel — **nunca o dinheiro de
ninguém**. Isso é decisão de projeto, com teste dedicado que reprova regressão.

## Modais

| Tela | Claro | Escuro |
|---|:---:|:---:|
| **Nova Despesa** — divisão, pagadores e itens | [![](images/nova-despesa-modal-light.png)](images/nova-despesa-modal-light.png) | [![](images/nova-despesa-modal-dark.png)](images/nova-despesa-modal-dark.png) |
| **Nova Renda** | [![](images/nova-renda-modal-off-light.png)](images/nova-renda-modal-off-light.png) | [![](images/nova-renda-modal-off-dark.png)](images/nova-renda-modal-off-dark.png) |
| **Nova Renda** — com recorrência ligada | [![](images/nova-renda-modal-on-light.png)](images/nova-renda-modal-on-light.png) | [![](images/nova-renda-modal-on-dark.png)](images/nova-renda-modal-on-dark.png) |
| **Onboarding** — a primeira tela de quem chega | [![](images/onboarding-modal.png)](images/onboarding-modal.png) | — |

## Entrar e cadastrar

| Tela | Claro | Escuro |
|---|:---:|:---:|
| **Entrar** | [![](images/auth-login-light.png)](images/auth-login-light.png) | [![](images/auth-login-dark.png)](images/auth-login-dark.png) |
| **Criar conta** | [![](images/auth-register-light.png)](images/auth-register-light.png) | [![](images/auth-register-dark.png)](images/auth-register-dark.png) |
| **Esqueci a senha** | [![](images/auth-esqueci-senha-light.png)](images/auth-esqueci-senha-light.png) | [![](images/auth-esqueci-senha-dark.png)](images/auth-esqueci-senha-dark.png) |
| **Redefinir senha** — estado de link inválido | [![](images/auth-redefinir-senha-light.png)](images/auth-redefinir-senha-light.png) | [![](images/auth-redefinir-senha-dark.png)](images/auth-redefinir-senha-dark.png) |

## Mobile

Largura de 390px, com a barra inferior de navegação.

| Tela | Claro | Escuro |
|---|:---:|:---:|
| **Início** | [![](images/mobile-inicio-light.png)](images/mobile-inicio-light.png) | [![](images/mobile-inicio-dark.png)](images/mobile-inicio-dark.png) |
| **Lançamentos** | [![](images/mobile-lancamentos-light.png)](images/mobile-lancamentos-light.png) | [![](images/mobile-lancamentos-dark.png)](images/mobile-lancamentos-dark.png) |
| **Relatórios** | [![](images/mobile-relatorios-light.png)](images/mobile-relatorios-light.png) | [![](images/mobile-relatorios-dark.png)](images/mobile-relatorios-dark.png) |
| **Cartões** | [![](images/mobile-cartoes-light.png)](images/mobile-cartoes-light.png) | [![](images/mobile-cartoes-dark.png)](images/mobile-cartoes-dark.png) |
| **Seus acertos** | [![](images/mobile-meus-acertos-light.png)](images/mobile-meus-acertos-light.png) | [![](images/mobile-meus-acertos-dark.png)](images/mobile-meus-acertos-dark.png) |

---

## Como regerar

```bash
cd frontend
npm run shots                                  # captura em frontend/screenshots/
python scripts/comprimir-shots.py              # recomprime para docs/images/
```

O roteiro (`e2e-shots/screenshots.spec.ts`) sobe um backend próprio contra um
`shots.db` descartável, semeia dados realistas pela API e percorre todas as
rotas nos dois temas. A saída vai para `frontend/screenshots/` — que é
gitignorada; as imagens deste catálogo são as mesmas, recomprimidas para 256
cores (~70% menores, sem diferença perceptível no tamanho em que são lidas).

**A recompressão é um script, não uma lembrança.** Ela sempre foi feita à mão com
ImageMagick ou Pillow, e numa regeração feita em máquina sem nenhum dos dois as
imagens entraram cruas — `docs/images` cresceu 45% de uma vez, e nada acusou.
`scripts/comprimir-shots.py` faz o mesmo usando só a biblioteca padrão do Python;
`--check` relata sem escrever.

**As capturas são do VIEWPORT (1440×900), não da página inteira.** Com
`fullPage: true` a tela de Acertos saía 1440×5118 — uma tira de 3,5:1 que o
GitHub renderiza como um risco ilegível nas tabelas acima. 1440 e não 1920 porque
o conteúdo do `AppShell` é limitado a `max-w-[1200px]`: numa janela maior as
imagens só ganhariam vazio nas laterais. O mobile usa 390×844, o viewport CSS do
iPhone 12–16 base.

Três detalhes do roteiro que existem por terem falhado antes:

- **`REGISTRATION_MODE=open`** no servidor efêmero. A semeadura cria uma conta, e
  desde o ADR 0026 o cadastro nasce por convite — sem isso o roteiro morria com
  403 antes da primeira captura, e ficou assim por não haver quem o executasse.
- **A conta precisa nascer superadministradora** (`SUPERADMIN_EMAIL` casando com
  o e-mail do roteiro). Sem isso `/admin` sairia como tela de erro — e entraria
  no catálogo como se fosse a tela real.
- **A semeadura confere cada resposta.** As rendas eram postadas num endpoint que
  saiu no ADR 0021; as chamadas falhavam em silêncio e o catálogo inteiro
  mostrava "Renda R$ 0,00", passando por estado legítimo do aplicativo.
