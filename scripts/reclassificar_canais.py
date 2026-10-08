"""Correção histórica de leads.canal_entrada — separação site / google_ads / meta_ads
(pedido da Stella, 07/10/2026), com as mesmas regras que os workers passaram a usar:

- BotConversa: "Canal de Aquisição" + etiquetas de anúncio (workers/common/canais.py)
- Agendor: "Origem do cliente" da pessoa e das organizações ligadas ao negócio,
  categoria da pessoa e funil (Jornada Porter / Porter Summit -> evento)
- precedência: anúncio pago prevalece; organico aceita qualquer canal concreto;
  entre canais concretos não pagos mantém o primeiro toque

Toda mudança fica registrada em leads_canal_reclassificacao (sql/020) com o canal
anterior, pra auditoria e pra desfazer. Também preenche origem_detalhe_entrada
quando estava vazia e o Agendor tem a origem (ex.: PAP, Visitas Comerciais).

A leitura do Agendor (people/organizations/deals) leva ~20 min por causa do limite
de requisições da API; --cache-dir reaproveita os JSONs de uma leitura anterior.

Uso: python scripts/reclassificar_canais.py [--cache-dir DIR] [--aplicar]
     (sem --aplicar só simula e imprime o resumo)
"""
import argparse
import collections
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workers.common.canais import deve_substituir_canal, mapear_canal_botconversa  # noqa: E402
from workers.common.db import get_connection  # noqa: E402
from workers.common.regras_negocio import campanha_evento_agendor, canal_concreto_origem_agendor  # noqa: E402

BASE_URL = "https://api.agendor.com.br/v3"


def _paginar(recurso: str):
    headers = {"Authorization": f"Token {os.environ['AGENDOR_TOKEN']}"}
    url, params = f"{BASE_URL}/{recurso}", {"page": 1, "per_page": 100}
    while url:
        for tentativa in range(8):
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=90)
            except requests.RequestException:
                time.sleep(5 * (tentativa + 1))
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(5 * (tentativa + 1))
                continue
            resp.raise_for_status()
            break
        else:
            raise RuntimeError(f"Agendor não respondeu em {url}")
        corpo = resp.json()
        yield from corpo.get("data", [])
        url, params = (corpo.get("links") or {}).get("next"), None
        time.sleep(0.6)


def _nome(obj, chave):
    return ((obj or {}).get(chave) or {}).get("name")


def carregar_agendor(cache_dir: Path | None) -> tuple[dict, dict, dict]:
    """(deals, pessoas, orgs) indexados por id, lendo do cache quando houver."""
    if cache_dir and (cache_dir / "agendor_origens.json").exists() and (cache_dir / "agendor_cadastros.json").exists():
        deals = json.load(open(cache_dir / "agendor_origens.json", encoding="utf-8"))
        cad = json.load(open(cache_dir / "agendor_cadastros.json", encoding="utf-8"))
        pessoas, orgs = cad["pessoas"], cad["orgs"]
    else:
        deals = {
            d["id"]: {"p_id": (d.get("person") or {}).get("id"), "o_id": (d.get("organization") or {}).get("id"),
                      "po_id": ((d.get("person") or {}).get("organization") or {}).get("id"),
                      "funil": _nome(d.get("dealStage"), "funnel")}
            for d in _paginar("deals")
        }
        pessoas = {p["id"]: {"origin": _nome(p, "leadOrigin"), "cat": _nome(p, "category"),
                             "org": (p.get("organization") or {}).get("id")} for p in _paginar("people")}
        orgs = {o["id"]: {"origin": _nome(o, "leadOrigin"), "cat": _nome(o, "category")} for o in _paginar("organizations")}
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)
            json.dump(deals, open(cache_dir / "agendor_origens.json", "w", encoding="utf-8"))
            json.dump({"pessoas": pessoas, "orgs": orgs}, open(cache_dir / "agendor_cadastros.json", "w", encoding="utf-8"))
    as_int = lambda d: {int(k): v for k, v in d.items()}  # noqa: E731 (JSON transforma chave em str)
    return as_int(deals), as_int(pessoas), as_int(orgs)


