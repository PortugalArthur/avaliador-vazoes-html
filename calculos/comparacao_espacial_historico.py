"""Extensão histórica mensal da correlação espacial do analisador anterior."""

from dataclasses import dataclass
from io import BytesIO

from calculos.base_estatistica_cobre import NOMES_MESES, _preparar_historico
from calculos.correlacao_espacial_cobre import (
    MOTIVOS, ResultadoEspacial, _calcular_estagio, diagnosticar_par, tabela_espacial,
)

import duckdb
import numpy as np
import pandas as pd
import xlsxwriter


@dataclass
class HistoricoEspacial:
    matrizes: ResultadoEspacial
    limites: dict[int, tuple[str, str]]
    avisos: dict[int, str]


def gerar_correlacao_historica(caminho, hydro_ids, nomes):
    """Correlaciona UHEs no mesmo mês e nos mesmos anos históricos.

    Cada linha da matriz de entrada é uma data mensal real, nunca a posição
    de um registro no arquivo. As ausências ficam como NaN, para que a rotina
    original utilize a interseção de pares finitos de cada par de usinas.
    """
    usinas = tuple(int(i) for i in hydro_ids)
    with duckdb.connect(database=":memory:") as conexao:
        bruto = conexao.execute(
            "SELECT hydro_id, start_date, end_date, value_m3s FROM read_parquet(?) ORDER BY hydro_id, start_date",
            [str(caminho)],
        ).df()
    limites, avisos, preparados = {}, {}, []
    for hydro_id, grupo in bruto.groupby("hydro_id", sort=False):
        hydro_id = int(hydro_id)
        if hydro_id not in usinas:
            continue
        try:
            dados, inicio, fim, _ = _preparar_historico(grupo, hydro_id)
        except ValueError as erro:
            avisos[hydro_id] = str(erro)
            continue
        limites[hydro_id] = (str(inicio), str(fim))
        preparados.append(dados[["hydro_id", "periodo", "month", "value_m3s"]])
    for hydro_id in usinas:
        if hydro_id not in limites and hydro_id not in avisos:
            avisos[hydro_id] = "UHE sem registros históricos."
    dados = pd.concat(preparados, ignore_index=True) if preparados else pd.DataFrame(
        columns=["hydro_id", "periodo", "month", "value_m3s"]
    )
    forma = (12, len(usinas), len(usinas))
    pares = np.zeros(forma, dtype=np.int32)
    correlacoes = np.full(forma, np.nan)
    medias, desvios, covariancias = (np.full(forma, np.nan) for _ in range(3))
    estados = np.ones(forma, dtype=np.uint8)
    presentes = np.zeros((12, len(usinas)), dtype=bool)
    esperados = np.zeros(12, dtype=np.int32)
    for mes in range(1, 13):
        grupo = dados.loc[dados["month"].eq(mes)]
        matriz = grupo.pivot(index="periodo", columns="hydro_id", values="value_m3s").reindex(columns=usinas).sort_index()
        valores = matriz.to_numpy(dtype=float)
        # Meses históricos diferentes e anos diferentes nunca são pareados.
        # Ex.: julho/1931 de A somente com julho/1931 de B.
        presentes[mes - 1] = np.asarray([int(i) in set(grupo.hydro_id) for i in usinas])
        esperados[mes - 1] = len(matriz)
        calculo = _calcular_estagio(valores)
        for destino, origem in zip((pares, correlacoes, medias, desvios, covariancias, estados), calculo):
            destino[mes - 1] = origem
    resultado = ResultadoEspacial(
        tuple(range(1, 13)), usinas, {i: nomes.get(i, f"UHE {i}") for i in usinas},
        esperados, pares, correlacoes, medias, desvios, covariancias, estados, presentes,
    )
    return HistoricoEspacial(resultado, limites, avisos)


