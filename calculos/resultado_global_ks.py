"""KS mensal para todas as UHEs, resumo por estágio e exportação Excel."""

from io import BytesIO

from calculos.base_estatistica_cobre import NOMES_MESES, _preparar_historico
from calculos.resultado_global_levene import _iterar_grupos
from calculos.teste_ks_cobre import preparar_amostras_ks

import duckdb
import numpy as np
import pandas as pd


COLUNA_DECISAO = "rejeita_igualdade_distribuicoes"
METODO = "KS assintótico bilateral — distribuição limite de Kolmogorov"
REFERENCIA = "https://www.maxwell.vrac.puc-rio.br/15500/15500_6.PDF#page=29"
COLUNAS_IDENTIFICACAO = [
    "hydro_id", "nome_usina", "stage_id", "inicio_estagio", "fim_estagio",
    "ordem_estagio", "ano", "mes", "mes_nome", "rotulo_estagio",
    "historico_inicio", "historico_fim", "primeiro_mes_historico_usado",
    "ultimo_mes_historico_usado", "lacunas_historicas", "metodo",
]
COLUNAS_ESCALARES = [
    "n_historico", "n_sintetico", "n_efetivo", "estatistica_ks", "z_ks",
    "vazao_maxima", "contagem_historico_maximo", "contagem_sintetico_maximo",
    "acumulado_historico_maximo", "acumulado_sintetico_maximo",
    "repeticoes_historico", "repeticoes_sintetico", "repeticoes_conjunto",
    "p_valor", "alfa", COLUNA_DECISAO,
]
COLUNAS_RESULTADO = COLUNAS_IDENTIFICACAO + COLUNAS_ESCALARES + [
    "resultado", "status_teste", "motivo_nao_calculado",
]
COLUNAS_INTEIRAS = [
    "hydro_id", "stage_id", "ordem_estagio", "ano", "mes", "lacunas_historicas",
    "n_historico", "n_sintetico", "contagem_historico_maximo", "contagem_sintetico_maximo",
    "repeticoes_historico", "repeticoes_sintetico", "repeticoes_conjunto",
]
NOMES_COLUNAS = {
    "hydro_id": "ID da UHE", "nome_usina": "Usina", "stage_id": "ID do estágio",
    "inicio_estagio": "Início do estágio", "fim_estagio": "Fim do estágio",
    "ordem_estagio": "Ordem cronológica (base zero)", "ano": "Ano", "mes": "Mês",
    "mes_nome": "Nome do mês", "rotulo_estagio": "Estágio e período",
    "historico_inicio": "Início do histórico da UHE", "historico_fim": "Fim do histórico da UHE",
    "primeiro_mes_historico_usado": "Primeiro mês histórico usado",
    "ultimo_mes_historico_usado": "Último mês histórico usado",
    "lacunas_historicas": "Lacunas mensais no histórico", "metodo": "Método",
    "n_historico": "N histórico", "n_sintetico": "N sintético", "n_efetivo": "Tamanho efetivo",
    "estatistica_ks": "Distância KS (D)", "z_ks": "Kolmogorov–Smirnov Z",
    "vazao_maxima": "Vazão da maior distância (m³/s)",
    "contagem_historico_maximo": "Histórico acumulado em x* (contagem)",
    "contagem_sintetico_maximo": "Sintético acumulado em x* (contagem)",
    "acumulado_historico_maximo": "Histórico acumulado em x* (proporção)",
    "acumulado_sintetico_maximo": "Sintético acumulado em x* (proporção)",
    "repeticoes_historico": "Repetições no histórico",
    "repeticoes_sintetico": "Repetições no sintético",
    "repeticoes_conjunto": "Repetições no conjunto das amostras",
    "p_valor": "p-valor assintótico bilateral", "alfa": "Alfa",
    COLUNA_DECISAO: "Rejeita igualdade das distribuições",
    "resultado": "Resultado", "status_teste": "Status do teste",
    "motivo_nao_calculado": "Motivo de não cálculo",
    "combinacoes_esperadas": "Combinações esperadas",
    "combinacoes_calculadas": "Combinações calculadas",
    "combinacoes_reprovadas": "Reprovações", "combinacoes_nao_reprovadas": "Não reprovadas",
    "combinacoes_nao_calculadas": "Não calculadas", "percentual_reprovado": "Reprovações (%)",
}


def _validar_alfa(alfa):
    if not np.isfinite(alfa) or not 0 < alfa < 1:
        raise ValueError("alfa deve estar entre 0 e 1.")


