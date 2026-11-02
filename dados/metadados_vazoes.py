"""Origem e correspondências do Parquet, sem acrescentar colunas de observações."""

import json
import re
import unicodedata

from infraestrutura.preparar_ambiente import garantir_dependencias
garantir_dependencias({"pyarrow": "pyarrow>=14"})
import pyarrow as pa
import pyarrow.parquet as pq


COLUNAS_BASE_NEWAVE = ["scenario_id", "stage_id", "node_id", "hydro_id", "incremental_inflow_m3s"]
ESTATISTICAS_PAR = ["annual_coefficient", "annual_mean_m3s", "annual_std_m3s",
                    "seasonal_mean_m3s", "seasonal_std_m3s"]


def colunas_newave_completo(max_order):
    return (COLUNAS_BASE_NEWAVE + ["inflow_nonnegativity_slack_m3s", "ar_order"]
            + [f"ar_coefficient_lag_{k}" for k in range(1, max_order + 1)] + ESTATISTICAS_PAR)


def normalizar_nome_usina(nome):
    texto = unicodedata.normalize("NFKD", str(nome).upper())
    return re.sub(r"[^A-Z0-9]", "", "".join(c for c in texto if not unicodedata.combining(c)))


def ler_metadados_vazoes(caminho):
    schema = pq.read_schema(caminho)
    metadata = schema.metadata or {}
    try:
        modelo = metadata.get(b"source_model", b"COBRE").decode("utf-8").upper()
        sem_no = metadata.get(b"node_id_semantics", b"").decode("utf-8") == "unavailable"
        mapas = {k: json.loads(metadata.get(k.encode(), b"[]").decode("utf-8"))
                 for k in ("hydro_mapping", "stage_mapping")}
    except (ValueError, UnicodeError) as erro:
        raise ValueError("Metadados de origem ou correspondência inválidos no Parquet.") from erro
    if not all(isinstance(mapa, list) for mapa in mapas.values()):
        raise ValueError("Os mapas de usinas e estágios do Parquet devem ser listas.")
    if modelo == "NEWAVE":
        if not sem_no or not all(mapas.values()):
            raise ValueError("Parquet NEWAVE sem indicação de node_id indisponível ou sem mapas de correspondência.")
        if "node_id" not in schema.names or not pa.types.is_integer(schema.field("node_id").type):
            raise ValueError("node_id do NEWAVE deve ter tipo inteiro anulável.")
        for mapa,chave,campos in [(mapas["hydro_mapping"],"hydro_id",("nome_usina_cadastro",)),
                                   (mapas["stage_mapping"],"stage_id",("start_date","end_date"))]:
            vistos = set()
            for item in mapa:
                if (not isinstance(item,dict) or not isinstance(item.get(chave),int)
                        or isinstance(item[chave],bool) or item[chave] in vistos
                        or not all(isinstance(item.get(c),str) and item[c] for c in campos)):
                    raise ValueError(f"Mapa de correspondência inválido ou duplicado para {chave}.")
                vistos.add(item[chave])
    enriquecido = modelo == "NEWAVE" and (b"newave_schema_version" in metadata
                   or "ar_order" in schema.names or any(c.startswith("ar_coefficient_lag_") for c in schema.names))
    max_order = None
    if enriquecido:
        try:
            max_order = int(metadata[b"ar_max_order"].decode())
        except (ValueError, KeyError, UnicodeError) as erro:
            raise ValueError("Parquet NEWAVE enriquecido sem limite de lags válido.") from erro
        if (metadata.get(b"newave_schema_version") != b"2" or max_order < 0
                or metadata.get(b"coefficient_basis") != b"seasonal_standardized"
                or metadata.get(b"slack_semantics") != b"unavailable"):
            raise ValueError("Metadados do ajuste NEWAVE enriquecido inválidos.")
        if schema.names != colunas_newave_completo(max_order):
            raise ValueError("Colunas ou ordem do Parquet NEWAVE enriquecido incompatíveis com o esquema.")
        if not pa.types.is_integer(schema.field("ar_order").type):
            raise ValueError("ar_order deve ter tipo inteiro.")
        for c in schema.names[5:]:
            if c != "ar_order" and schema.field(c).type != pa.float64():
                raise ValueError(f"{c}: o parâmetro NEWAVE deve ter tipo float64.")
    return dict(modelo=modelo, node_id_ausente=(modelo == "NEWAVE" and sem_no),
                par_enriquecido=enriquecido, max_order=max_order, **mapas)
