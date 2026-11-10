# Conferência dos contadores, percentuais e filtros

Verificação realizada em 6 de novembro de 2026, sobre os relatórios reais já gerados. O objetivo foi conferir a contagem dos resultados, sem refazer ou modificar as fórmulas de Welch, Levene, KS, correlações ou sequências.

## Resultado

Não foram encontradas divergências nas contagens e nos percentuais examinados, inclusive após aplicar o intervalo de estágios. Não foi necessária uma correção no programa.

Foram examinados os três relatórios em `relatorios/`:

- `analise_novo_modelo_V20.html`;
- `comparacao_novo_modelo_newave_V20.html`;
- `comparacao_novo_modeloV_19_VS_V_20.html`.

As verificações usaram os resultados efetivamente incorporados nesses arquivos, e não dados criados para reproduzir uma resposta esperada.

## Como foi conferido

Uma rotina independente em Python contou as linhas por usina e estágio. Essas contagens foram comparadas com a função usada pelo HTML, com os indicadores visíveis, com as tabelas desenhadas e com os percentuais escritos nos gráficos.

Para cada teste e modelo, foram conferidos 84 intervalos: todos os 72 estágios isoladamente, anos completos, horizonte completo, metades do horizonte e intervalos atravessando anos. Considerando as cinco participações de modelos nos três relatórios e os três testes, isso corresponde a **1260 conferências de intervalos**.

Também foram exercitados os próprios controles deslizantes no navegador, nos intervalos 0–71, 0–0, 5–17, 35–36 e 71–71, em cada uma das três primeiras abas dos três relatórios. Foram conferidos os valores visíveis dos seis indicadores e das linhas mostradas nas tabelas de resumo e ranking.

## Regras confirmadas

1. **Combinações calculadas:** contam apenas as linhas com status “Calculado” e p-valor numérico entre 0 e 1.
2. **Combinações reprovadas:** contam apenas os testes válidos com p-valor menor que 0,05. Um p-valor exatamente igual a 0,05 não é reprovado.
3. **Percentual de combinações aprovadas:** `100 × (calculadas − reprovadas) / calculadas`. Testes não calculados ficam fora desse denominador. Sem testes válidos, aparece “—”.
4. **Total de usinas no teste:** cada usina entra uma única vez e precisa ter pelo menos um teste válido dentro do intervalo selecionado.
5. **Usinas reprovadas:** cada usina com uma ou mais reprovações no intervalo conta uma única vez.
6. **Usinas completamente aprovadas:** precisam ter todos os estágios do intervalo calculados e aprovados. Uma usina sem reprovações, mas com algum teste indisponível, não é completamente aprovada.
7. **Percentual de usinas completamente aprovadas:** usa como denominador o total de usinas no teste, definido no item 4.
8. **Resumo por estágio:** suas contagens somam os totais gerais. Seu percentual de reprovação usa apenas os testes válidos daquele estágio.
9. **Ranking:** as quantidades de estágios calculados, reprovados e não calculados respeitam o intervalo. Empates recebem a mesma posição; a posição seguinte considera quantas usinas ficaram à frente.
10. **Filtros:** o intervalo altera indicadores, resumo, ranking e memorial. A busca por nome e o filtro de resultado da parte geral restringem somente o memorial, conforme o texto da própria interface. A busca interna de uma tabela restringe apenas aquela tabela.

As decisões booleanas gravadas nos resultados também foram comparadas com o critério `p < 0,05`; não houve inconsistências nos relatórios examinados. Não foram encontradas combinações usina–estágio duplicadas nas tabelas auditadas.

## Exemplo real com filtro

No teste de médias do Novo modelo V20:

| Intervalo de estágios | Calculadas | Reprovadas | Aprovadas (%) | Usinas no teste | Usinas com reprovação | Usinas completamente aprovadas (%) |
|---|---:|---:|---:|---:|---:|---:|
| 0–71 | 11142 | 1924 | 82,73 | 155 | 128 | 16,77 |
| 0–0 | 155 | 102 | 34,19 | 155 | 102 | 34,19 |
| 5–17 | 2011 | 800 | 60,22 | 155 | 111 | 27,74 |
| 35–36 | 309 | 21 | 93,20 | 155 | 11 | 92,26 |
| 71–71 | 154 | 1 | 99,35 | 154 | 1 | 99,35 |

No horizonte completo, existem 11448 combinações possíveis: 159 usinas × 72 estágios. Das 306 combinações não calculadas, 288 pertencem a quatro usinas sem testes válidos e 18 pertencem a Pimental.

Pimental tem 54 testes de médias válidos, todos aprovados, e 18 indisponíveis. Portanto, participa das 155 usinas no teste, mas não das 26 completamente aprovadas. Isso explica por que **16,77% não é simplesmente o complemento do percentual das 128 usinas reprovadas**. Há uma usina com comparação incompleta.

## Demais indicadores

- **Gráficos de p-valor:** foram conferidas 30 anotações, para Camargos, nos três testes, no horizonte completo e apenas no estágio 36, nos três relatórios. O percentual usa somente os testes válidos da usina e do intervalo. As barras e suas cores também coincidiram com os resultados gravados.
- **P50/P90 de sequências:** foram recontados os indicadores a partir das tabelas por usina. A comparação é estrita: percentil sintético maior que o histórico. Igualdades entram no denominador; usinas sem comparação ficam fora. Foram conferidos 30 indicadores e sua apresentação no HTML. Esses percentuais não são taxas de aprovação de testes.
- **Correlação anual entre bacias:** as quantidades de cenários válidos e indisponíveis foram confrontadas com os coeficientes individuais, em 525 participações de pares de bacias nos relatórios. Essa análise não possui p-valor ou taxa de aprovação.
- **Casos de fronteira:** sete situações pequenas, declaradas somente em memória para verificar a lógica, cobriram p = 0,05, p = 0, p = 1, resultados inválidos, ausência de uma linha, nenhum teste válido e seleção vazia. Esses casos não alteraram os relatórios reais.

## Evidências e reprodução

A rotina fica em `testes/verificar_contadores.py`. A partir da pasta do programa:

```powershell
python -m testes.verificar_contadores relatorios/comparacao_novo_modeloV_19_VS_V_20.html relatorios/comparacao_novo_modelo_newave_V20.html relatorios/analise_novo_modelo_V20.html
```

As contagens por intervalo e verificações do navegador ficam em `outputs/verificacao/contadores/`, em um JSON para cada relatório. O arquivo `integridade_calculos.json` confirma que os 16 módulos de cálculo continuam com os mesmos hashes da verificação anterior. Os relatórios originais permaneceram com tamanho e data de modificação preservados.

Esta conferência valida a agregação e a aplicação dos filtros nos arquivos examinados. A verificação manual das contas individuais dos testes é uma etapa complementar, que permanece separada desta auditoria.
