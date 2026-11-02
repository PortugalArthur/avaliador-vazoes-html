"""Teste t de Welch entre vazoes historicas e sinteticas."""

from infraestrutura.preparar_ambiente import garantir_dependencias

garantir_dependencias({"numpy": "numpy>=1.24", "scipy": "scipy>=1.11"})

import numpy as np
from scipy import stats


def avaliar_welch_resumo(
    n_historico,
    media_historica,
    variancia_historica,
    n_sintetico,
    media_sintetica,
    variancia_sintetica,
    alfa=0.05,
):
    """Executa o Welch a partir das estatisticas amostrais das duas fontes."""
    if not 0 < alfa < 1:
        raise ValueError("alfa deve estar entre 0 e 1.")

    n_historico = int(n_historico)
    n_sintetico = int(n_sintetico)
    if n_historico < 2:
        raise ValueError("historico: informe pelo menos 2 valores.")
    if n_sintetico < 2:
        raise ValueError("sintetico: informe pelo menos 2 valores.")

    estatisticas = np.asarray(
        [media_historica, variancia_historica, media_sintetica, variancia_sintetica],
        dtype=float,
    )
    if not np.isfinite(estatisticas).all():
        raise ValueError("As estatisticas amostrais devem ser finitas.")
    if variancia_historica < 0 or variancia_sintetica < 0:
        raise ValueError("As variancias amostrais nao podem ser negativas.")

    media_historica = float(media_historica)
    media_sintetica = float(media_sintetica)
    variancia_historica = float(variancia_historica)
    variancia_sintetica = float(variancia_sintetica)

    # Diferenca entre as medias, em m3/s: sintetico menos historico.
    diferenca_m3s = media_sintetica - media_historica

    # Variancia do erro-padrao da diferenca entre as medias.
    variancia_erro = (
        variancia_sintetica / n_sintetico
        + variancia_historica / n_historico
    )

    # O teste nao pode continuar com erro-padrao nulo ou invalido.
    if not np.isfinite(variancia_erro) or variancia_erro <= 0:
        raise ValueError("Erro-padrao nulo ou invalido.")

    erro_padrao = np.sqrt(variancia_erro)
    # Estatistica t de Welch.
    t = diferenca_m3s / erro_padrao

    # Graus de liberdade de Welch-Satterthwaite.
    # As variaveis de variancia ja representam s ao quadrado.
    parcela_sintetica = variancia_sintetica / n_sintetico
    parcela_historica = variancia_historica / n_historico

    # No numerador, elevamos ao quadrado a soma completa das duas parcelas.
    numerador_gl = variancia_erro ** 2

    # No denominador, cada parcela e elevada ao quadrado separadamente.
    denominador_gl = (
        parcela_sintetica ** 2 / (n_sintetico - 1)
        + parcela_historica ** 2 / (n_historico - 1)
    )

    if not np.isfinite(denominador_gl) or denominador_gl <= 0:
        raise ValueError("Nao foi possivel calcular os graus de liberdade.")

    graus_liberdade = numerador_gl / denominador_gl

    if not np.isfinite(graus_liberdade) or graus_liberdade <= 0:
        raise ValueError("Graus de liberdade invalidos.")

    # P-valor bilateral: considera diferencas positivas e negativas entre as medias.
    p_valor = 2 * stats.t.sf(abs(t), df=graus_liberdade)

    # Intervalo de confianca bilateral da diferenca entre as medias.
    t_critico = stats.t.ppf(1 - alfa / 2, df=graus_liberdade)
    margem_erro = t_critico * erro_padrao
    ic_inferior = diferenca_m3s - margem_erro
    ic_superior = diferenca_m3s + margem_erro

    # Decisao nominal do teste para o nivel de significancia informado.
    rejeita_igualdade = bool(p_valor < alfa)

    return {
        "n_historico": n_historico,
        "n_sintetico": n_sintetico,
        "media_historica": media_historica,
        "media_sintetica": media_sintetica,
        "variancia_historica": variancia_historica,
        "variancia_sintetica": variancia_sintetica,
        "desvio_padrao_historico": float(np.sqrt(variancia_historica)),
        "desvio_padrao_sintetico": float(np.sqrt(variancia_sintetica)),
        "diferenca_m3s": float(diferenca_m3s),
        "erro_padrao": float(erro_padrao),
        "t": float(t),
        "graus_liberdade": float(graus_liberdade),
        "p_valor": float(p_valor),
        "alfa": float(alfa),
        "t_critico": float(t_critico),
        "margem_erro": float(margem_erro),
        "ic_inferior": float(ic_inferior),
        "ic_superior": float(ic_superior),
        "rejeita_igualdade": rejeita_igualdade,
    }


def avaliar_welch(historico, sintetico, alfa=0.05):
    """Compara as medias usando a convencao sintetico menos historico."""
    if not 0 < alfa < 1:
        raise ValueError("alfa deve estar entre 0 e 1.")

    h = np.asarray(historico, dtype=float)
    s = np.asarray(sintetico, dtype=float)

    # Etapa de validacao das amostras antes de qualquer calculo estatistico.
    for nome, vetor in (("historico", h), ("sintetico", s)):
        # Cada amostra deve ser um unico vetor de vazoes, e nao uma matriz.
        if vetor.ndim != 1:
            raise ValueError(f"{nome}: informe um vetor unidimensional.")

        # A variancia amostral exige pelo menos duas observacoes.
        if vetor.size < 2:
            raise ValueError(f"{nome}: informe pelo menos 2 valores.")

        # Valores ausentes ou infinitos nao sao removidos nem substituidos por zero.
        if not np.isfinite(vetor).all():
            raise ValueError(f"{nome}: existem valores ausentes ou infinitos.")

    # Estatisticas descritivas das duas amostras do estagio atual.
    n_historico = h.size
    n_sintetico = s.size

    media_historica = h.mean()
    media_sintetica = s.mean()

    # ddof=1 calcula a variancia amostral com divisor n - 1.
    variancia_historica = h.var(ddof=1)
    variancia_sintetica = s.var(ddof=1)

    # O calculo central e compartilhado com o processamento global do dashboard.
    return avaliar_welch_resumo(
        n_historico,
        media_historica,
        variancia_historica,
        n_sintetico,
        media_sintetica,
        variancia_sintetica,
        alfa=alfa,
    )
