"""Leitura filtrada e processamento em lotes das trajetórias de todas as UHEs."""

from calculos.analise_sequencias_cobre import (
    ResultadoSequencias, organizar_horizonte, calcular_sequencias_usina,
)
from calculos.base_estatistica_cobre import carregar_cenarios, carregar_historico
import duckdb
import numpy as np
import pandas as pd


def calcular_sequencias_individual(consolidado, historico, hydro_id, nome, calendario, ids_estagios):
    horizonte = organizar_horizonte(calendario, ids_estagios)
    return calcular_sequencias_usina(carregar_cenarios(consolidado, hydro_id),
                                     carregar_historico(historico, hydro_id), hydro_id, nome, horizonte)


def _grupos_por_usina(conexao, caminho, vetores_por_lote=16):
    """Preserva uma UHE inteira mesmo quando suas linhas cruzam lotes DuckDB."""
    cursor = conexao.execute("""
        SELECT hydro_id, scenario_id, stage_id,
               TRY_CAST(incremental_inflow_m3s AS DOUBLE) AS incremental_inflow_m3s
        FROM read_parquet(?) ORDER BY hydro_id, scenario_id, stage_id
    """, [str(caminho)])
    pendente = None
    while True:
        lote = cursor.fetch_df_chunk(vetores_por_lote)
        if lote.empty:
            break
        if pendente is not None:
            lote = pd.concat([pendente, lote], ignore_index=True)
        ultimo = lote.hydro_id.iloc[-1]
        for hydro_id, grupo in lote.loc[lote.hydro_id.ne(ultimo)].groupby("hydro_id", sort=False):
            yield int(hydro_id), grupo
        pendente = lote.loc[lote.hydro_id.eq(ultimo)].copy()
    if pendente is not None and not pendente.empty:
        yield int(pendente.hydro_id.iloc[0]), pendente


def calcular_sequencias_todas_usinas(consolidado, historico, nomes, calendario, ids_estagios,
                                    vetores_por_lote=16, progresso=None):
    """Mesmo núcleo individual, uma leitura sequencial do consolidado e histórico."""
    horizonte = organizar_horizonte(calendario, ids_estagios)
    partes = {k: [] for k in ["mlts", "blocos", "intervalos_nao_utilizados", "resumos", "eventos", "diagnosticos"]}
    modelos = {}
    conexao = duckdb.connect(database=":memory:")
    try:
        conexao.execute("SET threads=4")
        historicos = conexao.execute("""
            SELECT hydro_id, TRY_CAST(start_date AS DATE) AS start_date,
                   TRY_CAST(end_date AS DATE) AS end_date, value_m3s
            FROM read_parquet(?) ORDER BY hydro_id, start_date
        """, [str(historico)]).df()
        por_usina = {int(i): g for i, g in historicos.groupby("hydro_id", sort=False)}
        vazia = historicos.iloc[:0]
        for numero, (hydro_id, dados) in enumerate(_grupos_por_usina(conexao, consolidado, vetores_por_lote), 1):
            resultado = calcular_sequencias_usina(dados, por_usina.get(hydro_id, vazia), hydro_id,
                                                   nomes.get(hydro_id, "Usina sem nome"), horizonte)
            for chave in partes:
                tabela = getattr(resultado, chave)
                modelos.setdefault(chave, tabela.iloc[:0].copy())
                if not tabela.empty:
                    tabela = tabela.copy()
                    # Eventos não guardam vetores mensais; categorias reduzem memória
                    # dos identificadores repetidos em milhões de sequências.
                    for coluna in ("nome_usina", "fonte", "status", "motivo"):
                        if coluna in tabela:
                            tabela[coluna] = tabela[coluna].astype("category")
                    partes[chave].append(tabela)
            if progresso is not None:
                progresso(numero, hydro_id)
    finally:
        conexao.close()
    tabelas = {}
    for chave, lista in partes.items():
        if not lista:
            tabelas[chave] = modelos.get(chave, pd.DataFrame()).copy()
            continue
        # Concatenar categorias de UHEs diferentes exige unificar os dicionários.
        for coluna in ("nome_usina", "fonte", "status", "motivo"):
            if coluna in lista[0]:
                valores = list(dict.fromkeys(v for tabela in lista for v in tabela[coluna].cat.categories))
                tipo = pd.CategoricalDtype(valores)
                for tabela in lista:
                    tabela[coluna] = tabela[coluna].astype(tipo)
        tabelas[chave] = pd.concat(lista, ignore_index=True)
    return ResultadoSequencias(horizonte, **tabelas)


