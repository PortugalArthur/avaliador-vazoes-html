"""Organiza cenarios e historico por UHE e estagio, sem executar testes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
from pathlib import Path

from infraestrutura.preparar_ambiente import garantir_dependencias

garantir_dependencias({"duckdb": "duckdb>=0.10", "pandas": "pandas>=2.0"})

import duckdb
import pandas as pd


NOMES_MESES = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}


@dataclass
class AmostraEstagio:
    """Vetores preparados para um futuro teste estatistico de um estagio."""

    hydro_id: int
    hydro_name: str
    stage_id: int
    start_date: date
    end_date: date
    year: int
    month: int
    month_name: str
    scenario_ids: pd.Series
    sintetico: pd.Series
    historico_datas: pd.Series
    historico: pd.Series


@dataclass
class OrganizacaoUsina:
    """Resultado completo da organizacao, ainda sem qualquer teste."""

    hydro_id: int
    hydro_name: str
    historico_inicio: pd.Period
    historico_fim: pd.Period
    meses_historicos_ausentes: tuple[pd.Period, ...]
    primeiro_estagio: date
    ultimo_estagio: date
    quantidade_cenarios: int
    quantidade_estagios: int
    amostras_por_estagio: dict[int, AmostraEstagio]
    resumo_estagios: pd.DataFrame


def _valores_finitos(valores: pd.Series) -> pd.Series:
    """Marca numeros finitos sem corrigir ou descartar os valores originais."""
    numericos = pd.to_numeric(valores, errors="coerce")
    return numericos.notna() & numericos.map(lambda valor: math.isfinite(float(valor)))


def carregar_cenarios(caminho: str | Path, hydro_id: int) -> pd.DataFrame:
    """Carrega somente as colunas necessarias da UHE selecionada."""
    conexao = duckdb.connect(database=":memory:")
    try:
        return conexao.execute(
            """
            SELECT scenario_id, stage_id, node_id, hydro_id,
                   incremental_inflow_m3s
            FROM read_parquet(?)
            WHERE hydro_id = ?
            ORDER BY stage_id, scenario_id, node_id
            """,
            [str(caminho), hydro_id],
        ).df()
    finally:
        conexao.close()


def carregar_historico(caminho: str | Path, hydro_id: int) -> pd.DataFrame:
    """Carrega a serie mensal historica da UHE selecionada."""
    conexao = duckdb.connect(database=":memory:")
    try:
        return conexao.execute(
            """
            SELECT hydro_id, TRY_CAST(start_date AS DATE) AS start_date,
                   TRY_CAST(end_date AS DATE) AS end_date, value_m3s
            FROM read_parquet(?)
            WHERE hydro_id = ?
            ORDER BY start_date
            """,
            [str(caminho), hydro_id],
        ).df()
    finally:
        conexao.close()


def _preparar_historico(
    dados: pd.DataFrame,
    hydro_id: int,
) -> tuple[pd.DataFrame, pd.Period, pd.Period, tuple[pd.Period, ...]]:
    """Identifica limites, lacunas e o mes real de cada observacao historica."""
    if dados.empty:
        raise ValueError(f"A UHE {hydro_id} nao possui registros historicos.")
    historico = dados.copy()
    historico["start_date"] = pd.to_datetime(historico["start_date"], errors="coerce")
    historico["end_date"] = pd.to_datetime(historico["end_date"], errors="coerce")
    if historico[["start_date", "end_date"]].isna().any().any():
        raise ValueError(f"A UHE {hydro_id} possui datas historicas invalidas.")
    historico["periodo"] = historico["start_date"].dt.to_period("M")
    if historico["periodo"].duplicated().any():
        repetido = historico.loc[historico["periodo"].duplicated(), "periodo"].iloc[0]
        raise ValueError(f"A UHE {hydro_id} possui o mes historico {repetido} repetido.")
    inicio = historico["periodo"].min()
    fim = historico["periodo"].max()
    intervalo = pd.period_range(inicio, fim, freq="M")
    presentes = set(historico["periodo"].tolist())
    ausentes = tuple(periodo for periodo in intervalo if periodo not in presentes)
    historico["year"] = historico["periodo"].map(lambda periodo: periodo.year)
    historico["month"] = historico["periodo"].map(lambda periodo: periodo.month)
    historico["value_m3s"] = pd.to_numeric(historico["value_m3s"], errors="coerce")
    historico["value_is_finite"] = _valores_finitos(historico["value_m3s"])
    return historico, inicio, fim, ausentes


def organizar_amostras_usina(
    consolidado: str | Path,
    historico: str | Path,
    hydro_id: int,
    nome: str,
    calendario: dict[int, dict],
) -> OrganizacaoUsina:
    """Forma os vetores historico e sintetico de todos os estagios da UHE."""
    cenarios = carregar_cenarios(consolidado, hydro_id)
    if cenarios.empty:
        raise ValueError(f"A UHE {hydro_id} nao possui cenarios no consolidado.")

    duplicados = cenarios.duplicated(["scenario_id", "stage_id"], keep=False)
    if duplicados.any():
        exemplo = cenarios.loc[duplicados].iloc[0]
        raise ValueError(
            f"A UHE {hydro_id} possui mais de uma linha para scenario_id "
            f"{int(exemplo['scenario_id'])} e stage_id {int(exemplo['stage_id'])}."
        )

    ids_estagios = {int(valor) for valor in cenarios["stage_id"].unique()}
    sem_calendario = sorted(ids_estagios - set(calendario))
    if sem_calendario:
        raise ValueError(
            "Estagios da UHE ausentes no stages.json: "
            + ", ".join(str(valor) for valor in sem_calendario)
        )
    estagios_ordenados = sorted(ids_estagios, key=lambda valor: calendario[valor]["ordem"])
    ordens = [calendario[stage_id]["ordem"] for stage_id in estagios_ordenados]
    for anterior, atual in zip(ordens, ordens[1:]):
        if atual != anterior + 1:
            raise ValueError("A UHE possui uma lacuna na sequencia de estagios sinteticos.")

    primeiro_stage = estagios_ordenados[0]
    cenarios_referencia = set(
        int(valor)
        for valor in cenarios.loc[
            cenarios["stage_id"].eq(primeiro_stage), "scenario_id"
        ].tolist()
    )
    if not cenarios_referencia:
        raise ValueError(f"O primeiro estagio da UHE {hydro_id} nao possui cenarios.")

    historico_bruto = carregar_historico(historico, hydro_id)
    historico_preparado, historico_inicio, historico_fim, meses_ausentes = _preparar_historico(
        historico_bruto, hydro_id
    )

    amostras = {}
    linhas_resumo = []
    for stage_id in estagios_ordenados:
        registro = calendario[stage_id]
        dados_stage = cenarios.loc[cenarios["stage_id"].eq(stage_id)].sort_values("scenario_id").copy()
        ids_stage = {int(valor) for valor in dados_stage["scenario_id"].tolist()}
        if ids_stage != cenarios_referencia:
            faltantes = sorted(cenarios_referencia - ids_stage)
            adicionais = sorted(ids_stage - cenarios_referencia)
            raise ValueError(
                f"O stage_id {stage_id} nao possui o mesmo conjunto de cenarios do primeiro estagio. "
                f"Ausentes: {faltantes[:20]}; adicionais: {adicionais[:20]}."
            )

        sintetico = pd.to_numeric(dados_stage["incremental_inflow_m3s"], errors="coerce")
        sintetico.index = dados_stage["scenario_id"].astype(int).tolist()
        sintetico.index.name = "scenario_id"
        sintetico.name = "incremental_inflow_m3s"
        sintetico_finito = _valores_finitos(sintetico)

        historico_mes = historico_preparado.loc[
            historico_preparado["month"].eq(registro["mes"])
        ].sort_values("start_date")
        vetor_historico = historico_mes.set_index("periodo")["value_m3s"].copy()
        vetor_historico.name = "value_m3s"
        historico_finito = _valores_finitos(vetor_historico)

        amostras[stage_id] = AmostraEstagio(
            hydro_id=hydro_id,
            hydro_name=nome,
            stage_id=stage_id,
            start_date=registro["inicio"],
            end_date=registro["fim"],
            year=registro["ano"],
            month=registro["mes"],
            month_name=NOMES_MESES[registro["mes"]],
            scenario_ids=dados_stage["scenario_id"].astype(int).reset_index(drop=True),
            sintetico=sintetico,
            historico_datas=historico_mes["start_date"].reset_index(drop=True),
            historico=vetor_historico,
        )

        status = "Pronto"
        if not sintetico_finito.all():
            status = "Valores sinteticos ausentes ou infinitos"
        if vetor_historico.empty:
            status = "Sem historico para o mes"
        elif not historico_finito.all():
            status = "Valores historicos ausentes ou infinitos"
        linhas_resumo.append(
            {
                "stage_id": stage_id,
                "inicio_estagio": registro["inicio"],
                "fim_estagio": registro["fim"],
                "ano": registro["ano"],
                "mes": registro["mes"],
                "mes_nome": NOMES_MESES[registro["mes"]],
                "n_sintetico": len(sintetico),
                "n_sintetico_valido": int(sintetico_finito.sum()),
                "n_historico": len(vetor_historico),
                "n_historico_valido": int(historico_finito.sum()),
                "primeiro_mes_historico_usado": (
                    historico_mes["periodo"].min() if not historico_mes.empty else None
                ),
                "ultimo_mes_historico_usado": (
                    historico_mes["periodo"].max() if not historico_mes.empty else None
                ),
                "status": status,
            }
        )

    return OrganizacaoUsina(
        hydro_id=hydro_id,
        hydro_name=nome,
        historico_inicio=historico_inicio,
        historico_fim=historico_fim,
        meses_historicos_ausentes=meses_ausentes,
        primeiro_estagio=calendario[estagios_ordenados[0]]["inicio"],
        ultimo_estagio=calendario[estagios_ordenados[-1]]["inicio"],
        quantidade_cenarios=len(cenarios_referencia),
        quantidade_estagios=len(estagios_ordenados),
        amostras_por_estagio=amostras,
        resumo_estagios=pd.DataFrame(linhas_resumo),
    )


def preparar_amostras_usina(
    consolidado: str | Path,
    historico: str | Path,
    hydro_id: int,
    nome: str,
    calendario: dict[int, dict],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compatibilidade temporaria com a primeira versao da base do projeto."""
    return carregar_cenarios(consolidado, hydro_id), carregar_historico(historico, hydro_id)


