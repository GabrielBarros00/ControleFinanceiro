# Alembic é a única interface de evolução de schema

O startup rodava `SQLModel.metadata.create_all` + reparos manuais (`ensure_schema_up_to_date`), deixando o dev.db híbrido: `alembic_version` na revisão base com schema do head — um `upgrade head` nele quebraria. Decidimos: remover `create_all` e os reparos do fluxo normal; reconciliar o dev.db existente com backup + `alembic stamp head` (dados preservados); toda mudança de schema nasce como revisão Alembic e é validada em banco zero, cópia do dev.db e Postgres.

Considered options: recriar o dev.db do zero (descartado — perderia dados de desenvolvimento úteis).
