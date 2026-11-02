"""Calcula e exporta o teste de Welch para todas as UHEs e estagios."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from infraestrutura.preparar_ambiente import garantir_dependencias

garantir_dependencias(
    {
        "duckdb": "duckdb>=0.10",
        "pandas": "pandas>=2.0",
        "xlsxwriter": "XlsxWriter>=3.2",
    }
)

import duckdb
import pandas as pd

from calculos.base_estatistica_cobre import NOMES_MESES
from calculos.teste_welch_cobre import avaliar_welch_resumo


def _estatisticas_sinteticas(caminho: str | Path) -> pd.DataFrame:
    """Le o parquet uma unica vez e resume cada combinacao UHE-estagio."""
    conexao = duckdb.connect(database=":memory:")
    try:
        return conexao.execute(
            """
            WITH dados AS (
                SELECT
                    hydro_id,
                    stage_id,
                    scenario_id,
                    TRY_CAST(incremental_inflow_m3s AS DOUBLE) AS valor
                FROM read_parquet(?)
            )
            SELECT
                hydro_id,
                stage_id,
                COUNT(*) AS n_linhas,
                COUNT(DISTINCT scenario_id) AS n_sintetico,
                COUNT(*) FILTER (WHERE valor IS NOT NULL AND ISFINITE(valor)) AS n_validos,
                AVG(valor) FILTER (WHERE valor IS NOT NULL AND ISFINITE(valor)) AS media_sintetica,
                VAR_SAMP(valor) FILTER (WHERE valor IS NOT NULL AND ISFINITE(valor)) AS variancia_sintetica
            FROM dados
            GROUP BY hydro_id, stage_id
            ORDER BY hydro_id, stage_id
            """,
            [str(Path(caminho).resolve())],
        ).df()
    finally:
        conexao.close()


def _estatisticas_historicas(caminho: str | Path) -> pd.DataFrame:
    """Resume o historico por UHE e mes do calendario."""
    conexao = duckdb.connect(database=":memory:")
    try:
        return conexao.execute(
            """
            WITH dados AS (
                SELECT
                    hydro_id,
                    EXTRACT(MONTH FROM TRY_CAST(start_date AS DATE))::INTEGER AS mes,
                    TRY_CAST(value_m3s AS DOUBLE) AS valor
                FROM read_parquet(?)
            )
            SELECT
                hydro_id,
                mes,
                COUNT(*) AS n_linhas_historicas,
                COUNT(*) FILTER (WHERE valor IS NOT NULL AND ISFINITE(valor)) AS n_historico,
                AVG(valor) FILTER (WHERE valor IS NOT NULL AND ISFINITE(valor)) AS media_historica,
                VAR_SAMP(valor) FILTER (WHERE valor IS NOT NULL AND ISFINITE(valor)) AS variancia_historica
            FROM dados
            GROUP BY hydro_id, mes
            ORDER BY hydro_id, mes
            """,
            [str(Path(caminho).resolve())],
        ).df()
    finally:
        conexao.close()


def calcular_welch_todas_usinas(
    caminho_consolidado: str | Path,
    caminho_historico: str | Path,
    nomes: dict[int, str],
    calendario: dict[int, dict],
    alfa: float = 0.05,
) -> pd.DataFrame:
    """Executa um Welch para toda combinacao UHE-estagio encontrada."""
    sintetico = _estatisticas_sinteticas(caminho_consolidado)
    historico = _estatisticas_historicas(caminho_historico)

    linhas = []
    for registro in sintetico.itertuples(index=False):
        hydro_id = int(registro.hydro_id)
        stage_id = int(registro.stage_id)
        etapa = calendario.get(stage_id)
        identificacao = {
            "hydro_id": hydro_id,
            "nome_usina": nomes.get(hydro_id, "Usina sem nome"),
            "stage_id": stage_id,
        }

        if etapa is None:
            linhas.append(
                {**identificacao, "status_teste": "Estagio ausente no stages.json"}
            )
            continue

        identificacao.update(
            {
                "inicio_estagio": etapa["inicio"],
                "fim_estagio": etapa["fim"],
                "ano": etapa["ano"],
                "mes": etapa["mes"],
                "mes_nome": NOMES_MESES[etapa["mes"]],
                "ordem_estagio": etapa["ordem"],
            }
        )

        if int(registro.n_linhas) != int(registro.n_sintetico):
            linhas.append(
                {**identificacao, "status_teste": "Cenarios repetidos na UHE e estagio"}
            )
            continue
        if int(registro.n_validos) != int(registro.n_linhas):
            linhas.append(
                {**identificacao, "status_teste": "Valores sinteticos ausentes ou infinitos"}
            )
            continue

        historico_mes = historico.loc[
            historico["hydro_id"].eq(hydro_id) & historico["mes"].eq(etapa["mes"])
        ]
        if historico_mes.empty:
            linhas.append(
                {**identificacao, "status_teste": "Sem historico para o mes"}
            )
            continue

        resumo_historico = historico_mes.iloc[0]
        if int(resumo_historico["n_historico"]) != int(
            resumo_historico["n_linhas_historicas"]
        ):
            linhas.append(
                {**identificacao, "status_teste": "Valores historicos ausentes ou infinitos"}
            )
            continue

        try:
            resultado = avaliar_welch_resumo(
                resumo_historico["n_historico"],
                resumo_historico["media_historica"],
                resumo_historico["variancia_historica"],
                registro.n_sintetico,
                registro.media_sintetica,
                registro.variancia_sintetica,
                alfa=alfa,
            )
        except ValueError as erro:
            linhas.append({**identificacao, "status_teste": str(erro)})
            continue

        linhas.append({**identificacao, **resultado, "status_teste": "Calculado"})

    resultados = pd.DataFrame(linhas)
    if not resultados.empty:
        # Garante um esquema estavel mesmo se nenhuma combinacao puder ser calculada.
        for coluna in (
            "rejeita_igualdade", "p_valor", "n_historico", "n_sintetico",
            "media_historica", "media_sintetica", "variancia_historica",
            "variancia_sintetica", "desvio_padrao_historico",
            "desvio_padrao_sintetico", "diferenca_m3s", "erro_padrao", "t",
            "graus_liberdade", "alfa", "t_critico", "margem_erro",
            "ic_inferior", "ic_superior",
        ):
            if coluna not in resultados:
                resultados[coluna] = pd.NA
        resultados = resultados.sort_values(
            ["nome_usina", "hydro_id", "ordem_estagio"],
            na_position="last",
        ).reset_index(drop=True)
    return resultados


def resumir_reprovacoes_por_estagio(resultados: pd.DataFrame) -> pd.DataFrame:
    """Conta as reprovacoes de todas as UHEs em cada estagio."""
    validos = resultados.loc[resultados["status_teste"].eq("Calculado")].copy()
    if validos.empty:
        return pd.DataFrame(
            columns=[
                "stage_id", "inicio_estagio", "mes_nome", "combinacoes_testadas",
                "combinacoes_reprovadas", "percentual_reprovado",
            ]
        )

    resumo = (
        validos.groupby(
            ["ordem_estagio", "stage_id", "inicio_estagio", "mes_nome"],
            as_index=False,
        )
        .agg(
            combinacoes_testadas=("hydro_id", "size"),
            combinacoes_reprovadas=("rejeita_igualdade", "sum"),
        )
        .sort_values("ordem_estagio")
    )
    resumo["combinacoes_reprovadas"] = resumo["combinacoes_reprovadas"].astype(int)
    resumo["percentual_reprovado"] = (
        100 * resumo["combinacoes_reprovadas"] / resumo["combinacoes_testadas"]
    )
    return resumo.loc[resumo["combinacoes_reprovadas"].gt(0)].reset_index(drop=True)


def gerar_excel_welch(
    resultados: pd.DataFrame,
    resumo_estagios: pd.DataFrame,
    alfa: float,
) -> bytes:
    """Gera uma pasta de trabalho formatada, mantendo numeros como numeros."""
    validos = resultados["status_teste"].eq("Calculado")
    reprovados = validos & resultados["rejeita_igualdade"].fillna(False)
    indicadores = pd.DataFrame(
        {
            "Indicador": [
                "Nível de significância (alfa)",
                "Combinações UHE-estágio calculadas",
                "Combinações UHE-estágio reprovadas",
                "UHEs com ao menos uma reprovação",
                "Combinações que não puderam ser calculadas",
            ],
            "Valor": [
                alfa,
                int(validos.sum()),
                int(reprovados.sum()),
                int(resultados.loc[reprovados, "hydro_id"].nunique()),
                int((~validos).sum()),
            ],
        }
    )

    colunas = [
        "hydro_id", "nome_usina", "stage_id", "inicio_estagio", "fim_estagio",
        "ano", "mes", "mes_nome", "n_historico", "n_sintetico",
        "media_historica", "media_sintetica", "variancia_historica",
        "variancia_sintetica", "desvio_padrao_historico",
        "desvio_padrao_sintetico", "diferenca_m3s", "erro_padrao", "t",
        "graus_liberdade", "p_valor", "alfa", "t_critico", "margem_erro",
        "ic_inferior", "ic_superior", "rejeita_igualdade", "status_teste",
    ]
    exportacao = resultados.reindex(columns=colunas).copy()
    exportacao["rejeita_igualdade"] = exportacao["rejeita_igualdade"].map(
        {True: "Reprovado", False: "Não reprovado"}
    )
    nomes_colunas = {
        "hydro_id": "ID da UHE",
        "nome_usina": "Usina",
        "stage_id": "ID do estágio",
        "inicio_estagio": "Início do estágio",
        "fim_estagio": "Fim do estágio",
        "ano": "Ano",
        "mes": "Mês",
        "mes_nome": "Nome do mês",
        "n_historico": "N histórico",
        "n_sintetico": "N sintético",
        "media_historica": "Média histórica (m³/s)",
        "media_sintetica": "Média sintética (m³/s)",
        "variancia_historica": "Variância histórica",
        "variancia_sintetica": "Variância sintética",
        "desvio_padrao_historico": "Desvio padrão histórico (m³/s)",
        "desvio_padrao_sintetico": "Desvio padrão sintético (m³/s)",
        "diferenca_m3s": "Diferença sintético - histórico (m³/s)",
        "erro_padrao": "Erro padrão",
        "t": "Estatística t",
        "graus_liberdade": "Graus de liberdade",
        "p_valor": "p-valor",
        "alfa": "Alfa",
        "t_critico": "t crítico",
        "margem_erro": "Margem de erro",
        "ic_inferior": "IC inferior",
        "ic_superior": "IC superior",
        "rejeita_igualdade": "Resultado",
        "status_teste": "Status do teste",
    }
    exportacao = exportacao.rename(columns=nomes_colunas)

    resumo_exportacao = resumo_estagios.drop(columns="ordem_estagio", errors="ignore").rename(
        columns={
            "stage_id": "ID do estágio",
            "inicio_estagio": "Início do estágio",
            "mes_nome": "Nome do mês",
            "combinacoes_testadas": "Combinações testadas",
            "combinacoes_reprovadas": "Combinações reprovadas",
            "percentual_reprovado": "Percentual reprovado (%)",
        }
    )

    saida = BytesIO()
    with pd.ExcelWriter(
        saida,
        engine="xlsxwriter",
        date_format="dd/mm/yyyy",
        datetime_format="dd/mm/yyyy",
    ) as escritor:
        indicadores.to_excel(escritor, sheet_name="Resumo geral", index=False, startrow=2)
        resumo_exportacao.to_excel(escritor, sheet_name="Reprovações por estágio", index=False)
        exportacao.to_excel(escritor, sheet_name="Resultados completos", index=False)

        pasta = escritor.book
        cabecalho = pasta.add_format(
            {"bold": True, "font_color": "white", "bg_color": "#4C1D95", "border": 1}
        )
        titulo = pasta.add_format(
            {"bold": True, "font_size": 16, "font_color": "#4C1D95"}
        )
        # Sem separador de milhar. O ponto decimal do formato interno e exibido
        # como virgula quando o Excel usa a configuracao regional pt-BR.
        inteiro = pasta.add_format({"num_format": "0"})
        decimal = pasta.add_format({"num_format": "0.000000"})
        percentual = pasta.add_format({"num_format": "0.00\"%\""})
        data = pasta.add_format({"num_format": "dd/mm/yyyy"})
        reprovado = pasta.add_format({"bg_color": "#FECACA", "font_color": "#991B1B"})

        aba_resumo = escritor.sheets["Resumo geral"]
        aba_resumo.write("A1", "Teste de Welch para todas as usinas", titulo)
        aba_resumo.set_column("A:A", 46)
        aba_resumo.set_column("B:B", 22, decimal)
        aba_resumo.freeze_panes(3, 0)
        for coluna, valor in enumerate(indicadores.columns):
            aba_resumo.write(2, coluna, valor, cabecalho)

        aba_estagios = escritor.sheets["Reprovações por estágio"]
        aba_estagios.freeze_panes(1, 0)
        aba_estagios.autofilter(0, 0, max(len(resumo_exportacao), 1), max(len(resumo_exportacao.columns) - 1, 0))
        aba_estagios.set_column("A:A", 14, inteiro)
        aba_estagios.set_column("B:B", 17, data)
        aba_estagios.set_column("C:C", 18)
        aba_estagios.set_column("D:E", 24, inteiro)
        aba_estagios.set_column("F:F", 24, percentual)
        for coluna, valor in enumerate(resumo_exportacao.columns):
            aba_estagios.write(0, coluna, valor, cabecalho)

        aba_dados = escritor.sheets["Resultados completos"]
        aba_dados.freeze_panes(1, 2)
        aba_dados.autofilter(0, 0, max(len(exportacao), 1), len(exportacao.columns) - 1)
        aba_dados.set_column(0, len(exportacao.columns) - 1, 16)
        aba_dados.set_column(1, 1, 32)
        aba_dados.set_column(3, 4, 17, data)
        aba_dados.set_column(10, 25, 19, decimal)
        aba_dados.set_column(27, 27, 42)
        for coluna, valor in enumerate(exportacao.columns):
            aba_dados.write(0, coluna, valor, cabecalho)
        if not exportacao.empty:
            coluna_resultado = exportacao.columns.get_loc("Resultado")
            aba_dados.conditional_format(
                1,
                coluna_resultado,
                len(exportacao),
                coluna_resultado,
                {"type": "text", "criteria": "containing", "value": "Reprovado", "format": reprovado},
            )

    return saida.getvalue()
