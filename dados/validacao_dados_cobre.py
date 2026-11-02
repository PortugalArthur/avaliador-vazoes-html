"""Valida as fontes usadas pelo projeto de testes estatisticos do COBRE."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import re

from infraestrutura.preparar_ambiente import garantir_dependencias

garantir_dependencias({"duckdb": "duckdb>=0.10"})

import duckdb
from dados.metadados_vazoes import ler_metadados_vazoes, normalizar_nome_usina


COLUNAS_CONSOLIDADO = [
    "scenario_id",
    "stage_id",
    "node_id",
    "hydro_id",
    "incremental_inflow_m3s",
]
COLUNAS_HISTORICO = ["hydro_id", "start_date", "end_date", "value_m3s"]


def localizar_fontes_deck(pasta: str | Path) -> dict[str, str]:
    """Localiza as três fontes na raiz do deck, sem misturar arquivos de outros decks."""
    raiz = Path(pasta).resolve()
    if not raiz.is_dir():
        raise ValueError(f"Pasta do deck não encontrada: {raiz}")
    relativos = {
        "hydros": Path("system") / "hydros.json",
        "stages": Path("stages.json"),
        "historico": Path("scenarios") / "inflow_history.parquet",
    }
    faltantes = [p.as_posix() for p in relativos.values() if not (raiz / p).is_file()]
    if faltantes:
        raise ValueError(
            "Selecione a raiz do deck COBRE (novo modelo), que contém as pastas system e scenarios. "
            "Arquivos não encontrados: " + ", ".join(faltantes)
        )
    return {chave: str(raiz / relativo) for chave, relativo in relativos.items()}


def _arquivo(caminho: str | Path, extensao: str) -> Path:
    arquivo = Path(caminho).resolve()
    if not arquivo.is_file():
        raise ValueError(f"Arquivo nao encontrado: {arquivo}")
    if arquivo.suffix.lower() != extensao:
        raise ValueError(f"O arquivo deve ter extensao {extensao}: {arquivo}")
    return arquivo


def validar_parquet_consolidado(caminho: str | Path) -> dict:
    """Valida COBRE e NEWAVE identificado; só o NEWAVE admite ausência de node_id."""
    arquivo = _arquivo(caminho, ".parquet")
    origem = ler_metadados_vazoes(arquivo)
    conexao = duckdb.connect(database=":memory:")
    try:
        descricao = conexao.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(arquivo)]
        ).fetchall()
        colunas = [linha[0] for linha in descricao]
        faltantes = [coluna for coluna in COLUNAS_CONSOLIDADO if coluna not in colunas]
        if faltantes:
            raise ValueError(
                "Colunas obrigatorias ausentes no consolidado: " + ", ".join(faltantes)
            )
        condicao_no = "" if origem["node_id_ausente"] else " OR node_id IS NULL"
        nulos = conexao.execute(
            """
            SELECT COUNT(*) FROM read_parquet(?)
            WHERE scenario_id IS NULL OR stage_id IS NULL
               OR hydro_id IS NULL
            """ + condicao_no,
            [str(arquivo)],
        ).fetchone()[0]
        if nulos:
            raise ValueError(f"O consolidado possui {nulos} linhas com identificadores nulos.")
        if origem["node_id_ausente"]:
            preenchidos = conexao.execute("SELECT COUNT(*) FROM read_parquet(?) WHERE node_id IS NOT NULL",[str(arquivo)]).fetchone()[0]
            if preenchidos:
                raise ValueError("O Parquet NEWAVE deve manter node_id nulo, pois o QINCR não informa nós.")
        if origem["par_enriquecido"]:
            _validar_parametros_newave(conexao, arquivo, origem["max_order"])
        duplicadas = conexao.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT scenario_id, stage_id, node_id, hydro_id
                FROM read_parquet(?)
                GROUP BY ALL HAVING COUNT(*) > 1
            )
            """,
            [str(arquivo)],
        ).fetchone()[0]
        if duplicadas:
            raise ValueError(f"O consolidado possui {duplicadas} chaves repetidas.")
        linha = conexao.execute(
            """
            SELECT COUNT(*), COUNT(DISTINCT scenario_id), COUNT(DISTINCT stage_id),
                   LIST(DISTINCT hydro_id), LIST(DISTINCT stage_id)
            FROM read_parquet(?)
            """,
            [str(arquivo)],
        ).fetchone()
    finally:
        conexao.close()
    lags = sorted(
        (coluna for coluna in colunas if re.fullmatch(r"lag_\d+_m3s", coluna)),
        key=lambda nome: int(nome.split("_")[1]),
    )
    return {
        "caminho": str(arquivo),
        "registros": linha[0],
        "cenarios": linha[1],
        "estagios": linha[2],
        "usinas": sorted(valor for valor in (linha[3] or []) if valor is not None),
        "ids_estagios": sorted(valor for valor in (linha[4] or []) if valor is not None),
        "colunas": colunas,
        "lags": lags,
        "modelo_origem": origem["modelo"],
        "node_id_ausente": origem["node_id_ausente"],
        "parametros_par_newave": origem["par_enriquecido"],
        "mapeamento_usinas": origem["hydro_mapping"],
        "mapeamento_estagios": origem["stage_mapping"],
    }


