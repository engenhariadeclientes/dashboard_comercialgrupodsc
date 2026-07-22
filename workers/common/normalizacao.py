"""Normalização e higienização de dados de lead — spec seções 5.1 e 6.

Mantém, propositalmente, sua própria cópia da tabela DDD→UF (em vez de consultar o
banco a cada telefone) porque é uma referência nacional fixa (ANATEL) e o parsing
de telefone roda em volume alto nos importers/workers. Precisa ficar em sincronia
com sql/004_seed_ddd_uf.sql se a lista de DDDs mudar.
"""
import re
import unicodedata
from typing import Optional

DDD_UF = {
    11: "SP", 12: "SP", 13: "SP", 14: "SP", 15: "SP", 16: "SP", 17: "SP", 18: "SP", 19: "SP",
    21: "RJ", 22: "RJ", 24: "RJ",
    27: "ES", 28: "ES",
    31: "MG", 32: "MG", 33: "MG", 34: "MG", 35: "MG", 37: "MG", 38: "MG",
    41: "PR", 42: "PR", 43: "PR", 44: "PR", 45: "PR", 46: "PR",
    47: "SC", 48: "SC", 49: "SC",
    51: "RS", 53: "RS", 54: "RS", 55: "RS",
    61: "DF",
    62: "GO", 64: "GO",
    63: "TO",
    65: "MT", 66: "MT",
    67: "MS",
    68: "AC",
    69: "RO",
    71: "BA", 73: "BA", 74: "BA", 75: "BA", 77: "BA",
    79: "SE",
    81: "PE", 87: "PE",
    82: "AL",
    83: "PB",
    84: "RN",
    85: "CE", 88: "CE",
    86: "PI", 89: "PI",
    91: "PA", 93: "PA", 94: "PA",
    92: "AM", 97: "AM",
    95: "RR",
    96: "AP",
    98: "MA", 99: "MA",
}

REGIAO_POR_UF = {
    "AC": "Norte", "AP": "Norte", "AM": "Norte", "PA": "Norte", "RO": "Norte", "RR": "Norte", "TO": "Norte",
    "AL": "Nordeste", "BA": "Nordeste", "CE": "Nordeste", "MA": "Nordeste", "PB": "Nordeste",
    "PE": "Nordeste", "PI": "Nordeste", "RN": "Nordeste", "SE": "Nordeste",
    "DF": "Centro-Oeste", "GO": "Centro-Oeste", "MS": "Centro-Oeste", "MT": "Centro-Oeste",
    "ES": "Sudeste", "MG": "Sudeste", "RJ": "Sudeste", "SP": "Sudeste",
    "PR": "Sul", "RS": "Sul", "SC": "Sul",
}

_CONECTIVOS_NOME = {"de", "da", "do", "das", "dos", "e"}


def normalizar_texto_busca(texto: str) -> str:
    """lowercase, sem acento, trim — usado como chave de busca (cidade, etc.)."""
    nfkd = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    return sem_acento.lower().strip()


