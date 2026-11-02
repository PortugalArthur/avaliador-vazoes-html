"""Construção por etapas do teste de Kolmogorov–Smirnov de duas amostras."""

from infraestrutura.preparar_ambiente import garantir_dependencias

garantir_dependencias({"numpy": "numpy>=1.24", "scipy": "scipy>=1.11"})

import numpy as np
from scipy import stats


def preparar_amostras_ks(historico, sintetico, alfa=0.05):
    """Calcula o KS assintótico bilateral para uma única UHE e estágio.

    O histórico deve conter somente o mês correspondente ao estágio.
    A seleção da UHE e a associação dos meses ficam a cargo do organizador.
    Referência: dissertação PUC-Rio 15500, seção 5.2.3, página 86.
    """
    # Validação: alfa representa a significância e deve estar entre 0 e 1.
    if not np.isfinite(alfa) or not 0 < alfa < 1:
        raise ValueError("alfa deve estar entre 0 e 1.")

    # Preparação: converte as amostras recebidas em vetores de números reais.
    try:
        historico = np.asarray(historico, dtype=float)
    except (TypeError, ValueError) as erro:
        raise ValueError("histórico: informe uma sequência de números reais.") from erro
    try:
        sintetico = np.asarray(sintetico, dtype=float)
    except (TypeError, ValueError) as erro:
        raise ValueError("sintético: informe uma sequência de números reais.") from erro

    # Etapa de validação: confere cada amostra antes de ordenar ou contar.
    for nome, vetor in (("histórico", historico), ("sintético", sintetico)):
        # Cada amostra deve ser um único vetor, sem linhas e colunas aninhadas.
        if vetor.ndim != 1:
            raise ValueError(f"{nome}: informe um vetor unidimensional.")
        # Precisamos de pelo menos uma observação em cada amostra.
        if vetor.size == 0:
            raise ValueError(f"{nome}: informe pelo menos 1 valor.")
        # Valores ausentes ou infinitos interrompem a preparação.
        # Nenhuma observação é excluída silenciosamente.
        if not np.isfinite(vetor).all():
            raise ValueError(f"{nome}: existem valores ausentes ou infinitos.")

    # Etapa 1: ordena as vazões da menor para a maior em cada amostra.
    # Valores repetidos e vazões iguais a zero permanecem no vetor.
    # np.sort produz um vetor ordenado sem alterar o vetor recebido.
    historico_ordenado = np.sort(historico)
    sintetico_ordenado = np.sort(sintetico)

    # Conta todas as observações, incluindo as repetições.
    # Os tamanhos vêm dos próprios dados e podem ser diferentes entre si.
    n_historico = historico_ordenado.size
    n_sintetico = sintetico_ordenado.size

    # Etapa 2: reúne as vazões observadas nas duas amostras em ordem crescente.
    # Cada vazão aparece uma vez nessa lista de pontos de comparação.
    # As repetições continuam preservadas dentro das amostras ordenadas.
    vazoes_comparacao = np.union1d(historico_ordenado, sintetico_ordenado)

    # Para cada vazão x, conta quantas observações de cada amostra são <= x.
    # side="right" inclui todos os valores iguais a x, inclusive repetições.
    # Como as amostras já estão ordenadas, a posição encontrada equivale
    # à quantidade de valores que atendem à condição.
    contagens_historico = np.searchsorted(
        historico_ordenado, vazoes_comparacao, side="right"
    )
    contagens_sintetico = np.searchsorted(
        sintetico_ordenado, vazoes_comparacao, side="right"
    )

    # Divide cada contagem pelo tamanho da sua própria amostra.
    # F_h(x) = quantidade de valores históricos <= x / n_historico.
    # F_s(x) = quantidade de valores sintéticos <= x / n_sintetico.
    # Os resultados são proporções entre 0 e 1, sem arredondamento.
    acumulados_historico = contagens_historico / n_historico
    acumulados_sintetico = contagens_sintetico / n_sintetico

    # Etapa 3: calcula a diferença entre as proporções em cada vazão x.
    # A convenção é sintético menos histórico: F_s(x) - F_h(x).
    diferencas_acumuladas = acumulados_sintetico - acumulados_historico

    # O módulo remove o sinal e mede a separação entre as curvas.
    # D = max_x |F_s(x) - F_h(x)|, uma proporção entre 0 e 1.
    distancias_absolutas = np.abs(diferencas_acumuladas)

    # np.argmax retorna a posição da maior distância, não a distância em si.
    # Se houver máximos exatamente iguais, escolhe a primeira posição.
    # Como as vazões estão ordenadas, essa posição corresponde à menor vazão.
    indice_maximo = int(np.argmax(distancias_absolutas))

    # Recupera a estatística D e a vazão em que essa distância foi encontrada.
    # D não tem unidade; a vazão associada continua expressa em m³/s.
    estatistica_ks = float(distancias_absolutas[indice_maximo])
    vazao_maxima = float(vazoes_comparacao[indice_maximo])

    # Etapa 4: calcula o tamanho efetivo das duas amostras.
    # n_efetivo = (n_historico * n_sintetico) / (n_historico + n_sintetico).
    # Esse fator ajusta D considerando a quantidade de valores de cada amostra.
    # Ele não altera as amostras nem reduz a quantidade de cenários utilizados.
    n_efetivo = (
        n_historico * n_sintetico
        / (n_historico + n_sintetico)
    )

    # Transforma D na estatística Z do KS assintótico bilateral.
    # Z = D * sqrt(n_efetivo), sem arredondamento das etapas intermediárias.
    z_ks = float(estatistica_ks * np.sqrt(n_efetivo))

    # Etapa 5: calcula o p-valor assintótico bilateral, como na referência.
    # K(z) é a função acumulada da distribuição limite de Kolmogorov.
    # p = 1 - K(Z) = 2 * soma_{k=1..infinito} (-1)^(k-1)*exp(-2*k²*Z²).
    # sf calcula essa cauda diretamente, com estabilidade numérica.
    # A distribuição já é bilateral: não se multiplica o resultado por dois.
    # Para Z = 0, sf retorna 1; não é necessário somar a série nesse ponto.
    p_valor = float(stats.kstwobign.sf(z_ks))
    if not np.isfinite(p_valor) or not 0 <= p_valor <= 1:
        raise ValueError("KS: p-valor assintótico inválido.")

    # Etapa 6: rejeita a igualdade das distribuições somente quando p < alfa.
    # Quando p = alfa, a hipótese de igualdade não é rejeitada.
    rejeita_igualdade_distribuicoes = bool(p_valor < alfa)

    # Diagnóstico: conta observações além da primeira de cada valor distinto.
    # Repetições são preservadas nas contas; a referência do p é contínua.
    repeticoes_historico = int(n_historico - np.unique(historico_ordenado).size)
    repeticoes_sintetico = int(n_sintetico - np.unique(sintetico_ordenado).size)
    repeticoes_conjunto = int(n_historico + n_sintetico - vazoes_comparacao.size)

    # Disponibiliza os resultados das etapas já implementadas.
    return {
        "historico_ordenado": historico_ordenado,
        "sintetico_ordenado": sintetico_ordenado,
        "n_historico": int(n_historico),
        "n_sintetico": int(n_sintetico),
        "vazoes_comparacao": vazoes_comparacao,
        "contagens_historico": contagens_historico,
        "contagens_sintetico": contagens_sintetico,
        "acumulados_historico": acumulados_historico,
        "acumulados_sintetico": acumulados_sintetico,
        "diferencas_acumuladas": diferencas_acumuladas,
        "distancias_absolutas": distancias_absolutas,
        "indice_maximo": indice_maximo,
        "estatistica_ks": estatistica_ks,
        "vazao_maxima": vazao_maxima,
        "n_efetivo": float(n_efetivo),
        "z_ks": z_ks,
        "contagem_historico_maximo": int(contagens_historico[indice_maximo]),
        "contagem_sintetico_maximo": int(contagens_sintetico[indice_maximo]),
        "acumulado_historico_maximo": float(acumulados_historico[indice_maximo]),
        "acumulado_sintetico_maximo": float(acumulados_sintetico[indice_maximo]),
        "repeticoes_historico": repeticoes_historico,
        "repeticoes_sintetico": repeticoes_sintetico,
        "repeticoes_conjunto": repeticoes_conjunto,
        "p_valor": p_valor,
        "alfa": float(alfa),
        "rejeita_igualdade_distribuicoes": rejeita_igualdade_distribuicoes,
    }