def _validar_parametros_newave(conexao, arquivo, max_order):
    """Valida o enriquecimento sem exigir parâmetros em arquivos antigos de cinco colunas."""
    campos = ["annual_coefficient", "annual_mean_m3s", "annual_std_m3s",
              "seasonal_mean_m3s", "seasonal_std_m3s"]
    erros = [f"ar_order IS NULL OR ar_order < 0 OR ar_order > {max_order}",
             "inflow_nonnegativity_slack_m3s IS NOT NULL"]
    erros += [f'("{c}" IS NULL OR NOT isfinite("{c}"))' for c in campos]
    erros += ["annual_std_m3s < 0", "seasonal_std_m3s < 0"]
    for k in range(1, max_order + 1):
        c = f"ar_coefficient_lag_{k}"
        campos.append(c)
        erros.append(f'(ar_order >= {k} AND ("{c}" IS NULL OR NOT isfinite("{c}")))'
                     f' OR (ar_order < {k} AND "{c}" IS NOT NULL)')
    invalidas = conexao.execute('SELECT COUNT(*) FROM read_parquet(?) WHERE '
                                + ' OR '.join(f'({e})' for e in erros), [str(arquivo)]).fetchone()[0]
    if invalidas:
        raise ValueError(f"Parâmetros NEWAVE inválidos em {invalidas} linhas: conferir ordem, lags, estatísticas e slack nulo.")
    campos.append("ar_order")
    divergencias = ' OR '.join(f'(MIN("{c}") IS DISTINCT FROM MAX("{c}"))' for c in campos)
    diferentes = conexao.execute('SELECT COUNT(*) FROM (SELECT hydro_id, stage_id FROM read_parquet(?) '
                                 'GROUP BY hydro_id,stage_id HAVING ' + divergencias + ')',
                                 [str(arquivo)]).fetchone()[0]
    if diferentes:
        raise ValueError("Parâmetros NEWAVE variam entre cenários da mesma UHE/estágio.")


def validar_hydros_json(caminho: str | Path) -> dict[int, str]:
    """Valida o cadastro e devolve hydro_id -> nome."""
    arquivo = _arquivo(caminho, ".json")
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError) as erro:
        raise ValueError("O hydros.json nao contem JSON UTF-8 valido.") from erro
    if not isinstance(dados, dict) or not isinstance(dados.get("hydros"), list):
        raise ValueError("O hydros.json deve conter uma lista 'hydros'.")
    nomes = {}
    for posicao, usina in enumerate(dados["hydros"], start=1):
        if not isinstance(usina, dict) or "id" not in usina or "name" not in usina:
            raise ValueError(f"Usina {posicao} invalida no hydros.json.")
        hydro_id, nome = usina["id"], usina["name"]
        if isinstance(hydro_id, bool) or not isinstance(hydro_id, int):
            raise ValueError(f"Usina {posicao} possui id invalido.")
        if not isinstance(nome, str) or not nome.strip():
            raise ValueError(f"hydro_id {hydro_id} nao possui nome valido.")
        if hydro_id in nomes:
            raise ValueError(f"hydro_id {hydro_id} aparece mais de uma vez.")
        nomes[hydro_id] = nome.strip()
    if not nomes:
        raise ValueError("O hydros.json nao possui usinas.")
    return nomes


def validar_stages_json(caminho: str | Path) -> dict[int, dict]:
    """Valida meses completos, ordem e continuidade do calendario."""
    arquivo = _arquivo(caminho, ".json")
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError) as erro:
        raise ValueError("O stages.json nao contem JSON UTF-8 valido.") from erro
    if not isinstance(dados, dict) or not isinstance(dados.get("stages"), list):
        raise ValueError("O stages.json deve conter uma lista 'stages'.")
    registros = []
    ids = set()
    for posicao, estagio in enumerate(dados["stages"], start=1):
        if not isinstance(estagio, dict) or not all(
            campo in estagio for campo in ("id", "start_date", "end_date")
        ):
            raise ValueError(f"Estagio {posicao} invalido no stages.json.")
        stage_id = estagio["id"]
        if isinstance(stage_id, bool) or not isinstance(stage_id, int) or stage_id in ids:
            raise ValueError(f"stage_id invalido ou repetido: {stage_id!r}.")
        try:
            inicio = date.fromisoformat(estagio["start_date"])
            fim = date.fromisoformat(estagio["end_date"])
        except (TypeError, ValueError) as erro:
            raise ValueError(f"stage_id {stage_id} possui datas invalidas.") from erro
        proximo = date(inicio.year + (inicio.month == 12), 1 if inicio.month == 12 else inicio.month + 1, 1)
        if inicio.day != 1 or fim != proximo:
            raise ValueError(f"stage_id {stage_id} nao representa um mes completo.")
        ids.add(stage_id)
        registros.append((stage_id, inicio, fim))
    if not registros:
        raise ValueError("O stages.json nao possui estagios.")
    registros.sort(key=lambda item: item[1])
    for anterior, atual in zip(registros, registros[1:]):
        if anterior[2] != atual[1]:
            raise ValueError(
                f"Ha lacuna ou sobreposicao entre stage_id {anterior[0]} e {atual[0]}."
            )
    return {
        stage_id: {
            "inicio": inicio,
            "fim": fim,
            "ano": inicio.year,
            "mes": inicio.month,
            "ordem": ordem,
        }
        for ordem, (stage_id, inicio, fim) in enumerate(registros)
    }


