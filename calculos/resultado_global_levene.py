"""Organização mensal, processamento em lotes e exportações do Levene original."""

from __future__ import annotations

from io import BytesIO

from calculos.base_estatistica_cobre import NOMES_MESES, _preparar_historico
from calculos.teste_levene_cobre import preparar_medias_levene

import duckdb
import numpy as np
import pandas as pd


COLUNAS_ESCALARES = [
    "n_historico", "n_sintetico", "media_historica", "media_sintetica",
    "media_desvios_historicos", "media_desvios_sinteticos", "media_geral_desvios",
    "soma_quadrados_entre_grupos", "soma_quadrados_dentro_grupos",
    "quantidade_grupos", "total_observacoes", "graus_liberdade_entre",
    "graus_liberdade_dentro", "quadrado_medio_entre", "quadrado_medio_dentro",
    "estatistica_levene", "p_valor", "alfa", "rejeita_igualdade_variancias",
]
COLUNAS_IDENTIFICACAO = [
    "hydro_id", "nome_usina", "stage_id", "inicio_estagio", "fim_estagio",
    "ordem_estagio", "ano", "mes", "mes_nome", "rotulo_estagio",
    "historico_inicio", "historico_fim", "primeiro_mes_historico_usado",
    "ultimo_mes_historico_usado", "lacunas_historicas", "versao_teste", "centro",
]
COLUNAS_RESULTADO = COLUNAS_IDENTIFICACAO + COLUNAS_ESCALARES + [
    "desvio_padrao_historico", "desvio_padrao_sintetico",
    "resultado", "status_teste", "motivo_nao_calculado",
]
NOMES_COLUNAS = {
    "hydro_id": "ID da UHE", "nome_usina": "Usina", "stage_id": "ID do estágio",
    "inicio_estagio": "Início do estágio", "fim_estagio": "Fim do estágio (exclusivo)",
    "ordem_estagio": "Ordem cronológica (base zero)", "ano": "Ano", "mes": "Mês numérico",
    "mes_nome": "Mês", "rotulo_estagio": "Estágio e período",
    "historico_inicio": "Início do histórico da UHE", "historico_fim": "Fim do histórico da UHE",
    "primeiro_mes_historico_usado": "Primeiro mês histórico usado",
    "ultimo_mes_historico_usado": "Último mês histórico usado",
    "lacunas_historicas": "Lacunas mensais no histórico", "versao_teste": "Teste",
    "centro": "Centro", "n_historico": "N histórico", "n_sintetico": "N sintético",
    "media_historica": "Média histórica (m³/s)", "media_sintetica": "Média sintética (m³/s)",
    "media_desvios_historicos": "Média dos desvios históricos (m³/s)",
    "media_desvios_sinteticos": "Média dos desvios sintéticos (m³/s)",
    "media_geral_desvios": "Média geral dos desvios (m³/s)",
    "soma_quadrados_entre_grupos": "Soma dos quadrados entre grupos ((m³/s)²)",
    "soma_quadrados_dentro_grupos": "Soma dos quadrados dentro dos grupos ((m³/s)²)",
    "quantidade_grupos": "Número de grupos", "total_observacoes": "Total de observações",
    "graus_liberdade_entre": "Graus de liberdade entre grupos",
    "graus_liberdade_dentro": "Graus de liberdade dentro dos grupos",
    "quadrado_medio_entre": "Quadrado médio entre grupos ((m³/s)²)",
    "quadrado_medio_dentro": "Quadrado médio dentro dos grupos ((m³/s)²)",
    "estatistica_levene": "Estatística W", "p_valor": "p-valor", "alfa": "Alfa",
    "rejeita_igualdade_variancias": "Rejeita igualdade das variâncias",
    "desvio_padrao_historico": "Desvio padrão histórico (m³/s)",
    "desvio_padrao_sintetico": "Desvio padrão sintético (m³/s)",
    "resultado": "Resultado", "status_teste": "Status do teste",
    "motivo_nao_calculado": "Motivo de não cálculo",
    "combinacoes_esperadas": "Combinações esperadas",
    "combinacoes_calculadas": "Combinações calculadas",
    "combinacoes_reprovadas": "Reprovações",
    "combinacoes_nao_reprovadas": "Não reprovadas",
    "combinacoes_nao_calculadas": "Não calculadas",
    "percentual_reprovado": "Reprovações (%)",
}