def organizar_amostras_dados(cenarios, historico_bruto, hydro_id, nome, calendario):
    """Adaptador em memória: mesmo organizador, evitando reler o Parquet por UHE."""
    if cenarios.empty:
        raise ValueError(f"A UHE {hydro_id} nao possui cenarios no consolidado.")

    duplicados = cenarios.duplicated(["scenario_id", "stage_id"], keep=False)
    if duplicados.any():
        exemplo = cenarios.loc[duplicados].iloc[0]
        raise ValueError(
            f"A UHE {hydro_id} possui mais de uma linha para scenario_id "
            f"{int(exemplo['scenario_id'])} e stage_id {int(exemplo['stage_id'])}."
        )

    ids_estagios = {int(valor) for valor in cenarios["stage_id"].unique()}
    sem_calendario = sorted(ids_estagios - set(calendario))
    if sem_calendario:
        raise ValueError(
            "Estagios da UHE ausentes no stages.json: "
            + ", ".join(str(valor) for valor in sem_calendario)
        )
    estagios_ordenados = sorted(ids_estagios, key=lambda valor: calendario[valor]["ordem"])
    ordens = [calendario[stage_id]["ordem"] for stage_id in estagios_ordenados]
    for anterior, atual in zip(ordens, ordens[1:]):
        if atual != anterior + 1:
            raise ValueError("A UHE possui uma lacuna na sequencia de estagios sinteticos.")

    primeiro_stage = estagios_ordenados[0]
    cenarios_referencia = set(
        int(valor)
        for valor in cenarios.loc[
            cenarios["stage_id"].eq(primeiro_stage), "scenario_id"
        ].tolist()
    )
    if not cenarios_referencia:
        raise ValueError(f"O primeiro estagio da UHE {hydro_id} nao possui cenarios.")

    historico_preparado, historico_inicio, historico_fim, meses_ausentes = _preparar_historico(
        historico_bruto, hydro_id
    )

    amostras = {}
    linhas_resumo = []
    for stage_id in estagios_ordenados:
        registro = calendario[stage_id]
        dados_stage = cenarios.loc[cenarios["stage_id"].eq(stage_id)].sort_values("scenario_id").copy()
        ids_stage = {int(valor) for valor in dados_stage["scenario_id"].tolist()}
        if ids_stage != cenarios_referencia:
            faltantes = sorted(cenarios_referencia - ids_stage)
            adicionais = sorted(ids_stage - cenarios_referencia)
            raise ValueError(
                f"O stage_id {stage_id} nao possui o mesmo conjunto de cenarios do primeiro estagio. "
                f"Ausentes: {faltantes[:20]}; adicionais: {adicionais[:20]}."
            )

        sintetico = pd.to_numeric(dados_stage["incremental_inflow_m3s"], errors="coerce")
        sintetico.index = dados_stage["scenario_id"].astype(int).tolist()
        sintetico.index.name = "scenario_id"
        sintetico.name = "incremental_inflow_m3s"
        sintetico_finito = _valores_finitos(sintetico)

        historico_mes = historico_preparado.loc[
            historico_preparado["month"].eq(registro["mes"])
        ].sort_values("start_date")
        vetor_historico = historico_mes.set_index("periodo")["value_m3s"].copy()
        vetor_historico.name = "value_m3s"
        historico_finito = _valores_finitos(vetor_historico)

        amostras[stage_id] = AmostraEstagio(
            hydro_id=hydro_id,
            hydro_name=nome,
            stage_id=stage_id,
            start_date=registro["inicio"],
            end_date=registro["fim"],
            year=registro["ano"],
            month=registro["mes"],
            month_name=NOMES_MESES[registro["mes"]],
            scenario_ids=dados_stage["scenario_id"].astype(int).reset_index(drop=True),
            sintetico=sintetico,
            historico_datas=historico_mes["start_date"].reset_index(drop=True),
            historico=vetor_historico,
        )

        status = "Pronto"
        if not sintetico_finito.all():
            status = "Valores sinteticos ausentes ou infinitos"
        if vetor_historico.empty:
            status = "Sem historico para o mes"
        elif not historico_finito.all():
            status = "Valores historicos ausentes ou infinitos"
        linhas_resumo.append(
            {
                "stage_id": stage_id,
                "inicio_estagio": registro["inicio"],
                "fim_estagio": registro["fim"],
                "ano": registro["ano"],
                "mes": registro["mes"],
                "mes_nome": NOMES_MESES[registro["mes"]],
                "n_sintetico": len(sintetico),
                "n_sintetico_valido": int(sintetico_finito.sum()),
                "n_historico": len(vetor_historico),
                "n_historico_valido": int(historico_finito.sum()),
                "primeiro_mes_historico_usado": (
                    historico_mes["periodo"].min() if not historico_mes.empty else None
                ),
                "ultimo_mes_historico_usado": (
                    historico_mes["periodo"].max() if not historico_mes.empty else None
                ),
                "status": status,
            }
        )

    return OrganizacaoUsina(
        hydro_id=hydro_id,
        hydro_name=nome,
        historico_inicio=historico_inicio,
        historico_fim=historico_fim,
        meses_historicos_ausentes=meses_ausentes,
        primeiro_estagio=calendario[estagios_ordenados[0]]["inicio"],
        ultimo_estagio=calendario[estagios_ordenados[-1]]["inicio"],
        quantidade_cenarios=len(cenarios_referencia),
        quantidade_estagios=len(estagios_ordenados),
        amostras_por_estagio=amostras,
        resumo_estagios=pd.DataFrame(linhas_resumo),
    )
