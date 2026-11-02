"""Localização e validação dos parâmetros PAR por UHE e estágio."""

from pathlib import Path
import json
import math

from infraestrutura.preparar_ambiente import garantir_dependencias
garantir_dependencias({"polars": "polars>=0.20"})
import polars as pl
from dados.validacao_dados_cobre import validar_hydros_json, validar_stages_json


ARQUIVOS_STOCHASTIC = ("inflow_ar_coefficients.parquet", "fitting_report.json",
                       "inflow_annual_component.parquet", "inflow_seasonal_stats.parquet")
CHAVES_PARAMETROS = ["hydro_id", "stage_id"]
ANUAIS = ["annual_coefficient", "annual_mean_m3s", "annual_std_m3s"]


def _exigir_arquivos(pasta, arquivos, orientacao):
    pasta = Path(pasta).resolve()
    faltantes = [str(a) for a in arquivos if not (pasta/a).is_file()]
    if faltantes:
        raise ValueError(f"{orientacao}\nPasta selecionada: {pasta}\nArquivos ausentes: {', '.join(faltantes)}")
    return pasta


def validar_pasta_deck(pasta):
    """A raiz de entrada contém os JSON de calendário, cadastro e configuração."""
    return _exigir_arquivos(pasta, ("config.json", "stages.json", "system/hydros.json"),
                            "Selecione a pasta raiz do DECK DE ENTRADA, que contém config.json, stages.json e system.")


def validar_pasta_saida(pasta):
    """A raiz da saída extraída contém simulation/hydros e stochastic."""
    pasta = _exigir_arquivos(pasta, ["stochastic/"+a for a in ARQUIVOS_STOCHASTIC],
                            "Selecione a pasta da SAÍDA EXTRAÍDA que contém simulation e stochastic. "
                            "Extraia output.zip antes de selecionar a pasta.")
    hydros = pasta/"simulation"/"hydros"
    if not hydros.is_dir() or not any(hydros.glob("scenario_id=*/data.parquet")):
        raise ValueError(f"A saída selecionada não contém simulation/hydros/scenario_id=.../data.parquet: {pasta}\n"
                         "Selecione a pasta que contém simulation e stochastic, não uma subpasta de cenário.")
    return hydros, pasta/"stochastic"


def _json(caminho):
    try:
        valor = json.loads(Path(caminho).read_text(encoding="utf-8-sig"))
    except (ValueError, OSError) as erro:
        raise ValueError(f"JSON inválido ou ilegível: {caminho}") from erro
    if not isinstance(valor, dict):
        raise ValueError(f"O JSON deve conter um objeto: {caminho}")
    return valor


def _inteiro(valor, descricao):
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ValueError(f"{descricao}: identificador/ordem deve ser inteiro, recebido {valor!r}.")
    return valor


def _numero(valor, descricao):
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
        raise ValueError(f"{descricao}: valor numérico ausente ou não finito.")
    return float(valor)


def _ler_tabela(caminho, colunas, chaves):
    try:
        tabela = pl.read_parquet(caminho, columns=colunas)
    except Exception as erro:
        raise ValueError(f"Não foi possível ler {caminho}; colunas exigidas: {', '.join(colunas)}") from erro
    registros, vistos = [], set()
    for linha in tabela.iter_rows(named=True):
        chave = tuple(_inteiro(linha[c], f"{Path(caminho).name}: {c}") for c in chaves)
        if chave in vistos:
            raise ValueError(f"{Path(caminho).name}: chave duplicada {chave}.")
        vistos.add(chave)
        for coluna in colunas:
            if coluna not in chaves:
                linha[coluna] = _numero(linha[coluna], f"{Path(caminho).name}: {coluna}, chave {chave}")
                if coluna.endswith("std_m3s") and linha[coluna] < 0:
                    raise ValueError(f"{Path(caminho).name}: desvio padrão negativo na chave {chave}.")
        registros.append(linha)
    return registros