def validar_historico(caminho: str | Path) -> dict:
    """Valida esquema, meses completos e unicidade do historico mensal."""
    arquivo = _arquivo(caminho, ".parquet")
    conexao = duckdb.connect(database=":memory:")
    try:
        descricao = conexao.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(arquivo)]
        ).fetchall()
        colunas = [linha[0] for linha in descricao]
        faltantes = [coluna for coluna in COLUNAS_HISTORICO if coluna not in colunas]
        if faltantes:
            raise ValueError("Colunas obrigatorias ausentes no historico: " + ", ".join(faltantes))
        invalidos = conexao.execute(
            """
            SELECT COUNT(*) FROM read_parquet(?)
            WHERE hydro_id IS NULL OR TRY_CAST(start_date AS DATE) IS NULL
               OR TRY_CAST(end_date AS DATE) IS NULL
               OR TRY_CAST(start_date AS DATE) <> CAST(DATE_TRUNC('month', TRY_CAST(start_date AS DATE)) AS DATE)
               OR TRY_CAST(end_date AS DATE) <> CAST(TRY_CAST(start_date AS DATE) + INTERVAL 1 MONTH AS DATE)
            """,
            [str(arquivo)],
        ).fetchone()[0]
        if invalidos:
            raise ValueError(f"O historico possui {invalidos} registros mensais invalidos.")
        duplicados = conexao.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT hydro_id, TRY_CAST(start_date AS DATE) AS inicio
                FROM read_parquet(?) GROUP BY ALL HAVING COUNT(*) > 1
            )
            """,
            [str(arquivo)],
        ).fetchone()[0]
        if duplicados:
            raise ValueError(f"O historico possui {duplicados} combinacoes repetidas de UHE e mes.")
        linha = conexao.execute(
            "SELECT COUNT(*), COUNT(DISTINCT hydro_id), MIN(start_date), MAX(start_date) FROM read_parquet(?)",
            [str(arquivo)],
        ).fetchone()
    finally:
        conexao.close()
    return {
        "caminho": str(arquivo),
        "registros": linha[0],
        "usinas": linha[1],
        "inicio": linha[2],
        "fim": linha[3],
        "colunas": colunas,
    }


def validar_compatibilidade(
    consolidado: dict, nomes: dict[int, str], calendario: dict[int, dict]
) -> list[str]:
    """Confere as chaves cruzadas sem inventar correspondencias."""
    problemas = []
    sem_nome = sorted(set(consolidado["usinas"]) - set(nomes))
    sem_data = sorted(set(consolidado["ids_estagios"]) - set(calendario))
    if sem_nome:
        problemas.append(f"UHEs sem nome no hydros.json: {sem_nome}")
    if sem_data:
        problemas.append(f"Estagios ausentes no stages.json: {sem_data}")
    if consolidado.get("modelo_origem") == "NEWAVE":
        mapa_usinas = consolidado["mapeamento_usinas"]
        mapa_estagios = consolidado["mapeamento_estagios"]
        if {u["hydro_id"] for u in mapa_usinas} != set(consolidado["usinas"]):
            problemas.append("O mapa NEWAVE de usinas não corresponde aos IDs do Parquet.")
        if {e["stage_id"] for e in mapa_estagios} != set(consolidado["ids_estagios"]):
            problemas.append("O mapa NEWAVE de estágios não corresponde aos IDs do Parquet.")
        for u in mapa_usinas:
            if u["hydro_id"] in nomes and normalizar_nome_usina(nomes[u["hydro_id"]]) != normalizar_nome_usina(u["nome_usina_cadastro"]):
                problemas.append(f"hydro_id {u['hydro_id']}: nome incompatível com a referência usada na conversão NEWAVE.")
        for e in mapa_estagios:
            etapa = calendario.get(e["stage_id"])
            if etapa and (str(etapa["inicio"]) != e["start_date"] or str(etapa["fim"]) != e["end_date"]):
                problemas.append(f"stage_id {e['stage_id']}: datas incompatíveis com a referência usada na conversão NEWAVE.")
    return problemas