def _validar_alfa(alfa):
    if not 0 < alfa < 1:
        raise ValueError("alfa deve estar entre 0 e 1.")


def _identificacao(hydro_id, nome, stage_id, etapa, alfa):
    return {
        "hydro_id": int(hydro_id), "nome_usina": nome, "stage_id": int(stage_id),
        "inicio_estagio": etapa["inicio"], "fim_estagio": etapa["fim"],
        "ordem_estagio": etapa["ordem"], "ano": etapa["ano"], "mes": etapa["mes"],
        "mes_nome": NOMES_MESES[etapa["mes"]],
        "rotulo_estagio": f"{etapa['mes']:02d}/{etapa['ano']} — stage {stage_id}",
        "alfa": float(alfa), "versao_teste": "Levene original", "centro": "Média",
    }


def _avaliar_linha(linha, historico, sintetico, alfa, motivo=""):
    """Mesma conta e mesmo tratamento de falhas nas análises individual e global."""
    linha = dict(linha)
    h = np.asarray(historico, dtype=float)
    s = np.asarray(sintetico, dtype=float)
    linha.update(n_historico=len(h), n_sintetico=len(s))
    # Apenas estatísticas descritivas de vazão para o gráfico já existente.
    for fonte, vetor in (("historico", h), ("sintetico", s)):
        if vetor.size and np.isfinite(vetor).all():
            coluna_media = "media_historica" if fonte == "historico" else "media_sintetica"
            linha[coluna_media] = float(vetor.mean())
            if vetor.size >= 2:
                linha[f"desvio_padrao_{fonte}"] = float(vetor.std(ddof=1))
    if not motivo:
        try:
            calculo = preparar_medias_levene(h, s, alfa=alfa)
        except ValueError as erro:
            linha.update(getattr(erro, "diagnostico", {}))
            motivo = str(erro)
        else:
            linha.update({chave: calculo[chave] for chave in COLUNAS_ESCALARES})
    if motivo:
        linha.update(
            resultado="Não calculado", status_teste="Não calculado",
            motivo_nao_calculado=motivo,
        )
    else:
        linha.update(
            resultado="Reprovado" if linha["rejeita_igualdade_variancias"] else "Não reprovado",
            status_teste="Calculado", motivo_nao_calculado="",
        )
    return linha


def _tabela_resultados(linhas):
    tabela = pd.DataFrame(linhas).reindex(columns=COLUNAS_RESULTADO)
    tabela["rejeita_igualdade_variancias"] = tabela["rejeita_igualdade_variancias"].astype("boolean")
    return tabela.sort_values(
        ["nome_usina", "hydro_id", "ordem_estagio"], kind="stable"
    ).reset_index(drop=True)


def calcular_levene_por_estagio(organizacao, alfa=0.05):
    """Aplica a função didática aos vetores mensais já organizados da UHE."""
    _validar_alfa(alfa)
    linhas = []
    for ordem, (stage_id, amostra) in enumerate(organizacao.amostras_por_estagio.items()):
        etapa = {
            "inicio": amostra.start_date, "fim": amostra.end_date,
            "ano": amostra.year, "mes": amostra.month, "ordem": ordem,
        }
        linha = _identificacao(amostra.hydro_id, amostra.hydro_name, stage_id, etapa, alfa)
        linha.update(
            historico_inicio=str(organizacao.historico_inicio),
            historico_fim=str(organizacao.historico_fim),
            lacunas_historicas=len(organizacao.meses_historicos_ausentes),
            primeiro_mes_historico_usado=str(amostra.historico.index.min()) if len(amostra.historico) else None,
            ultimo_mes_historico_usado=str(amostra.historico.index.max()) if len(amostra.historico) else None,
        )
        linhas.append(_avaliar_linha(linha, amostra.historico, amostra.sintetico, alfa))
    return _tabela_resultados(linhas)