def carregar_parametros_par(pasta_deck, pasta_stochastic):
    """Uma linha por UHE/estágio; p=0 só com confirmação do relatório sazonal."""
    deck = validar_pasta_deck(pasta_deck)
    stochastic = _exigir_arquivos(pasta_stochastic, ARQUIVOS_STOCHASTIC,
                                  "A pasta stochastic deve conter os quatro arquivos do ajuste PAR.")
    config, stages = _json(deck/"config.json"), _json(deck/"stages.json")
    estimation = config.get("estimation")
    if not isinstance(estimation, dict):
        raise ValueError("config.json deve conter estimation.max_order.")
    max_order = _inteiro(estimation.get("max_order"), "config.json: estimation.max_order")
    if max_order < 0:
        raise ValueError("config.json: max_order deve ser não negativo.")
    nomes = validar_hydros_json(deck/"system"/"hydros.json")
    calendario = validar_stages_json(deck/"stages.json")

    # O relatório mensal é indexado por season_id. Validar essa relação com
    # a data de cada estágio, sem supor que o horizonte começa em janeiro.
    definicoes = stages.get("season_definitions", {})
    seasons = definicoes.get("seasons", [])
    if definicoes.get("cycle_type") != "monthly" or not isinstance(seasons, list):
        raise ValueError("O ajuste deve ter sazonalidade mensal em stages.json.")
    meses = {}
    for season in seasons:
        if not isinstance(season, dict):
            raise ValueError("Estação mensal inválida em stages.json.")
        sid = _inteiro(season.get("id"), "season_id")
        mes = _inteiro(season.get("month_start"), "month_start")
        if sid in meses or not 1 <= mes <= 12:
            raise ValueError("Estações mensais duplicadas ou inválidas em stages.json.")
        meses[sid] = mes
    if set(meses) != set(range(12)) or set(meses.values()) != set(range(1,13)):
        raise ValueError("O relatório mensal exige season_id de 0 a 11, associados aos 12 meses em stages.json.")
    por_estagio = {}
    for stage in stages["stages"]:
        sid = _inteiro(stage.get("season_id"), f"Estágio {stage['id']}: season_id")
        if sid not in meses or meses[sid] != calendario[stage["id"]]["mes"]:
            raise ValueError(f"Estágio {stage['id']}: estação incompatível com o mês do calendário.")
        por_estagio[stage["id"]] = sid

    ar = _ler_tabela(stochastic/ARQUIVOS_STOCHASTIC[0], CHAVES_PARAMETROS+["lag", "coefficient"],
                     CHAVES_PARAMETROS+["lag"])
    anuais = _ler_tabela(stochastic/"inflow_annual_component.parquet", CHAVES_PARAMETROS+ANUAIS, CHAVES_PARAMETROS)
    sazonais = _ler_tabela(stochastic/"inflow_seasonal_stats.parquet", CHAVES_PARAMETROS+["mean_m3s", "std_m3s"], CHAVES_PARAMETROS)
    relatorio = _json(stochastic/"fitting_report.json").get("hydros")
    if not isinstance(relatorio, dict):
        raise ValueError("fitting_report.json deve conter o objeto hydros.")
    annual = {(r["hydro_id"],r["stage_id"]):r for r in anuais}
    pares = {(r["hydro_id"],r["stage_id"]) for r in sazonais}
    if not pares or set(annual) != pares:
        raise ValueError("As tabelas anual e sazonal devem conter os mesmos pares de UHE e estágio, sem ausências.")
    for u, e in pares:
        if u not in nomes or e not in calendario:
            raise ValueError(f"UHE/estágio {(u,e)} da saída ausente no deck de entrada selecionado.")
    coeficientes = {}
    for r in ar:
        chave = (r["hydro_id"],r["stage_id"])
        if chave not in pares or not 1 <= r["lag"] <= max_order:
            raise ValueError(f"Coeficiente AR com chave/lag incompatível com o deck: {chave}, lag {r['lag']}.")
        coeficientes.setdefault(chave,{})[r["lag"]] = r["coefficient"]

    colunas_ar = [f"ar_coefficient_lag_{i}" for i in range(1,max_order+1)]
    colunas = ["ar_order"]+colunas_ar+ANUAIS+["seasonal_mean_m3s", "seasonal_std_m3s"]
    linhas = []
    for r in sazonais:
        chave = (r["hydro_id"],r["stage_id"])
        registro = relatorio.get(str(chave[0]), {})
        listas = registro.get("coefficients") if isinstance(registro, dict) else None
        if not isinstance(listas,list) or len(listas) != 12:
            raise ValueError(f"Relatório sem as 12 listas de coeficientes para a UHE {chave[0]}.")
        esperados = listas[por_estagio[chave[1]]]
        if not isinstance(esperados,list) or len(esperados) > max_order:
            raise ValueError(f"Ordem mensal inválida no relatório para a UHE/estágio {chave}.")
        observados = coeficientes.get(chave,{})
        if set(observados) != set(range(1,len(esperados)+1)):
            raise ValueError(f"Coeficientes AR ausentes ou divergentes do relatório na UHE/estágio {chave}. "
                             "Uma ausência inesperada não pode ser convertida em p=0.")
        for lag, esperado in enumerate(esperados,1):
            esperado = _numero(esperado,f"Coeficiente do relatório: {chave}, lag {lag}")
            if not math.isclose(observados[lag],esperado,rel_tol=1e-10,abs_tol=1e-12):
                raise ValueError(f"Coeficiente do relatório difere do Parquet na UHE/estágio {chave}, lag {lag}.")
        # O maior lag efetivo define p. Lista vazia confirma p=0; selected_order
        # não substitui a ordem mensal. Lags não utilizados são nulos, não zeros.
        linha = dict(hydro_id=chave[0],stage_id=chave[1],ar_order=max(observados,default=0))
        linha.update({col:observados.get(i) for i,col in enumerate(colunas_ar,1)})
        linha.update({col:annual[chave][col] for col in ANUAIS})
        linha.update(seasonal_mean_m3s=r["mean_m3s"],seasonal_std_m3s=r["std_m3s"])
        linhas.append(linha)
    schema = {"hydro_id":pl.Int64,"stage_id":pl.Int64,"ar_order":pl.Int32}
    schema.update({c:pl.Float64 for c in colunas if c != "ar_order"})
    return pl.DataFrame(linhas,schema=schema).select(CHAVES_PARAMETROS+colunas), colunas