def normalizar_email(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    email = raw.strip().lower()
    return email or None


def normalizar_nome(raw: Optional[str]) -> Optional[str]:
    """Trim, remoção de sufixos não alfabéticos colados (ex.: '...de Oliveira.ra'), capitalização."""
    if not raw:
        return None
    nome = raw.strip()
    # sufixo colado sem espaço após um ponto (corrupção observada nos forms nativos)
    nome = re.sub(r"\.[a-zA-Z]{1,4}$", "", nome).strip()
    # remove caracteres que não sejam letras/espaço/hífen/apóstrofo
    nome = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ' \-]", "", nome)
    nome = re.sub(r"\s+", " ", nome).strip()
    if not nome:
        return None

    palavras = nome.lower().split(" ")
    capitalizadas = []
    for i, palavra in enumerate(palavras):
        if i > 0 and palavra in _CONECTIVOS_NOME:
            capitalizadas.append(palavra)
        else:
            capitalizadas.append(palavra[:1].upper() + palavra[1:] if palavra else palavra)
    return " ".join(capitalizadas)


def _valida_ddd(ddd: int) -> bool:
    return ddd in DDD_UF


def extrair_telefone_valido(raw: Optional[str]) -> tuple[Optional[str], bool]:
    """Extrai o primeiro número BR válido (DDD + 8/9 dígitos) de uma string suja.

    Retorna (telefone_e164_ou_None, telefone_invalido: bool).
    Descarta excedente (ex.: telefone duplicado/concatenado). DDD inexistente
    ou dígitos insuficientes → (None, True) — matching cai para e-mail (seção 5.1).
    """
    if not raw:
        return None, True

    digitos = re.sub(r"\D", "", raw)

    # remove um único código de país +55 na frente, se sobrar dígitos suficientes depois
    if digitos.startswith("55") and len(digitos) >= 12:
        digitos = digitos[2:]

    if len(digitos) < 10:
        return None, True

    ddd = int(digitos[0:2])
    if not _valida_ddd(ddd):
        return None, True

    resto = digitos[2:]
    if len(resto) >= 9 and resto[0] == "9":
        numero = resto[0:9]
    elif len(resto) >= 8:
        numero = resto[0:8]
    else:
        return None, True

    return f"+55{ddd:02d}{numero}", False


def gerar_variacoes_telefone(telefone_e164: str) -> list[str]:
    """Gera as variações com/sem 9º dígito para matching (seção 6)."""
    if not telefone_e164 or not telefone_e164.startswith("+55"):
        return [telefone_e164] if telefone_e164 else []

    corpo = telefone_e164[3:]
    ddd, numero = corpo[0:2], corpo[2:]
    variacoes = {telefone_e164}

    if len(numero) == 9 and numero[0] == "9":
        variacoes.add(f"+55{ddd}{numero[1:]}")  # sem o 9º dígito
    elif len(numero) == 8:
        variacoes.add(f"+55{ddd}9{numero}")  # com o 9º dígito

    return sorted(variacoes)


def uf_por_ddd(telefone_e164: Optional[str]) -> Optional[str]:
    if not telefone_e164 or not telefone_e164.startswith("+55") or len(telefone_e164) < 5:
        return None
    ddd = int(telefone_e164[3:5])
    return DDD_UF.get(ddd)


def resolver_uf_por_cidade(cidade: Optional[str], conn) -> Optional[str]:
    """Resolve UF a partir do nome da cidade (texto livre) via municipios_ibge.

    Ambiguidade (cidades homônimas em UFs diferentes) → prioriza SC; senão None
    (marca fica pendente para revisão) — regra 4.1.1.
    """
    if not cidade:
        return None
    nome_norm = normalizar_texto_busca(cidade)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT uf FROM municipios_ibge WHERE nome_normalizado = %s",
            (nome_norm,),
        )
        ufs = {row["uf"] for row in cur.fetchall()}

    if not ufs:
        return None
    if len(ufs) == 1:
        return next(iter(ufs))
    return "SC" if "SC" in ufs else None


def derivar_marca(
    conn,
    cidade: Optional[str] = None,
    uf_informada: Optional[str] = None,
    telefone_e164: Optional[str] = None,
) -> dict:
    """Deriva marca/UF/regiao de um lead — regra de negócio central (4.1.1).

    Ordem: UF explícita > cidade (via IBGE, SC prioritária em empate) >
    fallback DDD do telefone (uf_derivada_por_ddd=True, confiança menor) >
    desconhecido (marca=None, "pendente").
    """
    uf = None
    uf_derivada_por_ddd = False

    if uf_informada and len(uf_informada.strip()) == 2:
        uf = uf_informada.strip().upper()
    elif cidade:
        uf = resolver_uf_por_cidade(cidade, conn)

    if uf is None and telefone_e164:
        uf = uf_por_ddd(telefone_e164)
        uf_derivada_por_ddd = uf is not None

    if uf is None:
        return {"marca": None, "uf": None, "regiao": None, "uf_derivada_por_ddd": False}

    marca = "Duplique" if uf == "SC" else "DSC"
    return {
        "marca": marca,
        "uf": uf,
        "regiao": REGIAO_POR_UF.get(uf),
        "uf_derivada_por_ddd": uf_derivada_por_ddd,
    }