def _iterar_grupos(conexao, caminho, calendario, vetores_por_lote):
    """Preserva integralmente o último grupo quando ele cruza a borda de um lote."""
    mapa = pd.DataFrame([
        {"stage_id": stage_id, "ordem": etapa["ordem"]}
        for stage_id, etapa in calendario.items()
    ])
    conexao.register("calendario_levene", mapa)
    consulta = conexao.execute(
        """
        SELECT p.hydro_id, p.stage_id, p.scenario_id,
               TRY_CAST(p.incremental_inflow_m3s AS DOUBLE) AS valor
        FROM read_parquet(?) p
        JOIN calendario_levene c ON p.stage_id = c.stage_id
        ORDER BY p.hydro_id, c.ordem, p.scenario_id
        """, [str(caminho)],
    )
    pendente = None
    while True:
        lote = consulta.fetch_df_chunk(vetores_por_lote)
        if lote.empty:
            break
        if pendente is not None:
            lote = pd.concat([pendente, lote], ignore_index=True)
        ultima_chave = (int(lote.iloc[-1]["hydro_id"]), int(lote.iloc[-1]["stage_id"]))
        for chave, grupo in lote.groupby(["hydro_id", "stage_id"], sort=False):
            chave = tuple(int(valor) for valor in chave)
            if chave == ultima_chave:
                pendente = grupo.copy()
            else:
                yield chave, grupo
    if pendente is not None:
        chave = (int(pendente.iloc[0]["hydro_id"]), int(pendente.iloc[0]["stage_id"]))
        yield chave, pendente


