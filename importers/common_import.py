"""Helpers compartilhados entre os importers de carga inicial (spec seção 8)."""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workers.common.eventos import registrar_evento  # noqa: E402
from workers.common.matching import atualizar_campos_lead, resolver_ou_criar_lead  # noqa: E402
from workers.common.normalizacao import (  # noqa: E402
    derivar_marca,
    extrair_telefone_valido,
    gerar_variacoes_telefone,
    normalizar_email,
    normalizar_nome,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("importers")


def montar_dados_lead(
    conn,
    nome_raw: str | None,
    telefone_raw: str | None,
    email_raw: str | None,
    cidade: str | None,
    uf_informada: str | None,
    profissao_funcao: str | None,
    canal: str,
    campanha: str | None,
    origem_detalhe: str | None,
    tipo_captura: str | None,
    data_entrada,
    payload_extra: dict | None = None,
) -> dict:
    """Aplica a higienização (5.1) e a derivação de marca (4.1.1) e devolve o dict pronto
    para resolver_ou_criar_lead / atualizar_campos_lead."""
    nome = normalizar_nome(nome_raw)
    email = normalizar_email(email_raw)
    telefone, telefone_invalido = extrair_telefone_valido(telefone_raw)
    variacoes = gerar_variacoes_telefone(telefone) if telefone else []

    marca_info = derivar_marca(conn, cidade=cidade, uf_informada=uf_informada, telefone_e164=telefone)

    payload = dict(payload_extra or {})
    payload["fonte_bruta"] = {
        "nome_raw": nome_raw,
        "telefone_raw": telefone_raw,
        "email_raw": email_raw,
    }
    if telefone_invalido:
        payload["telefone_invalido"] = True

    return {
        "nome": nome,
        "telefone": telefone,
        "telefone_variacoes": variacoes or None,
        "email": email,
        "cidade": cidade,
        "uf": marca_info["uf"],
        "regiao": marca_info["regiao"],
        "marca": marca_info["marca"],
        "uf_derivada_por_ddd": marca_info["uf_derivada_por_ddd"],
        "profissao_funcao": profissao_funcao,
        "canal_entrada": canal,
        "campanha_entrada": campanha,
        "origem_detalhe_entrada": origem_detalhe,
        "tipo_captura": tipo_captura,
        "data_entrada": data_entrada,
        "payload": payload,
    }


def importar_lead(conn, dados: dict, fonte: str = "importacao") -> tuple[int, bool]:
    """Resolve/cria o lead e registra o evento `importado`."""
    lead_id, criado = resolver_ou_criar_lead(conn, dados, fonte=fonte)

    if not criado:
        atualizar_campos_lead(
            conn,
            lead_id,
            {k: dados[k] for k in ("cidade", "uf", "regiao", "marca", "uf_derivada_por_ddd") if dados.get(k) is not None},
        )

    registrar_evento(
        conn,
        lead_id=lead_id,
        fonte=fonte,
        tipo_evento="importado",
        data_evento=dados["data_entrada"],
        canal=dados["canal_entrada"],
        campanha=dados["campanha_entrada"],
        origem_detalhe=dados["origem_detalhe_entrada"],
        payload=dados.get("payload"),
    )
    return lead_id, criado
