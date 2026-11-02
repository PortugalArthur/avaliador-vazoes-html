"""Construção por etapas do teste de Levene original, baseado na média."""

from infraestrutura.preparar_ambiente import garantir_dependencias

garantir_dependencias({"numpy": "numpy>=1.24", "scipy": "scipy>=1.11"})

import numpy as np
from scipy import stats


class ErroCalculoLevene(ValueError):
    """Conserva as etapas já calculadas quando uma validação interrompe o teste."""

    def __init__(self, mensagem, diagnostico):
        super().__init__(mensagem)
        self.diagnostico = diagnostico


def preparar_medias_levene(historico, sintetico, alfa=0.05):
    """Calcula o Levene original e a decisão para uma UHE e estágio."""
    # Validação: alfa é o nível de significância e deve ficar entre 0 e 1.
    # Por padrão, 0.05 representa o nível de significância de 5%.
    if not 0 < alfa < 1:
        raise ValueError("alfa deve estar entre 0 e 1.")

    # Preparação: transforma cada amostra em um vetor de números reais.
    h = np.asarray(historico, dtype=float)
    s = np.asarray(sintetico, dtype=float)

    # Validação: confere as amostras antes de iniciar as contas.
    for nome, vetor in (("histórico", h), ("sintético", s)):
        if vetor.ndim != 1:
            raise ValueError(f"{nome}: informe um vetor unidimensional.")
        if vetor.size < 2:
            raise ValueError(f"{nome}: informe pelo menos 2 valores.")
        if not np.isfinite(vetor).all():
            raise ValueError(f"{nome}: existem valores ausentes ou infinitos.")

    # Etapa 1: conta quantas vazões existem em cada amostra.
    n_historico = h.size
    n_sintetico = s.size

    # Etapa 1: soma as vazões e divide pela quantidade da própria amostra.
    media_historica = h.mean()
    media_sintetica = s.mean()

    # Etapa 2: subtrai de cada vazão a média da sua própria amostra.
    # np.abs remove o sinal: tanto valores acima quanto abaixo da média
    # resultam em distâncias positivas ou iguais a zero.
    desvios_absolutos_historicos = np.abs(h - media_historica)
    desvios_absolutos_sinteticos = np.abs(s - media_sintetica)

    # Etapa 3: calcula a média das distâncias absolutas em cada amostra.
    # Cada resultado indica quanto as vazões se afastam, em média,
    # da média da sua própria amostra, em m³/s.
    media_desvios_historicos = desvios_absolutos_historicos.mean()
    media_desvios_sinteticos = desvios_absolutos_sinteticos.mean()

    # Etapa 4: calcula a média geral das distâncias absolutas.
    # A média de cada grupo recebe o peso da quantidade de valores do grupo.
    # Isso equivale a somar todas as distâncias e dividir pelo total de valores.
    media_geral_desvios = (
        n_historico * media_desvios_historicos
        + n_sintetico * media_desvios_sinteticos
    ) / (n_historico + n_sintetico)

    # Etapa 5: calcula a soma dos quadrados entre os grupos.
    # Subtrai a média geral da média das distâncias de cada grupo,
    # eleva a diferença ao quadrado e multiplica pelo tamanho do grupo.
    # Depois soma as contribuições histórica e sintética.
    soma_quadrados_entre_grupos = (
        n_historico * (media_desvios_historicos - media_geral_desvios) ** 2
        + n_sintetico * (media_desvios_sinteticos - media_geral_desvios) ** 2
    )

    # Etapa 6: calcula a soma dos quadrados dentro dos grupos.
    # Para cada distância absoluta, subtrai a média das distâncias do próprio
    # grupo, eleva a diferença ao quadrado e soma todos os termos.
    # Por fim, soma as contribuições histórica e sintética.
    soma_quadrados_dentro_grupos = (
        ((desvios_absolutos_historicos - media_desvios_historicos) ** 2).sum()
        + ((desvios_absolutos_sinteticos - media_desvios_sinteticos) ** 2).sum()
    )

    # Etapa 7: define os dois grupos e o total de observações.
    # Os grupos são histórico e sintético; N conta valores, não estágios.
    quantidade_grupos = 2
    total_observacoes = n_historico + n_sintetico

    # Graus de liberdade: k - 1 para a comparação entre os grupos
    # e N - k para a variação dentro dos grupos.
    graus_liberdade_entre = quantidade_grupos - 1
    graus_liberdade_dentro = total_observacoes - quantidade_grupos

    # Divide cada soma dos quadrados pelo respectivo grau de liberdade.
    quadrado_medio_entre = (
        soma_quadrados_entre_grupos / graus_liberdade_entre
    )
    quadrado_medio_dentro = (
        soma_quadrados_dentro_grupos / graus_liberdade_dentro
    )

    # Guarda resultados escalares para a tabela e para diagnosticar interrupções.
    diagnostico = {
        "n_historico": int(n_historico),
        "n_sintetico": int(n_sintetico),
        "media_historica": float(media_historica),
        "media_sintetica": float(media_sintetica),
        "media_desvios_historicos": float(media_desvios_historicos),
        "media_desvios_sinteticos": float(media_desvios_sinteticos),
        "media_geral_desvios": float(media_geral_desvios),
        "soma_quadrados_entre_grupos": float(soma_quadrados_entre_grupos),
        "soma_quadrados_dentro_grupos": float(soma_quadrados_dentro_grupos),
        "quantidade_grupos": int(quantidade_grupos),
        "total_observacoes": int(total_observacoes),
        "graus_liberdade_entre": int(graus_liberdade_entre),
        "graus_liberdade_dentro": int(graus_liberdade_dentro),
        "quadrado_medio_entre": float(quadrado_medio_entre),
        "quadrado_medio_dentro": float(quadrado_medio_dentro),
        "alfa": float(alfa),
    }

    # Validação: impede uma divisão por zero ou com denominador inválido.
    if not np.isfinite(quadrado_medio_dentro) or quadrado_medio_dentro <= 0:
        raise ErroCalculoLevene("Levene: denominador nulo ou inválido.", diagnostico)
    if not np.isfinite(quadrado_medio_entre) or quadrado_medio_entre < 0:
        raise ErroCalculoLevene("Levene: numerador inválido.", diagnostico)

    # Estatística W: razão entre os quadrados médios entre e dentro dos grupos.
    estatistica_levene = quadrado_medio_entre / quadrado_medio_dentro
    if not np.isfinite(estatistica_levene):
        raise ErroCalculoLevene("Levene: estatística W inválida.", diagnostico)
    diagnostico["estatistica_levene"] = float(estatistica_levene)

    # Etapa 8: calcula o p-valor usando a distribuição F de referência.
    # Sob a hipótese de variâncias iguais, a distribuição de W é aproximada
    # por uma F com k - 1 e N - k graus de liberdade.
    # sf calcula a área à direita do W observado: P(F >= W) = 1 - CDF(W).
    # Essa área já é o p-valor do Levene; não se multiplica por dois.
    p_valor = stats.f.sf(
        estatistica_levene,
        dfn=graus_liberdade_entre,
        dfd=graus_liberdade_dentro,
    )
    if not np.isfinite(p_valor) or not 0 <= p_valor <= 1:
        raise ErroCalculoLevene("Levene: p-valor inválido.", diagnostico)

    # Etapa 9: compara o p-valor com o nível de significância escolhido.
    # p < alfa: rejeita a hipótese de variâncias iguais (reprovação no teste).
    # p >= alfa: não rejeita essa hipótese; isso não prova que são iguais.
    rejeita_igualdade_variancias = bool(p_valor < alfa)

    # Retorna as etapas da conta e a decisão do teste de Levene.
    return {
        "n_historico": int(n_historico),
        "n_sintetico": int(n_sintetico),
        "media_historica": float(media_historica),
        "media_sintetica": float(media_sintetica),
        "desvios_absolutos_historicos": desvios_absolutos_historicos,
        "desvios_absolutos_sinteticos": desvios_absolutos_sinteticos,
        "media_desvios_historicos": float(media_desvios_historicos),
        "media_desvios_sinteticos": float(media_desvios_sinteticos),
        "media_geral_desvios": float(media_geral_desvios),
        "soma_quadrados_entre_grupos": float(soma_quadrados_entre_grupos),
        "soma_quadrados_dentro_grupos": float(soma_quadrados_dentro_grupos),
        "quantidade_grupos": int(quantidade_grupos),
        "total_observacoes": int(total_observacoes),
        "graus_liberdade_entre": int(graus_liberdade_entre),
        "graus_liberdade_dentro": int(graus_liberdade_dentro),
        "quadrado_medio_entre": float(quadrado_medio_entre),
        "quadrado_medio_dentro": float(quadrado_medio_dentro),
        "estatistica_levene": float(estatistica_levene),
        "p_valor": float(p_valor),
        "alfa": float(alfa),
        "rejeita_igualdade_variancias": rejeita_igualdade_variancias,
    }