def _identificacao(hydro_id, nome, stage_id, etapa, alfa):
    return {
        "hydro_id": int(hydro_id), "nome_usina": nome, "stage_id": int(stage_id),
        "inicio_estagio": etapa["inicio"], "fim_estagio": etapa["fim"],
        "ordem_estagio": etapa["ordem"], "ano": etapa["ano"], "mes": etapa["mes"],
        "mes_nome": NOMES_MESES[etapa["mes"]],
        "rotulo_estagio": f"{etapa['mes']:02d}/{etapa['ano']} — stage {stage_id}",
        "alfa": float(alfa), "metodo": METODO,
    }


def _avaliar_linha(linha, historico, sintetico, alfa, motivo=""):
    linha = {**linha, "n_historico": len(historico), "n_sintetico": len(sintetico)}
    if not motivo:
        try:
            calculo = preparar_amostras_ks(historico, sintetico, alfa)
        except ValueError as erro:
            motivo = str(erro)
        else:
            # Vetores das curvas ficam somente no cálculo individual do estágio.
            linha.update({chave: calculo[chave] for chave in COLUNAS_ESCALARES})
    linha.update(
        status_teste="Não calculado" if motivo else "Calculado",
        resultado="Não calculado" if motivo else "Reprovado" if linha[COLUNA_DECISAO] else "Não reprovado",
        motivo_nao_calculado=motivo,
    )
    return linha


def _tabela(linhas):
    dados = pd.DataFrame(linhas).reindex(columns=COLUNAS_RESULTADO)
    dados[COLUNA_DECISAO] = dados[COLUNA_DECISAO].astype("boolean")
    for coluna in COLUNAS_ESCALARES:
        if coluna != COLUNA_DECISAO:
            dados[coluna] = pd.to_numeric(dados[coluna], errors="coerce")
    return dados.sort_values(["nome_usina", "hydro_id", "ordem_estagio"], kind="stable").reset_index(drop=True)


def calcular_ks_por_estagio(organizacao, alfa=0.05):
    """Um teste por estágio da UHE, usando o mesmo núcleo do processamento global."""
    _validar_alfa(alfa)
    linhas = []
    for ordem, (stage_id, amostra) in enumerate(organizacao.amostras_por_estagio.items()):
        etapa = {"inicio": amostra.start_date, "fim": amostra.end_date,
                 "ano": amostra.year, "mes": amostra.month, "ordem": ordem}
        linha = _identificacao(amostra.hydro_id, amostra.hydro_name, stage_id, etapa, alfa)
        linha.update(
            historico_inicio=str(organizacao.historico_inicio), historico_fim=str(organizacao.historico_fim),
            lacunas_historicas=len(organizacao.meses_historicos_ausentes),
            primeiro_mes_historico_usado=str(amostra.historico.index.min()) if len(amostra.historico) else None,
            ultimo_mes_historico_usado=str(amostra.historico.index.max()) if len(amostra.historico) else None,
        )
        linhas.append(_avaliar_linha(linha, amostra.historico, amostra.sintetico, alfa))
    return _tabela(linhas)