def calcular_levene_todas_usinas(
    caminho_consolidado, caminho_historico, nomes, calendario, alfa=0.05,
    *, vetores_por_lote=16,
):
    """Um teste por UHE-estágio; histórico por mês real e cenários em lotes."""
    _validar_alfa(alfa)
    if vetores_por_lote < 1:
        raise ValueError("O tamanho do lote deve ser positivo.")
    conexao = duckdb.connect(database=":memory:")
    conexao.execute("SET enable_progress_bar = false")
    try:
        metadados = conexao.execute(
            "SELECT DISTINCT hydro_id, stage_id FROM read_parquet(?)",
            [str(caminho_consolidado)],
        ).df()
        if metadados.empty:
            return _tabela_resultados([])
        if metadados.isna().any().any():
            raise ValueError("O consolidado possui IDs de UHE ou estágio ausentes.")
        usinas = sorted(int(valor) for valor in metadados["hydro_id"].unique())
        ids_estagios = {int(valor) for valor in metadados["stage_id"].unique()}
        sem_data = ids_estagios - set(calendario)
        if sem_data:
            raise ValueError(f"Estágios sem calendário no stages.json: {sorted(sem_data)}")
        estagios = sorted(ids_estagios, key=lambda valor: calendario[valor]["inicio"])
        # Valida também a relação data/mês do calendário recebido.
        for stage_id in estagios:
            etapa = calendario[stage_id]
            if etapa["mes"] != etapa["inicio"].month or etapa["ano"] != etapa["inicio"].year:
                raise ValueError(f"Mês/ano incompatível com a data do estágio {stage_id}.")
        avisos = []
        for anterior, atual in zip(estagios, estagios[1:]):
            if calendario[anterior]["fim"] != calendario[atual]["inicio"]:
                avisos.append(f"Lacuna no horizonte entre os estágios {anterior} e {atual}.")
        extras = sorted(set(calendario) - ids_estagios)
        if extras:
            avisos.append(f"Estágios do calendário sem cenários no consolidado: {extras}.")
        historico_bruto = conexao.execute(
            """SELECT hydro_id, start_date, end_date, value_m3s
               FROM read_parquet(?) ORDER BY hydro_id, start_date""",
            [str(caminho_historico)],
        ).df()
        historicos = {}
        for hydro_id, dados in historico_bruto.groupby("hydro_id", sort=False):
            try:
                preparado, inicio, fim, lacunas = _preparar_historico(dados, int(hydro_id))
            except ValueError as erro:
                historicos[int(hydro_id)] = {"motivo": str(erro), "meses": {}}
                continue
            historicos[int(hydro_id)] = {
                "motivo": "", "historico_inicio": str(inicio), "historico_fim": str(fim),
                "lacunas_historicas": len(lacunas),
                "meses": {
                    mes: grupo.set_index("periodo")["value_m3s"].sort_index()
                    for mes, grupo in preparado.groupby("month", sort=False)
                },
            }
        del historico_bruto

        linhas = []
        referencias = {}
        vistos = set()

        def montar_linha(hydro_id, stage_id, grupo):
            etapa = calendario[stage_id]
            linha = _identificacao(hydro_id, nomes.get(hydro_id, "Usina sem nome"), stage_id, etapa, alfa)
            contexto = historicos.get(hydro_id, {"motivo": "UHE sem histórico.", "meses": {}})
            linha.update({chave: valor for chave, valor in contexto.items() if chave not in ("motivo", "meses")})
            h = contexto["meses"].get(etapa["mes"], pd.Series(dtype=float))
            linha.update(
                primeiro_mes_historico_usado=str(h.index.min()) if len(h) else None,
                ultimo_mes_historico_usado=str(h.index.max()) if len(h) else None,
            )
            motivo = contexto["motivo"]
            s = []
            if grupo is None:
                motivo = "Sem cenários para a UHE e estágio."
            else:
                s = grupo["valor"].to_numpy(dtype=float)
                ids = grupo["scenario_id"]
                conjunto = frozenset(ids.tolist())
                referencia = referencias.setdefault(hydro_id, conjunto)
                if ids.isna().any() or ids.duplicated().any():
                    motivo = "IDs de cenários ausentes ou repetidos na UHE e estágio."
                elif conjunto != referencia:
                    motivo = "Conjunto de cenários diferente do primeiro estágio disponível da UHE."
            if not motivo and len(h) == 0:
                motivo = f"Sem histórico de {NOMES_MESES[etapa['mes']]} para a UHE."
            return _avaliar_linha(linha, h, s, alfa, motivo)

        for (hydro_id, stage_id), grupo in _iterar_grupos(
            conexao, caminho_consolidado, calendario, vetores_por_lote
        ):
            linhas.append(montar_linha(hydro_id, stage_id, grupo))
            vistos.add((hydro_id, stage_id))
        for hydro_id in usinas:
            for stage_id in estagios:
                if (hydro_id, stage_id) not in vistos:
                    linhas.append(montar_linha(hydro_id, stage_id, None))
        tabela = _tabela_resultados(linhas)
        tabela.attrs["avisos_horizonte"] = avisos
        return tabela
    finally:
        conexao.close()


def resumir_levene_por_estagio(resultados):
    """Inclui todos os estágios, com falhas separadas das decisões do teste."""
    colunas = ["ordem_estagio", "stage_id", "inicio_estagio", "mes_nome"]
    totais = [
        "combinacoes_esperadas", "combinacoes_calculadas", "combinacoes_reprovadas",
        "combinacoes_nao_reprovadas", "combinacoes_nao_calculadas", "percentual_reprovado",
    ]
    if resultados.empty:
        return pd.DataFrame(columns=colunas + totais)
    dados = resultados.copy()
    dados["calculado"] = dados["status_teste"].eq("Calculado")
    dados["reprovado"] = dados["calculado"] & dados["rejeita_igualdade_variancias"].fillna(False)
    resumo = dados.groupby(colunas, as_index=False).agg(
        combinacoes_esperadas=("hydro_id", "size"),
        combinacoes_calculadas=("calculado", "sum"),
        combinacoes_reprovadas=("reprovado", "sum"),
    ).sort_values("ordem_estagio")
    for coluna in ("combinacoes_esperadas", "combinacoes_calculadas", "combinacoes_reprovadas"):
        resumo[coluna] = resumo[coluna].astype(int)
    resumo["combinacoes_nao_reprovadas"] = resumo["combinacoes_calculadas"] - resumo["combinacoes_reprovadas"]
    resumo["combinacoes_nao_calculadas"] = resumo["combinacoes_esperadas"] - resumo["combinacoes_calculadas"]
    resumo["percentual_reprovado"] = (
        100 * resumo["combinacoes_reprovadas"] / resumo["combinacoes_calculadas"].replace(0, np.nan)
    )
    return resumo[colunas + totais].reset_index(drop=True)


