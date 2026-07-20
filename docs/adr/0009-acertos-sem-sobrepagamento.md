# Acertos de dívida: sobrepagamento proibido; terceiros só admin+

Um acerto podia ser criado entre quaisquer dois membros com qualquer valor, invertendo a relação de dívida e criando crédito artificial. Decidimos: o acerto só é aceito na direção da dívida existente e limitado ao saldo atual (`amount ≤ saldo`); um member só registra acertos em que ele é o pagador; registrar acerto de terceiros exige admin/owner. Sobrepagamento é rejeitado com erro claro em PT-BR.