def calcular_ks_todas_usinas(consolidado, historico, nomes, calendario, alfa=0.05, *, vetores_por_lote=16):
    """Identifica o horizonte e compara amostras mensais em grupos completos."""
    _validar_alfa(alfa)
    if vetores_por_lote < 1:
        raise ValueError("O tamanho do lote deve ser positivo.")
    conexao = duckdb.connect(database=":memory:")
    conexao.execute("SET enable_progress_bar = false")
    try:
        metadados = conexao.execute(
            "SELECT DISTINCT hydro_id, stage_id FROM read_parquet(?)", [str(consolidado)]
        ).df()
        if metadados.empty:
            return _tabela([])
        if metadados.isna().any().any():
            raise ValueError("O consolidado possui IDs de UHE ou estágio ausentes.")
        usinas = sorted(int(valor) for valor in metadados.hydro_id.unique())
        ids = {int(valor) for valor in metadados.stage_id.unique()}
        if ids - set(calendario):
            raise ValueError(f"Estágios sem calendário no stages.json: {sorted(ids - set(calendario))}")
        estagios = sorted(ids, key=lambda valor: calendario[valor]["inicio"])
        for stage_id in estagios:
            etapa = calendario[stage_id]
            if etapa["mes"] != etapa["inicio"].month or etapa["ano"] != etapa["inicio"].year:
                raise ValueError(f"Mês/ano incompatível com a data do estágio {stage_id}.")
        avisos = [f"Lacuna no horizonte entre os estágios {a} e {b}."
                  for a, b in zip(estagios, estagios[1:]) if calendario[a]["fim"] != calendario[b]["inicio"]]
        extras = sorted(set(calendario) - ids)
        if extras:
            avisos.append(f"Estágios do calendário sem cenários no consolidado: {extras}.")
        dados_h = conexao.execute(
            "SELECT hydro_id, start_date, end_date, value_m3s FROM read_parquet(?) ORDER BY hydro_id, start_date",
            [str(historico)],
        ).df()
        historicos = {}
        for hydro_id, grupo in dados_h.groupby("hydro_id", sort=False):
            try:
                preparado, inicio, fim, lacunas = _preparar_historico(grupo, int(hydro_id))
            except ValueError as erro:
                historicos[int(hydro_id)] = {"motivo": str(erro), "meses": {}}
                continue
            historicos[int(hydro_id)] = {
                "motivo": "", "historico_inicio": str(inicio), "historico_fim": str(fim),
                "lacunas_historicas": len(lacunas),
                "meses": {mes: g.set_index("periodo")["value_m3s"].sort_index()
                          for mes, g in preparado.groupby("month", sort=False)},
            }
        del dados_h
        referencias, vistos, linhas = {}, set(), []

        def montar_linha(hydro_id, stage_id, grupo):
            etapa = calendario[stage_id]
            linha = _identificacao(hydro_id, nomes.get(hydro_id, "Usina sem nome"), stage_id, etapa, alfa)
            contexto = historicos.get(hydro_id, {"motivo": "UHE sem histórico.", "meses": {}})
            linha.update({k: v for k, v in contexto.items() if k not in ("motivo", "meses")})
            h = contexto["meses"].get(etapa["mes"], pd.Series(dtype=float))
            linha.update(primeiro_mes_historico_usado=str(h.index.min()) if len(h) else None,
                         ultimo_mes_historico_usado=str(h.index.max()) if len(h) else None)
            motivo, s = contexto["motivo"], []
            if grupo is None:
                motivo = "Sem cenários para a UHE e estágio."
            else:
                s = grupo["valor"].to_numpy(dtype=float)
                ids_cenarios = grupo["scenario_id"]
                conjunto = frozenset(ids_cenarios.tolist())
                referencia = referencias.setdefault(hydro_id, conjunto)
                if ids_cenarios.isna().any() or ids_cenarios.duplicated().any():
                    motivo = "IDs de cenários ausentes ou repetidos na UHE e estágio."
                elif conjunto != referencia:
                    motivo = "Conjunto de cenários diferente do primeiro estágio disponível da UHE."
            if not motivo and len(h) == 0:
                motivo = f"Sem histórico de {NOMES_MESES[etapa['mes']]} para a UHE."
            return _avaliar_linha(linha, h, s, alfa, motivo)

        # Reutiliza apenas o leitor em lotes do Levene; as contas são do KS.
        for (hydro_id, stage_id), grupo in _iterar_grupos(conexao, consolidado, calendario, vetores_por_lote):
            linhas.append(montar_linha(hydro_id, stage_id, grupo))
            vistos.add((hydro_id, stage_id))
        for hydro_id in usinas:
            for stage_id in estagios:
                if (hydro_id, stage_id) not in vistos:
                    linhas.append(montar_linha(hydro_id, stage_id, None))
        tabela = _tabela(linhas)
        tabela.attrs["avisos_horizonte"] = avisos
        return tabela
    finally:
        conexao.close()


def resumir_ks_por_estagio(resultados):
    chaves = ["ordem_estagio", "stage_id", "inicio_estagio", "mes_nome"]
    contagens = ["combinacoes_esperadas", "combinacoes_calculadas", "combinacoes_reprovadas",
                 "combinacoes_nao_reprovadas", "combinacoes_nao_calculadas", "percentual_reprovado"]
    if resultados.empty:
        return pd.DataFrame(columns=chaves + contagens)
    dados = resultados.copy()
    dados["calculado"] = dados.status_teste.eq("Calculado")
    dados["reprovado"] = dados.calculado & dados[COLUNA_DECISAO].fillna(False)
    resumo = dados.groupby(chaves, as_index=False).agg(
        combinacoes_esperadas=("hydro_id", "size"), combinacoes_calculadas=("calculado", "sum"),
        combinacoes_reprovadas=("reprovado", "sum"),
    ).sort_values("ordem_estagio")
    for c in contagens[:3]:
        resumo[c] = resumo[c].astype(int)
    resumo["combinacoes_nao_reprovadas"] = resumo.combinacoes_calculadas - resumo.combinacoes_reprovadas
    resumo["combinacoes_nao_calculadas"] = resumo.combinacoes_esperadas - resumo.combinacoes_calculadas
    resumo["percentual_reprovado"] = 100 * resumo.combinacoes_reprovadas / resumo.combinacoes_calculadas.replace(0, np.nan)
    return resumo[chaves + contagens].reset_index(drop=True)