def _diagnostico_disponivel(matriz, periodo, referencia, comparada):
    if referencia in matriz.hydro_ids and comparada in matriz.hydro_ids:
        return diagnosticar_par(matriz, periodo, referencia, comparada)
    return {
        "stage_id": periodo, "hydro_id referência": referencia, "UHE referência": matriz.nomes.get(referencia, str(referencia)),
        "hydro_id comparada": comparada, "UHE comparada": matriz.nomes.get(comparada, str(comparada)),
        "Pares esperados": int(matriz.pares_esperados[matriz.stage_ids.index(periodo)]), "Pares válidos": 0,
        "Média referência (m³/s)": None, "Média comparada (m³/s)": None,
        "Desvio referência (m³/s)": None, "Desvio comparada (m³/s)": None,
        "Covariância (m⁶/s²)": None, "Correlação": None,
        "Status": "indisponível", "Motivo": "UHE sem cenários no estágio selecionado.",
    }


def tabela_comparacao_estagio(sintetico, historico, stage_id, hydro_id, calendario):
    """Uma linha por outra UHE, com coeficientes e contagens das duas fontes."""
    h = historico.matrizes
    mes = calendario[stage_id]["mes"]
    linhas = []
    for comparada in h.hydro_ids:
        if comparada == hydro_id:
            continue
        ds = _diagnostico_disponivel(sintetico, stage_id, hydro_id, comparada)
        dh = diagnosticar_par(h, mes, hydro_id, comparada)
        motivo_h = historico.avisos.get(hydro_id) or historico.avisos.get(comparada) or dh["Motivo"]
        linhas.append({
            "hydro_id": comparada, "Usina": h.nomes[comparada],
            "Correlação sintética": ds["Correlação"], "Correlação histórica": dh["Correlação"],
            "Pares sintéticos": ds["Pares válidos"], "Pares históricos": dh["Pares válidos"],
            "Motivo sintético": ds["Motivo"], "Motivo histórico": motivo_h,
        })
    return pd.DataFrame(linhas, columns=["hydro_id", "Usina", "Correlação sintética", "Correlação histórica",
                                        "Pares sintéticos", "Pares históricos", "Motivo sintético", "Motivo histórico"])


def memorial_estagio(sintetico, historico, stage_id, hydro_id, calendario):
    linhas = []
    mes = calendario[stage_id]["mes"]
    for comparada in historico.matrizes.hydro_ids:
        if comparada == hydro_id:
            continue
        for fonte, matriz, chave in [("Sintético", sintetico, stage_id), ("Histórico", historico.matrizes, mes)]:
            linha = _diagnostico_disponivel(matriz, chave, hydro_id, comparada)
            linha.pop("stage_id")
            linha.update(Fonte=fonte, **{"Estágio sintético": stage_id, "Mês histórico": NOMES_MESES[mes]})
            if fonte == "Histórico":
                linha["Motivo"] = historico.avisos.get(hydro_id) or historico.avisos.get(comparada) or linha["Motivo"]
            linhas.append(linha)
    return pd.DataFrame(linhas)


def matriz_historica(historico, meses=None):
    return tabela_espacial(historico.matrizes, estagios=meses).rename(columns={"stage_id": "Mês"})