def sinais_agendor(negocio_ids, deals, pessoas, orgs):
    """Lista de (canal, campanha, motivo, origem_detalhe) vinda dos negócios do lead."""
    sinais = []
    for nid in negocio_ids or []:
        deal = deals.get(nid)
        if not deal:
            continue
        pessoa = pessoas.get(deal.get("p_id")) or {}
        origens = [("pessoa", pessoa.get("origin"))] + [
            ("organizacao", (orgs.get(oid) or {}).get("origin"))
            for oid in (deal.get("o_id"), deal.get("po_id"), pessoa.get("org")) if oid
        ]
        for onde, origem in origens:
            if origem:
                sinais.append((canal_concreto_origem_agendor(origem), None, f"agendor:{onde}:{origem}", origem))
        campanha = campanha_evento_agendor(pessoa.get("cat"), deal.get("funil"))
        if campanha:
            sinais.append(("evento", campanha, f"agendor:categoria/funil:{campanha}", None))
    return sinais


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--aplicar", action="store_true")
    args = parser.parse_args()

    deals, pessoas, orgs = carregar_agendor(args.cache_dir)
    lote = datetime.now().strftime("reclass-%Y%m%d-%H%M%S")
    mudancas = collections.Counter()
    exemplos_motivo = collections.Counter()
    alteracoes = []

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT l.id, l.canal_entrada, l.campanha_entrada, l.origem_detalhe_entrada, l.dados_botconversa,
                       array_remove(array_agg(n.agendor_negocio_id), NULL) AS negocios
                FROM leads l LEFT JOIN negocios n ON n.lead_id = l.id
                GROUP BY l.id
            """)
            leads = cur.fetchall()

        for lead in leads:
            bc = lead["dados_botconversa"] or {}
            sinais = sinais_agendor(lead["negocios"], deals, pessoas, orgs)
            canal_bc = mapear_canal_botconversa(bc.get("canal_aquisicao_bc"), bc.get("tags") or [])
            if canal_bc:
                sinais.append((canal_bc, None, f"botconversa:{bc.get('canal_aquisicao_bc') or 'etiqueta'}", None))
            if lead["origem_detalhe_entrada"]:
                sinais.append((canal_concreto_origem_agendor(lead["origem_detalhe_entrada"]), None,
                               f"origem_detalhe:{lead['origem_detalhe_entrada']}", None))

            canal, campanha, motivo = lead["canal_entrada"], lead["campanha_entrada"], None
            for canal_sinal, campanha_sinal, motivo_sinal, _ in sinais:
                if deve_substituir_canal(canal, canal_sinal):
                    canal, motivo = canal_sinal, motivo_sinal
                    # nome de evento não vale mais se o lead deixou de ser 'evento'
                    campanha = campanha_sinal or (None if lead["canal_entrada"] == "evento" else lead["campanha_entrada"])
            origem_nova = None
            if not lead["origem_detalhe_entrada"]:
                origem_nova = next((o for *_, o in sinais if o), None)

            campos = {}
            if canal != lead["canal_entrada"]:
                campos["canal_entrada"] = canal
                mudancas[(lead["canal_entrada"], canal)] += 1
                exemplos_motivo[motivo.split(":")[0] + ":" + motivo.split(":")[-1]] += 1
                if campanha != lead["campanha_entrada"]:
                    campos["campanha_entrada"] = campanha
            if origem_nova:
                campos["origem_detalhe_entrada"] = origem_nova
                mudancas[("origem_detalhe preenchida", "")] += 1

            if campos:
                alteracoes.append((
                    lead["id"], campos.get("canal_entrada"), "campanha_entrada" in campos,
                    campos.get("campanha_entrada"), campos.get("origem_detalhe_entrada"),
                    lead["canal_entrada"], motivo,
                ))

        if args.aplicar and alteracoes:
            # um único lote (COPY + UPDATE ... FROM) em vez de um UPDATE por lead:
            # ~1.400 idas e voltas ao Postgres remoto levavam minutos
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TEMP TABLE _reclass (
                        lead_id INTEGER, canal_novo TEXT, muda_campanha BOOLEAN, campanha TEXT,
                        origem_detalhe TEXT, canal_anterior TEXT, motivo TEXT
                    ) ON COMMIT DROP
                """)
                with cur.copy("COPY _reclass FROM STDIN") as copy:
                    for linha in alteracoes:
                        copy.write_row(linha)
                cur.execute("""
                    UPDATE leads l SET
                        canal_entrada = COALESCE(r.canal_novo, l.canal_entrada),
                        campanha_entrada = CASE WHEN r.muda_campanha THEN r.campanha ELSE l.campanha_entrada END,
                        origem_detalhe_entrada = COALESCE(l.origem_detalhe_entrada, r.origem_detalhe),
                        atualizado_em = NOW()
                    FROM _reclass r WHERE r.lead_id = l.id
                """)
                cur.execute("""
                    INSERT INTO leads_canal_reclassificacao (lote, lead_id, canal_anterior, canal_novo, motivo)
                    SELECT %s, lead_id, canal_anterior, canal_novo, motivo FROM _reclass WHERE canal_novo IS NOT NULL
                """, (lote,))
            conn.commit()

    print(("APLICADO, lote " + lote) if args.aplicar else "SIMULAÇÃO (nada gravado)")
    for (de, para), n in mudancas.most_common():
        print(f"  {de:>26} -> {para:<12} {n}")
    print("motivos:")
    for m, n in exemplos_motivo.most_common(20):
        print(f"  {n:>6}  {m}")


if __name__ == "__main__":
    main()