def gerar_excel_ks(resultados, alfa=0.05):
    """Uma exportação completa no padrão visual do Welch e Levene."""
    from infraestrutura.preparar_ambiente import garantir_dependencias
    garantir_dependencias({"xlsxwriter": "XlsxWriter>=3.2"})
    _validar_alfa(alfa)
    calculados = resultados.status_teste.eq("Calculado")
    reprovados = calculados & resultados[COLUNA_DECISAO].fillna(False)
    indicadores = pd.DataFrame({"Indicador": [
        "Nível de significância (alfa)", "Combinações UHE-estágio calculadas",
        "Combinações UHE-estágio reprovadas", "UHEs com ao menos uma reprovação",
        "Combinações que não puderam ser calculadas", "Método", "Referência",
        "Observação sobre repetições",
    ], "Valor": [alfa, int(calculados.sum()), int(reprovados.sum()),
                 int(resultados.loc[reprovados, "hydro_id"].nunique()), int((~calculados).sum()),
                 METODO, REFERENCIA, "Observações repetidas preservadas; referência assintótica para distribuições contínuas."]})
    dados = resultados.reindex(columns=COLUNAS_RESULTADO).sort_values(
        ["nome_usina", "hydro_id", "ordem_estagio"], kind="stable"
    ).copy()
    for c in COLUNAS_INTEIRAS:
        dados[c] = pd.to_numeric(dados[c], errors="coerce").astype("Int64")
    for c in ["inicio_estagio", "fim_estagio"]:
        dados[c] = pd.to_datetime(dados[c])
    dados[COLUNA_DECISAO] = dados[COLUNA_DECISAO].map({True: "Sim", False: "Não"})
    resumo = resumir_ks_por_estagio(resultados).drop(columns="ordem_estagio")
    resumo["inicio_estagio"] = pd.to_datetime(resumo["inicio_estagio"])
    saida = BytesIO()
    with pd.ExcelWriter(saida, engine="xlsxwriter", date_format="dd/mm/yyyy", datetime_format="dd/mm/yyyy",
                        engine_kwargs={"options": {"strings_to_formulas": False, "strings_to_urls": False}}) as escritor:
        indicadores.to_excel(escritor, sheet_name="Resumo geral", index=False, startrow=2)
        resumo.rename(columns=NOMES_COLUNAS).to_excel(escritor, sheet_name="Resumo por estágio", index=False)
        dados.rename(columns=NOMES_COLUNAS).to_excel(escritor, sheet_name="Resultados completos", index=False)
        livro = escritor.book
        cabecalho = livro.add_format({"bold": True, "font_color": "white", "bg_color": "#4C1D95",
                                     "border": 1, "text_wrap": True, "valign": "vcenter"})
        titulo = livro.add_format({"bold": True, "font_size": 16, "font_color": "#4C1D95"})
        inteiro = livro.add_format({"num_format": "0"})
        decimal = livro.add_format({"num_format": "0.000000"})
        data = livro.add_format({"num_format": "dd/mm/yyyy"})
        percentual = livro.add_format({"num_format": '0.00"%"'})
        destaque = livro.add_format({"bg_color": "#FECACA", "font_color": "#991B1B"})
        geral = escritor.sheets["Resumo geral"]
        geral.write("A1", "Teste de Kolmogorov–Smirnov para todas as usinas", titulo)
        geral.set_column("A:A", 46)
        geral.set_column("B:B", 72, inteiro)
        geral.write_number(3, 1, alfa, decimal)
        geral.freeze_panes(3, 0)
        for i, valor in enumerate(indicadores.columns):
            geral.write(2, i, valor, cabecalho)
        for nome, tabela in [("Resumo por estágio", resumo), ("Resultados completos", dados)]:
            aba = escritor.sheets[nome]
            aba.freeze_panes(1, 2 if nome == "Resultados completos" else 0)
            aba.autofilter(0, 0, len(tabela), len(tabela.columns) - 1)
            aba.set_row(0, 48)
            for i, c in enumerate(tabela.columns):
                formato = data if c in ("inicio_estagio", "fim_estagio") else percentual if c == "percentual_reprovado" else (
                    inteiro if pd.api.types.is_integer_dtype(tabela[c]) else decimal if pd.api.types.is_numeric_dtype(tabela[c]) else None)
                largura = 48 if c in ("metodo", "motivo_nao_calculado") else 32 if c == "nome_usina" else 23
                aba.set_column(i, i, largura, formato)
                aba.write(0, i, NOMES_COLUNAS.get(c, c), cabecalho)
        if len(dados):
            i = dados.columns.get_loc("resultado")
            escritor.sheets["Resultados completos"].conditional_format(
                1, i, len(dados), i, {"type": "cell", "criteria": "==", "value": '"Reprovado"', "format": destaque})
    return saida.getvalue()