def exportar_comparacao_espacial_xlsx(sintetico, historico, calendario):
    """Matrizes no formato antigo e diagnósticos completos, em um único Excel.

    A exportação contém todas as referências e estágios calculados, sem
    depender dos seletores de apresentação. A diagonal permanece vazia.
    Pares simétricos aparecem uma única vez nas folhas de diagnóstico.
    """
    saida = BytesIO()
    livro = xlsxwriter.Workbook(saida, {"constant_memory": True, "strings_to_formulas": False, "strings_to_urls": False})
    cabecalho = livro.add_format({"bold": True, "font_color": "white", "bg_color": "#4C1D95",
                                 "border": 1, "text_wrap": True, "valign": "vcenter"})
    numero = livro.add_format({"num_format": "0.000000"})
    inteiro = livro.add_format({"num_format": "0"})

    def escrever_quadro(nome, quadro, colunas_inteiras=()):
        if len(quadro) > 1048575 or len(quadro.columns) > 16384:
            raise ValueError(f"{nome}: a matriz supera o limite de uma planilha Excel.")
        folha = livro.add_worksheet(nome)
        folha.freeze_panes(1, min(3, len(quadro.columns)))
        folha.set_row(0, 40)
        for c, nome_coluna in enumerate(quadro.columns):
            folha.write(0, c, nome_coluna, cabecalho)
            folha.set_column(c, c, 32 if c == 0 else 23)
        for l, registro in enumerate(quadro.itertuples(index=False, name=None), 1):
            for c, valor in enumerate(registro):
                if pd.isna(valor):
                    continue
                if isinstance(valor, (str, pd.Period)):
                    folha.write_string(l, c, str(valor))
                elif isinstance(valor, (int, float, np.number)):
                    folha.write_number(l, c, float(valor), inteiro if quadro.columns[c] in colunas_inteiras else numero)
                else:
                    folha.write_string(l, c, str(valor))
        folha.autofilter(0, 0, len(quadro), len(quadro.columns) - 1)

    escrever_quadro("Correlação espacial", tabela_espacial(sintetico), ["hydro_id referência", "stage_id"])
    escrever_quadro("Histórico mensal", matriz_historica(historico), ["hydro_id referência", "Mês"])
    cadastro = pd.DataFrame([{
        "hydro_id": i, "Usina": sintetico.nomes[i],
        "Primeiro mês histórico": historico.limites.get(i, (None, None))[0],
        "Último mês histórico": historico.limites.get(i, (None, None))[1],
        "Aviso histórico": historico.avisos.get(i, ""),
    } for i in sintetico.hydro_ids])
    escrever_quadro("Cadastro de UHEs", cadastro, ["hydro_id"])
    calendario_exportado = pd.DataFrame([{
        "stage_id": s, "Início": str(calendario[s]["inicio"]), "Fim": str(calendario[s]["fim"]),
        "Mês": calendario[s]["mes"], "Nome do mês": NOMES_MESES[calendario[s]["mes"]],
    } for s in sintetico.stage_ids])
    escrever_quadro("Calendário", calendario_exportado, ["stage_id", "Mês"])

    # Escreve os memoriais linha a linha; não constrói um DataFrame de milhões de linhas.
    titulos = ["Período", "hydro_id A", "UHE A", "hydro_id B", "UHE B", "Pares esperados", "Pares válidos",
               "Média A (m³/s)", "Média B (m³/s)", "Desvio A (m³/s)", "Desvio B (m³/s)",
               "Covariância (m⁶/s²)", "Correlação", "Status", "Motivo"]
    for fonte, matriz in [("Sintético", sintetico), ("Histórico", historico.matrizes)]:
        folha, linha_saida, parte = None, 1048576, 0
        for s, periodo in enumerate(matriz.stage_ids):
            for u, a in enumerate(matriz.hydro_ids):
                for v in range(u + 1, len(matriz.hydro_ids)):
                    b = matriz.hydro_ids[v]
                    if linha_saida >= 1048576:
                        if folha is not None:
                            folha.autofilter(0, 0, linha_saida - 1, len(titulos) - 1)
                        parte += 1
                        folha = livro.add_worksheet(f"Memorial {fonte} {parte}")
                        folha.freeze_panes(1, 5)
                        folha.set_row(0, 40)
                        for c, titulo in enumerate(titulos):
                            folha.write(0, c, titulo, cabecalho)
                            folha.set_column(c, c, 25 if c != 14 else 60)
                        linha_saida = 1
                    estado = int(matriz.estados[s, u, v])
                    motivo = MOTIVOS[estado]
                    if fonte == "Histórico":
                        motivo = historico.avisos.get(a) or historico.avisos.get(b) or motivo
                    valores = [periodo, a, matriz.nomes[a], b, matriz.nomes[b], int(matriz.pares_esperados[s]),
                               int(matriz.pares_validos[s,u,v]), matriz.medias[s,u,v], matriz.medias[s,v,u],
                               matriz.desvios[s,u,v], matriz.desvios[s,v,u], matriz.covariancias[s,u,v],
                               matriz.correlacoes[s,u,v], "calculado" if estado == 0 else "indisponível", motivo]
                    for c, valor in enumerate(valores):
                        if isinstance(valor, str):
                            folha.write_string(linha_saida, c, valor)
                        elif np.isfinite(valor):
                            folha.write_number(linha_saida, c, float(valor), inteiro if c in (0, 1, 3, 5, 6) else numero)
                    linha_saida += 1
        if folha is not None:
            folha.autofilter(0, 0, linha_saida - 1, len(titulos) - 1)
    livro.close()
    return saida.getvalue()