def _dados_exportacao_levene(resultados, *, datas_texto):
    """Prepara as mesmas colunas e valores completos para os dois formatos."""
    dados = resultados.reindex(columns=COLUNAS_RESULTADO).sort_values(
        ["nome_usina", "hydro_id", "ordem_estagio"], kind="stable"
    ).copy()
    for coluna in ("inicio_estagio", "fim_estagio"):
        dados[coluna] = pd.to_datetime(dados[coluna])
        if datas_texto:
            dados[coluna] = dados[coluna].dt.strftime("%d/%m/%Y")
    # IDs e contagens devem permanecer inteiros mesmo quando existem falhas.
    for coluna in (
        "hydro_id", "stage_id", "ordem_estagio", "ano", "mes", "lacunas_historicas",
        "n_historico", "n_sintetico", "quantidade_grupos", "total_observacoes",
        "graus_liberdade_entre", "graus_liberdade_dentro",
    ):
        dados[coluna] = pd.to_numeric(dados[coluna], errors="coerce").astype("Int64")
    return dados


def gerar_csv_levene(resultados):
    """CSV pt-BR: UTF-8 com BOM, ponto e vírgula, precisão completa e sem milhares."""
    dados = _dados_exportacao_levene(resultados, datas_texto=True).rename(columns=NOMES_COLUNAS)
    return dados.to_csv(
        index=False, sep=";", decimal=",", na_rep="", lineterminator="\r\n",
    ).encode("utf-8-sig")


