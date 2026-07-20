# `statement_id` é exclusivamente derivado no servidor

A API aceitava `statement_id` do cliente sem validação de cartão/workspace (IDOR e corrupção cruzada de fatura). Decidimos remover o campo dos DTOs públicos de criação/edição: a fatura é sempre resolvida no servidor a partir de cartão + data da compra + dia de fechamento. Alterar data ou cartão de uma despesa rerroteia a fatura automaticamente; remover o cartão limpa o vínculo. Nenhum chamador fora do módulo de cartões manipula `statement_id`.