def resumir_usinas(resultados):
    """Contagens descritivas por fonte; sem aprovação, reprovação ou p-valor."""
    if resultados.empty:
        return pd.DataFrame()
    dados = resultados.copy()
    dados["valida"] = dados.status.eq("Calculado")
    dados["sem_sequencias"] = dados.valida & dados.quantidade_sequencias.eq(0)
    return dados.groupby(["hydro_id", "nome_usina", "fonte"], observed=True, sort=True).agg(
        trajetorias=("trajetoria_id", "size"), validas=("valida", "sum"),
        sem_sequencias=("sem_sequencias", "sum"),
        quantidade_media_sequencias=("quantidade_sequencias", "mean"),
        comprimento_medio=("comprimento_medio", "mean"),
        soma_media=("soma_media", "mean"), intensidade_media=("intensidade_media", "mean"),
    ).reset_index().assign(invalidas=lambda x: x.trajetorias-x.validas)


def carregar_detalhe_trajetoria(consolidado, historico, resultado, hydro_id, fonte, trajetoria_id):
    """Lê só a trajetória pedida. Não materializa o memorial mensal global."""
    linha = resultado.resumos.loc[(resultado.resumos.hydro_id.eq(hydro_id)) &
                                  resultado.resumos.fonte.eq(fonte) &
                                  resultado.resumos.trajetoria_id.eq(trajetoria_id)].iloc[0]
    periodos = pd.period_range(linha.inicio, periods=int(linha.horizonte_meses), freq="M")
    conexao = duckdb.connect(database=":memory:")
    try:
        if fonte == "Sintético":
            dados = conexao.execute("""SELECT stage_id, TRY_CAST(incremental_inflow_m3s AS DOUBLE) AS vazao
                FROM read_parquet(?) WHERE hydro_id=? AND scenario_id=?""",
                [str(consolidado), int(hydro_id), int(trajetoria_id)]).df()
            dados = dados.merge(resultado.horizonte[["stage_id", "periodo"]], on="stage_id", how="left")
        else:
            dados = conexao.execute("""SELECT start_date, TRY_CAST(value_m3s AS DOUBLE) AS vazao
                FROM read_parquet(?) WHERE hydro_id=? AND TRY_CAST(start_date AS DATE)>=?
                AND TRY_CAST(start_date AS DATE)<?""",
                [str(historico), int(hydro_id), periodos[0].start_time.date(), (periodos[-1]+1).start_time.date()]).df()
            dados["periodo"] = pd.to_datetime(dados.start_date).dt.to_period("M")
    finally:
        conexao.close()
    agrupado = dados.groupby("periodo").vazao.agg(["first", "size"]).reindex(periodos)
    detalhe = pd.DataFrame(dict(data=periodos.to_timestamp(), mes=periodos.month,
                                vazao=agrupado["first"].to_numpy(), registros_mes=agrupado["size"].fillna(0).to_numpy()))
    detalhe["mlt"] = detalhe.mes.map(resultado.mlts.loc[resultado.mlts.hydro_id.eq(hydro_id)].set_index("mes").mlt)
    detalhe["diferenca"] = detalhe.vazao-detalhe.mlt
    detalhe["abaixo_mlt"] = (detalhe.vazao < detalhe.mlt).astype("boolean")
    detalhe["numero_sequencia"] = pd.array([pd.NA]*len(detalhe), dtype="Int64")
    if fonte == "Sintético":
        detalhe["stage_id"] = resultado.horizonte.stage_id.to_numpy()
    if linha.status != "Calculado":
        detalhe["abaixo_mlt"] = pd.NA
    else:
        eventos = resultado.eventos.loc[resultado.eventos.hydro_id.eq(hydro_id) &
                                        resultado.eventos.fonte.eq(fonte) &
                                        resultado.eventos.trajetoria_id.eq(trajetoria_id)]
        for evento in eventos.itertuples():
            detalhe.loc[detalhe.data.between(evento.inicio, evento.fim), "numero_sequencia"] = evento.numero_sequencia
    detalhe["status_trajetoria"], detalhe["motivo"] = linha.status, linha.motivo
    return detalhe