def gerar_excel_levene(resultados, alfa=0.05):
    """Excel no padrão visual do Welch, sem recortar o horizonte da exportação."""
    from infraestrutura.preparar_ambiente import garantir_dependencias

    garantir_dependencias({"xlsxwriter": "XlsxWriter>=3.2"})
    _validar_alfa(alfa)
    calculados = resultados["status_teste"].eq("Calculado")
    reprovados = calculados & resultados["rejeita_igualdade_variancias"].fillna(False)
    indicadores = pd.DataFrame({
        "Indicador": [
            "Nível de significância (alfa)",
            "Combinações UHE-estágio calculadas",
            "Combinações UHE-estágio reprovadas",
            "UHEs com ao menos uma reprovação",
            "Combinações que não puderam ser calculadas",
        ],
        "Valor": [
            alfa, int(calculados.sum()), int(reprovados.sum()),
            int(resultados.loc[reprovados, "hydro_id"].nunique()), int((~calculados).sum()),
        ],
    })
    dados = _dados_exportacao_levene(resultados, datas_texto=False)
    primeiras = [
        "hydro_id", "nome_usina", "stage_id", "inicio_estagio", "fim_estagio",
        "ano", "mes", "mes_nome", "n_historico", "n_sintetico",
        "media_historica", "media_sintetica", "desvio_padrao_historico", "desvio_padrao_sintetico",
    ]
    colunas = primeiras + [coluna for coluna in COLUNAS_RESULTADO if coluna not in primeiras]
    dados = dados[colunas]
    dados["rejeita_igualdade_variancias"] = dados["rejeita_igualdade_variancias"].map({True: "Sim", False: "Não"})
    # Mesmos cabeçalhos dos campos comuns à planilha do Welch.
    rotulos = {**NOMES_COLUNAS, "mes": "Mês", "mes_nome": "Nome do mês", "fim_estagio": "Fim do estágio"}
    exportacao = dados.rename(columns=rotulos)
    resumo = resumir_levene_por_estagio(resultados).drop(columns="ordem_estagio", errors="ignore").copy()
    resumo["inicio_estagio"] = pd.to_datetime(resumo["inicio_estagio"])
    resumo_exportacao = resumo.rename(columns=rotulos)

    saida = BytesIO()
    with pd.ExcelWriter(
        saida, engine="xlsxwriter", date_format="dd/mm/yyyy", datetime_format="dd/mm/yyyy",
        engine_kwargs={"options": {"strings_to_formulas": False, "strings_to_urls": False}},
    ) as escritor:
        indicadores.to_excel(escritor, sheet_name="Resumo geral", index=False, startrow=2)
        resumo_exportacao.to_excel(escritor, sheet_name="Resumo por estágio", index=False)
        exportacao.to_excel(escritor, sheet_name="Resultados completos", index=False)
        pasta = escritor.book
        # Cores, datas e seis casas decimais seguem o Excel da aba Welch.
        cabecalho = pasta.add_format({
            "bold": True, "font_color": "white", "bg_color": "#4C1D95", "border": 1,
            "text_wrap": True, "valign": "vcenter",
        })
        titulo = pasta.add_format({"bold": True, "font_size": 16, "font_color": "#4C1D95"})
        inteiro = pasta.add_format({"num_format": "0"})
        decimal = pasta.add_format({"num_format": "0.000000"})
        percentual = pasta.add_format({"num_format": '0.00"%"'})
        data = pasta.add_format({"num_format": "dd/mm/yyyy"})
        destaque = pasta.add_format({"bg_color": "#FECACA", "font_color": "#991B1B"})

        aba_resumo = escritor.sheets["Resumo geral"]
        aba_resumo.write("A1", "Teste de Levene para todas as usinas", titulo)
        aba_resumo.set_column("A:A", 46)
        aba_resumo.set_column("B:B", 22, inteiro)
        aba_resumo.write_number(3, 1, alfa, decimal)
        aba_resumo.freeze_panes(3, 0)
        for indice, valor in enumerate(indicadores.columns):
            aba_resumo.write(2, indice, valor, cabecalho)

        aba_estagios = escritor.sheets["Resumo por estágio"]
        aba_estagios.freeze_panes(1, 0)
        aba_estagios.autofilter(0, 0, len(resumo_exportacao), len(resumo_exportacao.columns) - 1)
        for indice, coluna in enumerate(resumo.columns):
            formato = data if coluna == "inicio_estagio" else percentual if coluna == "percentual_reprovado" else inteiro
            aba_estagios.set_column(indice, indice, 24, formato)
        aba_estagios.set_row(0, 32)
        for indice, valor in enumerate(resumo_exportacao.columns):
            aba_estagios.write(0, indice, valor, cabecalho)

        aba_dados = escritor.sheets["Resultados completos"]
        aba_dados.freeze_panes(1, 2)
        aba_dados.autofilter(0, 0, len(exportacao), len(exportacao.columns) - 1)
        for indice, coluna in enumerate(colunas):
            formato = None
            largura = 22
            if coluna in ("inicio_estagio", "fim_estagio"):
                formato = data
                largura = 17
            elif pd.api.types.is_integer_dtype(dados[coluna]):
                formato = inteiro
            elif pd.api.types.is_numeric_dtype(dados[coluna]):
                formato = decimal
            elif coluna == "nome_usina":
                largura = 32
            elif coluna == "motivo_nao_calculado":
                largura = 48
            aba_dados.set_column(indice, indice, largura, formato)
        aba_dados.set_row(0, 48)
        for indice, valor in enumerate(exportacao.columns):
            aba_dados.write(0, indice, valor, cabecalho)
        if not exportacao.empty:
            indice_resultado = exportacao.columns.get_loc("Resultado")
            aba_dados.conditional_format(
                1, indice_resultado, len(exportacao), indice_resultado,
                {"type": "cell", "criteria": "==", "value": '"Reprovado"', "format": destaque},
            )
    return saida.getvalue()
