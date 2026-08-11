from datetime import datetime, UTC
from typing import Optional

from sqlalchemy import Column, String, Text
from sqlmodel import SQLModel, Field


class AppSetting(SQLModel, table=True):
    """Configuração do site alterável em RUNTIME, sem editar `.env` nem reiniciar.

    Por que existe uma segunda fonte de configuração além do `Settings`: as duas
    respondem a perguntas diferentes. O `.env` responde "como este processo se
    conecta ao mundo" — banco, chave de assinatura, SMTP, fuso — e mudar isso é
    ato de quem tem acesso ao host, com reinício. Esta tabela responde "como o
    site se comporta hoje" — se aceita cadastro aberto, quanto cada workspace
    pode guardar de anexo, se está em manutenção — e quem decide é o admin, pela
    tela, com a mudança valendo na requisição seguinte.

    O valor é JSON em texto (não uma coluna por chave) porque o conjunto de
    chaves cresce com o produto, e uma coluna nova a cada botão da tela de
    administração significaria uma migração a cada botão. A tipagem mora no
    `app.services.app_settings`, que é o único lugar que lê e escreve aqui —
    nenhuma rota toca nesta tabela diretamente.

    CREDENCIAL NÃO ENTRA AQUI. Senha de SMTP, segredo do Google e `SECRET_KEY`
    continuam no ambiente: esta tabela vai no `pg_dump`, e o dump circula em
    backup, em cópia de ensaio e na máquina de quem for depurar. O que a tela de
    Admin oferece sobre SMTP é diagnóstico (está configurado? o envio funciona?),
    não o segredo.
    """

    key: str = Field(sa_column=Column(String(64), primary_key=True))
    # JSON serializado. Guardar o tipo junto do valor é o que permite distinguir
    # o booleano `false` da string "false" — e um modo de manutenção que liga
    # porque alguém gravou "false" seria um belo jeito de derrubar o site.
    value: str = Field(sa_column=Column(Text, nullable=False))
    updated_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
