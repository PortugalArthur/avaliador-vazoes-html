"""Correlação de Pearson entre UHEs no mesmo estágio e cenário."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from infraestrutura.preparar_ambiente import garantir_dependencias

garantir_dependencias({
    "duckdb": "duckdb>=0.10",
    "pandas": "pandas>=2.0",
    "xlsxwriter": "XlsxWriter>=3.2",
})

import duckdb
import numpy as np
import pandas as pd
import xlsxwriter
from dados.metadados_vazoes import ler_metadados_vazoes


VERSAO_CORRELACAO_ESPACIAL = 2
COLUNAS_FONTE = (
    "scenario_id", "stage_id", "node_id", "hydro_id",
    "incremental_inflow_m3s",
)
MOTIVOS = {
    0: "",
    1: "Menos de dois pares finitos.",
    2: "Vazão de uma das UHEs constante entre os pares.",
    3: "Valores quase constantes; correlação numericamente instável.",
    4: "Coeficiente numericamente inválido ou fora de [-1, 1].",
    5: "Comparação da UHE consigo mesma não exibida.",
}


@dataclass
class ResultadoEspacial:
    """Matrizes pequenas por estágio; não conserva os 23 milhões de vazões."""

    stage_ids: tuple[int, ...]
    hydro_ids: tuple[int, ...]
    nomes: dict[int, str]
    pares_esperados: np.ndarray
    pares_validos: np.ndarray
    correlacoes: np.ndarray
    medias: np.ndarray
    desvios: np.ndarray
    covariancias: np.ndarray
    estados: np.ndarray
    grupos_presentes: np.ndarray

    def posicoes(self, stage_id: int, referencia: int, comparada: int) -> tuple[int, int, int]:
        try:
            return (
                self.stage_ids.index(int(stage_id)),
                self.hydro_ids.index(int(referencia)),
                self.hydro_ids.index(int(comparada)),
            )
        except ValueError as erro:
            raise ValueError("UHE ou estágio ausente no resultado espacial.") from erro


def _identificadores(conexao: duckdb.DuckDBPyConnection, caminho: str, stage_id: int | None):
    descricao = conexao.execute("DESCRIBE SELECT * FROM read_parquet(?)", [caminho]).fetchall()
    faltantes = sorted(set(COLUNAS_FONTE) - {linha[0] for linha in descricao})
    if faltantes:
        raise ValueError("O Parquet não possui as colunas da correlação espacial: " + ", ".join(faltantes))
    filtro = " WHERE stage_id = ?" if stage_id is not None else ""
    lista = conexao.execute(
        "SELECT list_sort(list(DISTINCT scenario_id)), "
        "list_sort(list(DISTINCT stage_id)), "
        "list_sort(list(DISTINCT hydro_id)) "
        "FROM read_parquet(?)" + filtro,
        [caminho] + ([int(stage_id)] if stage_id is not None else []),
    ).fetchall()[0]
    if any(not valores or any(valor is None for valor in valores) for valores in lista):
        raise ValueError("Cenário, estágio ou UHE ausente nos identificadores do Parquet.")
    return tuple(int(v) for v in lista[0]), tuple(int(v) for v in lista[1]), tuple(int(v) for v in lista[2])


def _carregar_vazoes(
    caminho: str, calendario: dict[int, dict], stage_id: int | None,
) -> tuple[tuple[int, ...], tuple[int, ...], np.ndarray, np.ndarray, np.ndarray]:
    conexao = duckdb.connect(database=":memory:")
    try:
        origem = ler_metadados_vazoes(caminho)
        cenarios, estagios, usinas = _identificadores(conexao, caminho, stage_id)
        sem_calendario = set(estagios) - set(calendario)
        if sem_calendario:
            raise ValueError("Estágios sem data no stages.json: " + ", ".join(map(str, sorted(sem_calendario))))
        estagios = tuple(sorted(estagios, key=lambda valor: calendario[valor]["ordem"]))
        qtd_estagios, qtd_cenarios, qtd_usinas = len(estagios), len(cenarios), len(usinas)
        forma = (qtd_estagios, qtd_cenarios, qtd_usinas)
        vazoes = np.full(forma, np.nan, dtype=np.float64)
        presentes = np.zeros(forma, dtype=np.bool_)
        stage_index = pd.Index(estagios)
        scenario_index = pd.Index(cenarios)
        hydro_index = pd.Index(usinas)
        filtro = " WHERE stage_id = ?" if stage_id is not None else ""
        consulta = (
            "SELECT scenario_id, stage_id, hydro_id, node_id, incremental_inflow_m3s "
            "FROM read_parquet(?)" + filtro
        )
        cursor = conexao.execute(consulta, [caminho] + ([int(stage_id)] if stage_id is not None else []))
        while True:
            bloco = cursor.fetch_df_chunk(128)
            if bloco.empty:
                break
            chaves_obrigatorias = ["scenario_id", "stage_id", "hydro_id"]
            if not origem["node_id_ausente"]:
                chaves_obrigatorias.append("node_id")
            elif bloco.node_id.notna().any():
                raise ValueError("O Parquet NEWAVE deve manter node_id nulo.")
            if bloco[chaves_obrigatorias].isna().any().any():
                raise ValueError("O Parquet contém scenario_id, stage_id, hydro_id ou node_id ausente.")
            s = stage_index.get_indexer(bloco["stage_id"])
            c = scenario_index.get_indexer(bloco["scenario_id"])
            h = hydro_index.get_indexer(bloco["hydro_id"])
            if np.any(s < 0) or np.any(c < 0) or np.any(h < 0):
                raise ValueError("Identificador não encontrado durante o pareamento espacial.")
            chaves = (s * qtd_cenarios + c) * qtd_usinas + h
            unicas, contagens = np.unique(chaves, return_counts=True)
            if np.any(contagens > 1) or np.any(presentes.ravel()[unicas]):
                raise ValueError("Chave hydro_id × stage_id × scenario_id duplicada no Parquet.")
            valores = bloco["incremental_inflow_m3s"].to_numpy(dtype=np.float64, na_value=np.nan)
            vazoes.ravel()[chaves] = valores
            presentes.ravel()[chaves] = True
        grupos = presentes.any(axis=1)
        esperados = presentes.any(axis=2).sum(axis=1).astype(np.int32)
        return estagios, usinas, vazoes, grupos, esperados
    finally:
        conexao.close()


def _calcular_estagio(vazoes: np.ndarray) -> tuple[np.ndarray, ...]:
    """Momentos centralizados por interseção de cenários, usando matrizes simétricas."""
    valido = np.isfinite(vazoes)
    mascara = valido.astype(np.float64)
    n_usinas = vazoes.shape[1]
    centros = np.zeros(n_usinas, dtype=np.float64)
    for indice in range(n_usinas):
        valores = vazoes[valido[:, indice], indice]
        if valores.size:
            centros[indice] = np.mean(valores)
    centrados = np.where(valido, vazoes - centros, 0.0)
    n = mascara.T @ mascara
    soma = centrados.T @ mascara
    soma_quadrados = (centrados * centrados).T @ mascara
    produtos = centrados.T @ centrados
    with np.errstate(invalid="ignore", divide="ignore"):
        medias = centros[:, None] + soma / n
        variancias_numerador = soma_quadrados - soma * soma / n
        covariancias_numerador = produtos - soma * soma.T / n
        covariancias_numerador = (covariancias_numerador + covariancias_numerador.T) / 2
        desvios = np.sqrt(np.maximum(variancias_numerador / n, 0.0))
        covariancias = covariancias_numerador / n
        correlacoes = covariancias_numerador / np.sqrt(
            variancias_numerador * variancias_numerador.T
        )
    estados = np.zeros((n_usinas, n_usinas), dtype=np.uint8)
    estados[n < 2] = 1
    constante = (variancias_numerador <= 0) | (variancias_numerador.T <= 0)
    estados[(estados == 0) & constante] = 2
    with np.errstate(invalid="ignore"):
        quase_constante = (
            (desvios * np.sqrt(n) < 1e-13 * np.abs(medias))
            | (desvios.T * np.sqrt(n) < 1e-13 * np.abs(medias.T))
        )
    estados[(estados == 0) & quase_constante] = 3
    ruim = ~np.isfinite(correlacoes) | (np.abs(correlacoes) > 1 + 1e-10)
    estados[(estados == 0) & ruim] = 4
    correlacoes = np.clip(correlacoes, -1.0, 1.0)
    correlacoes[estados != 0] = np.nan
    np.fill_diagonal(correlacoes, np.nan)
    np.fill_diagonal(estados, 5)
    return (
        n.astype(np.int32), correlacoes, medias, desvios,
        covariancias, estados,
    )


def _calcular_estagio_referencia(vazoes: np.ndarray, referencia: int) -> tuple[np.ndarray, ...]:
    """Calcula apenas os pares da UHE exibida no gráfico."""
    n_usinas = vazoes.shape[1]
    n_matriz = np.zeros((n_usinas, n_usinas), dtype=np.int32)
    coeficientes = np.full((n_usinas, n_usinas), np.nan)
    medias = np.full((n_usinas, n_usinas), np.nan)
    desvios = np.full((n_usinas, n_usinas), np.nan)
    covariancias = np.full((n_usinas, n_usinas), np.nan)
    estados = np.ones((n_usinas, n_usinas), dtype=np.uint8)
    x = vazoes[:, referencia]
    valido_x = np.isfinite(x)
    mascara = np.isfinite(vazoes)
    pares = mascara & valido_x[:, None]
    n = pares.sum(axis=0).astype(np.int32)
    with np.errstate(invalid="ignore", divide="ignore"):
        soma_x = np.where(pares, x[:, None], 0.0).sum(axis=0)
        soma_y = np.where(pares, vazoes, 0.0).sum(axis=0)
        media_x = soma_x / n
        media_y = soma_y / n
        dx = np.where(pares, x[:, None] - media_x, 0.0)
        dy = np.where(pares, vazoes - media_y, 0.0)
        var_x = np.sum(dx * dx, axis=0)
        var_y = np.sum(dy * dy, axis=0)
        cov_num = np.sum(dx * dy, axis=0)
        desvio_x = np.sqrt(var_x / n)
        desvio_y = np.sqrt(var_y / n)
        cov = cov_num / n
        rho = cov_num / np.sqrt(var_x * var_y)
    estado = np.zeros(n_usinas, dtype=np.uint8)
    estado[n < 2] = 1
    estado[(estado == 0) & ((var_x <= 0) | (var_y <= 0))] = 2
    quase_constante = (
        (desvio_x * np.sqrt(n) < 1e-13 * np.abs(media_x))
        | (desvio_y * np.sqrt(n) < 1e-13 * np.abs(media_y))
    )
    estado[(estado == 0) & quase_constante] = 3
    estado[(estado == 0) & (~np.isfinite(rho) | (np.abs(rho) > 1 + 1e-10))] = 4
    rho = np.clip(rho, -1.0, 1.0)
    rho[estado != 0] = np.nan
    n_matriz[referencia, :] = n
    n_matriz[:, referencia] = n
    coeficientes[referencia, :] = rho
    coeficientes[:, referencia] = rho
    medias[referencia, :] = media_x
    medias[:, referencia] = media_y
    desvios[referencia, :] = desvio_x
    desvios[:, referencia] = desvio_y
    covariancias[referencia, :] = cov
    covariancias[:, referencia] = cov
    estados[referencia, :] = estado
    estados[:, referencia] = estado
    coeficientes[referencia, referencia] = np.nan
    estados[referencia, referencia] = 5
    return n_matriz, coeficientes, medias, desvios, covariancias, estados


def gerar_correlacao_espacial(
    caminho: str, nomes_por_id: dict[int, str],
    calendario: dict[int, dict], stage_id: int | None = None,
    hydro_id_referencia: int | None = None,
) -> ResultadoEspacial:
    """Mesma rotina estatística para um estágio do gráfico ou todo o relatório."""
    if not calendario:
        raise ValueError("Selecione o stages.json para a correlação espacial.")
    estagios, usinas, vazoes, grupos, esperados = _carregar_vazoes(caminho, calendario, stage_id)
    if hydro_id_referencia is not None and stage_id is None:
        raise ValueError("Informe um estágio para calcular apenas a UHE de referência.")
    if hydro_id_referencia is not None and hydro_id_referencia not in usinas:
        raise ValueError(f"hydro_id {hydro_id_referencia} ausente no estágio selecionado.")
    forma = (len(estagios), len(usinas), len(usinas))
    pares = np.empty(forma, dtype=np.int32)
    correlacoes = np.empty(forma, dtype=np.float64)
    medias = np.empty(forma, dtype=np.float64)
    desvios = np.empty(forma, dtype=np.float64)
    covariancias = np.empty(forma, dtype=np.float64)
    estados = np.empty(forma, dtype=np.uint8)
    for indice in range(len(estagios)):
        resultado = (
            _calcular_estagio_referencia(vazoes[indice], usinas.index(hydro_id_referencia))
            if hydro_id_referencia is not None else _calcular_estagio(vazoes[indice])
        )
        for destino, origem in zip(
            (pares, correlacoes, medias, desvios, covariancias, estados), resultado
        ):
            destino[indice] = origem
    del vazoes
    nomes = {
        hydro_id: nomes_por_id.get(hydro_id, f"Usina sem nome — hydro_id {hydro_id}")
        for hydro_id in usinas
    }
    return ResultadoEspacial(
        estagios, usinas, nomes, esperados, pares, correlacoes,
        medias, desvios, covariancias, estados, grupos,
    )


def diagnosticar_par(
    resultado: ResultadoEspacial, stage_id: int, referencia: int, comparada: int,
) -> dict:
    s, u, v = resultado.posicoes(stage_id, referencia, comparada)
    estado = int(resultado.estados[s, u, v])

    def finito(valor):
        return float(valor) if np.isfinite(valor) else None

    return {
        "stage_id": stage_id,
        "hydro_id referência": referencia,
        "UHE referência": resultado.nomes[referencia],
        "hydro_id comparada": comparada,
        "UHE comparada": resultado.nomes[comparada],
        "Pares esperados": int(resultado.pares_esperados[s]),
        "Pares válidos": int(resultado.pares_validos[s, u, v]),
        "Média referência (m³/s)": finito(resultado.medias[s, u, v]),
        "Média comparada (m³/s)": finito(resultado.medias[s, v, u]),
        "Desvio referência (m³/s)": finito(resultado.desvios[s, u, v]),
        "Desvio comparada (m³/s)": finito(resultado.desvios[s, v, u]),
        "Covariância (m⁶/s²)": finito(resultado.covariancias[s, u, v]),
        "Correlação": finito(resultado.correlacoes[s, u, v]),
        "Status": "calculado" if estado == 0 else "indisponível",
        "Motivo": MOTIVOS[estado],
    }


def tabela_espacial(
    resultado: ResultadoEspacial,
    referencias: list[int] | None = None,
    estagios: list[int] | None = None,
) -> pd.DataFrame:
    """Cabeçalhos fixos por hydro_id e uma célula diagonal vazia por linha."""
    r = sorted(resultado.hydro_ids.index(v) for v in referencias) if referencias else list(range(len(resultado.hydro_ids)))
    s = sorted(resultado.stage_ids.index(v) for v in estagios) if estagios else list(range(len(resultado.stage_ids)))
    rotulos = [f"Corr. hydro_id {hydro_id}" for hydro_id in resultado.hydro_ids]
    valores = resultado.correlacoes[np.ix_(s, r, range(len(resultado.hydro_ids)))]
    valores = np.transpose(valores, (1, 0, 2)).reshape(len(r) * len(s), len(rotulos))
    quadro = pd.DataFrame(valores, columns=rotulos)
    ids_referencia = np.repeat([resultado.hydro_ids[i] for i in r], len(s))
    quadro.insert(0, "stage_id", np.tile([resultado.stage_ids[i] for i in s], len(r)))
    quadro.insert(0, "hydro_id referência", ids_referencia)
    quadro.insert(0, "UHE referência", [resultado.nomes[identificador] for identificador in ids_referencia])
    presentes = np.asarray([resultado.grupos_presentes[si, ri] for ri in r for si in s], dtype=bool)
    return quadro.loc[presentes].reset_index(drop=True)


def exportar_correlacao_espacial_xlsx(
    resultado: ResultadoEspacial, referencias: list[int], estagios: list[int],
) -> bytes:
    """Exporta linhas filtradas, matriz numérica oculta e auditoria sem duplicar pares."""
    quadro = tabela_espacial(resultado, referencias, estagios)
    if len(quadro) >= 1_048_576:
        raise ValueError("A tabela supera o limite de linhas de uma folha XLSX; aplique filtros antes de exportar.")
    if len(quadro.columns) > 16_384:
        raise ValueError("A tabela supera o limite de colunas de uma folha XLSX.")
    saida = BytesIO()
    livro = xlsxwriter.Workbook(saida, {"constant_memory": True})
    cabecalho = livro.add_format({
        "bold": True, "font_color": "#FFFFFF", "bg_color": "#078FA8",
        "border": 1, "border_color": "#B6E3EB", "align": "center",
    })
    formatos = [
        livro.add_format({"border": 1, "border_color": "#B6E3EB", "bg_color": cor})
        for cor in ("#FFFFFF", "#E9F9FC")
    ]
    numero = [
        livro.add_format({
            "border": 1, "border_color": "#B6E3EB", "bg_color": cor,
            "num_format": "0.000000000000000",
        })
        for cor in ("#FFFFFF", "#E9F9FC")
    ]
    for titulo, visivel in (("Correlação espacial", True), ("Valores completos", False)):
        folha = livro.add_worksheet(titulo)
        if not visivel:
            folha.hide()
        for coluna, nome in enumerate(quadro.columns):
            largura = min(255, max(16, len(str(nome)) + 2))
            if coluna == 0:
                largura = min(80, max(largura, max((len(str(v)) + 2 for v in quadro.iloc[:, 0]), default=16)))
            folha.set_column(coluna, coluna, largura)
            folha.write(0, coluna, nome, cabecalho)
        folha.freeze_panes(1, 3)
        folha.autofilter(0, 0, len(quadro), len(quadro.columns) - 1)
        folha.set_tab_color("#078FA8")
        for linha, registro in enumerate(quadro.itertuples(index=False, name=None), start=1):
            estilo = formatos[linha % 2]
            estilo_num = numero[linha % 2]
            for coluna, valor in enumerate(registro):
                if pd.isna(valor):
                    folha.write_blank(linha, coluna, None, estilo)
                elif coluna >= 3 and visivel:
                    folha.write_string(linha, coluna, f"{float(valor):.2f}", estilo)
                elif coluna >= 3:
                    folha.write_number(linha, coluna, float(valor), estilo_num)
                elif isinstance(valor, str):
                    folha.write_string(linha, coluna, valor, estilo)
                else:
                    folha.write_number(linha, coluna, int(valor), estilo)
    cabecalho_diagnostico = [
        "stage_id", "hydro_id A", "hydro_id B", "Pares esperados",
        "Pares válidos", "Média A (m³/s)", "Média B (m³/s)",
        "Desvio A (m³/s)", "Desvio B (m³/s)",
        "Covariância (m⁶/s²)", "Correlação", "Status", "Motivo",
    ]
    indices_referencia = (
        {resultado.hydro_ids.index(v) for v in referencias}
        if referencias else set(range(len(resultado.hydro_ids)))
    )
    indices_estagio = (
        sorted(resultado.stage_ids.index(v) for v in estagios)
        if estagios else list(range(len(resultado.stage_ids)))
    )
    limite = 1_048_576
    folha = None
    numero_folha = 0
    linha_saida = limite
    for s in indices_estagio:
        for u in range(len(resultado.hydro_ids)):
            for v in range(u + 1, len(resultado.hydro_ids)):
                if not (
                    (u in indices_referencia and resultado.grupos_presentes[s, u])
                    or (v in indices_referencia and resultado.grupos_presentes[s, v])
                ):
                    continue
                if linha_saida >= limite:
                    if folha is not None:
                        folha.autofilter(0, 0, linha_saida - 1, len(cabecalho_diagnostico) - 1)
                    numero_folha += 1
                    folha = livro.add_worksheet(f"Diagnóstico {numero_folha}")
                    for coluna, nome in enumerate(cabecalho_diagnostico):
                        folha.set_column(coluna, coluna, min(80, max(23, len(nome) + 2)))
                        folha.write(0, coluna, nome, cabecalho)
                    folha.freeze_panes(1, 3)
                    folha.set_tab_color("#078FA8")
                    linha_saida = 1
                estado = int(resultado.estados[s, u, v])
                valores = [
                    resultado.stage_ids[s], resultado.hydro_ids[u], resultado.hydro_ids[v],
                    int(resultado.pares_esperados[s]), int(resultado.pares_validos[s, u, v]),
                    resultado.medias[s, u, v], resultado.medias[s, v, u],
                    resultado.desvios[s, u, v], resultado.desvios[s, v, u],
                    resultado.covariancias[s, u, v], resultado.correlacoes[s, u, v],
                    "calculado" if estado == 0 else "indisponível", MOTIVOS[estado],
                ]
                for coluna, valor in enumerate(valores):
                    estilo = formatos[linha_saida % 2]
                    if isinstance(valor, str):
                        folha.write_string(linha_saida, coluna, valor, estilo)
                    elif np.isfinite(valor):
                        folha.write_number(linha_saida, coluna, float(valor), numero[linha_saida % 2])
                    else:
                        folha.write_blank(linha_saida, coluna, None, estilo)
                linha_saida += 1
    if folha is None:
        folha = livro.add_worksheet("Diagnóstico 1")
        for coluna, nome in enumerate(cabecalho_diagnostico):
            folha.write(0, coluna, nome, cabecalho)
    else:
        folha.autofilter(0, 0, linha_saida - 1, len(cabecalho_diagnostico) - 1)
    livro.close()
    return saida.getvalue()
