# Importação CSV em lote auditável com decisão por linha

O import era um preview + bulk genérico: linhas inválidas sumiam em silêncio, duplicatas eram apenas marcadas e nada era rastreável. Decidimos: V1 com decisão explícita por linha **importar/ignorar** (mesclar fica para depois), `ImportBatch` + `ImportRow` com status e motivo por linha, fingerprint idempotente (reimportar o mesmo arquivo não duplica) e preenchimento completo de `billing_month`. `invert_amount` significa "tratar valores como despesa" (sinal explícito), não negação incondicional.
