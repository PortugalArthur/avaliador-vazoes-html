# Avaliador de vazões em HTML — plano completo de implementação

**Versão:** 1.1 · **Data:** 02/11/2026 · **Fuso dos relatórios:** America/Sao_Paulo.

**Estado desta entrega:** implementado e verificado em 02/11/2026.
O projeto contém os programas, três atalhos `.bat`, geradores independentes,
relatório real de comparação e evidências em `outputs/verificacao/`.
Consulte `README.md` e `VERIFICACAO_IMPLEMENTACAO.md` nesta pasta.

## 1. Objetivo

Criar um programa independente, na Área de Trabalho, que reaproveite os
geradores de Parquet e as análises do avaliador atual e produza um único
relatório HTML interativo, completo e consultável sem servidor ou internet.

O programa deverá funcionar com um modelo ou com os dois modelos. Em todos
os casos, os testes serão **modelo contra histórico**. A expressão
"Comparação" significa colocar os resultados das duas avaliações no mesmo
relatório, para consulta visual. Não significa testar um modelo contra o outro.

Não alterar os projetos existentes:

- `C:/Users/Pichau/Desktop/TESTES_ESTATISTICOS_COBRE`;
- `C:/Users/Pichau/Desktop/COMPARADOR_PARAMETROS_COBRE_NEWAVE`;
- `C:/Users/Pichau/Desktop/VAZOES_COBRE-main`.

O novo programa ficará em:

`C:/Users/Pichau/Desktop/AVALIADOR_VAZOES_HTML`.

## 2. Decisões fechadas com o usuário

| Tema | Regra obrigatória |
| --- | --- |
| Execução | Opções **Análise** e **Comparação** na janela de geração. |
| Análise | Histórico + um Parquet: novo modelo ou NEWAVE. |
| Comparação | Histórico + Parquet do novo modelo + Parquet NEWAVE. |
| Referência | Cada modelo é sempre comparado ao histórico, nunca ao outro modelo. |
| Horizonte em Comparação | Exatamente os mesmos meses/anos sintéticos nos dois modelos. |
| Usinas em Comparação | Exatamente o mesmo conjunto de usinas nos dois modelos. |
| Histórico | Pode ter períodos diferentes por modelo; recortar em memória, sem editar a fonte. |
| Períodos históricos | Mostrar início e fim de cada modelo na janela e permitir sua edição. |
| Significância | Fixa em **5%**, sem campo para alteração. |
| Entradas do deck | Escolher a pasta COBRE e localizar automaticamente cadastro, calendário e histórico. |
| Arquivo final | Um único HTML, sem arquivos de apoio necessários à consulta. |
| Exportações | Sem downloads de Excel, CSV ou outros memoriais externos. |
| Nome do HTML | Identificar modo, modelo(s), data e hora da geração. |
| Visão geral do SIN | Cinco abas, com indicadores e memoriais em cada análise. Correlação espacial inclui boxplots anuais entre bacias. |
| Resultado por Usina | Cinco abas, com gráficos e memoriais individuais. |
| Seleção de usina | Pelo **nome**, dentro de cada aba; não haverá seletor geral. |
| Tabelas em Comparação | Novo modelo primeiro e NEWAVE abaixo, intercalados por conteúdo. |
| Gráficos em Comparação | Novo modelo × histórico e, abaixo, NEWAVE × histórico, por tipo de gráfico. |
| Cores | Novo modelo ciano; histórico preto; NEWAVE laranja forte próximo do marrom, sem ser muito escuro. |
| Sequências | Horizonte completo, sem seletor de estágios; opções **Máximo** e **Média**, sem Mínimo. |

As escolhas complementares feitas para fechar o planejamento estão na seção 18.
Elas são decisões desta especificação, sem atribuí-las a pedidos explícitos.

## 3. Referências internas a reaproveitar

### 3.1. Avaliador atual

Raiz: `C:/Users/Pichau/Desktop/TESTES_ESTATISTICOS_COBRE`.

- `calculos/`: Welch, Levene, KS, correlações e sequências validados.
- `dados/`: validadores, metadados e cadastro de bacias ONS.
- `geradores/`: conversores COBRE e NEWAVE, incluindo parâmetros do PARPVAZ.
- `interface/`: referência dos gráficos e dos seis contadores dos testes.
- `testes/`: exemplos conhecidos e verificações de integração.

O reaproveitamento deverá preservar as fórmulas e os casos particulares
validados. Adaptar a organização e a apresentação não autoriza trocar o
método estatístico nem ajustar os números para aproximar resultados.

### 3.2. Comparador de parâmetros

Raiz: `C:/Users/Pichau/Desktop/COMPARADOR_PARAMETROS_COBRE_NEWAVE`.

Reaproveitar o padrão de janela de seleção de entradas, progresso, lembrança
dos últimos caminhos, visual de cabeçalho e cartões, abas, tabelas ordenáveis,
paginação e barras de rolagem horizontal superior e inferior sincronizadas.

Não incorporar suas regras de comparação de parâmetros, tolerâncias ou
classificação `sc`: este novo programa faz avaliações estatísticas de vazões.

### 3.3. Boxplot de vazões do programa anterior

Referência somente para leitura:

`C:/Users/Pichau/Desktop/VAZOES_COBRE-main/V1 analisador de vazoes/analisador_resultados_cobre.py`,
função `criar_boxplot`.

Reproduzir o boxplot por estágio com todas as vazões válidas dos cenários e
o histórico mensal correspondente. Não alterar esse programa nem trazer
para o novo visual a distribuição de slack, que não foi solicitada.

## 4. Dois conceitos distintos de modo

### 4.1. Modo de geração

Escolhido antes de calcular, gravado no relatório e identificado no título:

| Modo | Modelos presentes |
| --- | --- |
| Análise — novo modelo | Apenas novo modelo. |
| Análise — NEWAVE | Apenas NEWAVE. |
| Comparação | Novo modelo e NEWAVE. |

### 4.2. Modo de visualização

Escolhido no topo do HTML, sem gerar outro arquivo:

| Visualização | Abas |
| --- | --- |
| **Visão geral do SIN** | Teste de médias; Teste de variâncias; Teste de distribuição; Correlação espacial; Análise de sequências. |
| **Resultado por Usina** | Teste de médias; Teste de variâncias; Teste de distribuição; Correlação espacial; Análise de sequências. |

O HTML deverá abrir em **Visão geral do SIN → Teste de médias**, abrangendo
todas as usinas e o horizonte sintético completo.

Mudar de visualização não exclui dados e não recalcula os testes.
Guardar o estado de cada aba durante a navegação. Não aplicar o nome
selecionado em uma aba às demais abas.

## 5. Entradas e janela de geração

### 5.1. Campos e fluxo

1. Escolher **Análise** ou **Comparação**.
2. Em Análise, escolher **Novo modelo (COBRE)** ou **NEWAVE**.
3. Selecionar a **pasta do deck COBRE**.
4. Selecionar o(s) Parquet(s) necessário(s), em campos separados por modelo.
5. Conferir os arquivos encontrados, o horizonte, as usinas e os períodos
   históricos propostos para cada modelo.
6. Ajustar, se necessário, o início e o fim do histórico de cada modelo.
7. Clicar em **Gerar relatório HTML**.
8. Exibir o progresso, salvar em `relatorios/` e abrir o arquivo concluído.

O seletor de pasta deverá localizar exatamente:

| Informação | Caminho relativo à raiz do deck |
| --- | --- |
| Cadastro de usinas | `system/hydros.json` |
| Calendário sintético | `stages.json` |
| Histórico completo | `scenarios/inflow_history.parquet` |

Não procurar silenciosamente arquivos em outras pastas ou misturar decks.
Mostrar os nomes e caminhos encontrados. Em Análise, esconder/desabilitar
o campo do modelo não utilizado.

### 5.2. Período histórico por modelo

O arquivo histórico é escolhido indiretamente pela pasta do deck. O novo
programa deverá manter essa fonte intacta e criar referências filtradas em
memória ou em arquivos temporários próprios durante a geração.

Os campos devem ser início e fim em **mês/ano**, inclusivos. Mostrar também
os limites disponíveis na fonte. Não permitir intervalos invertidos, vazios
ou fora do histórico disponível.

Para NEWAVE, quando houver um único período consistente em
`parpvaz_history_periods`, usá-lo para preencher a proposta inicial. Exemplo
já conferido: `[[1931, 2024]]`. Os limites efetivos também devem respeitar os
meses existentes no arquivo histórico.

Não presumir sempre 2024, sempre um ano a menos ou uma regra baseada apenas
no primeiro ano sintético. Se os metadados faltarem ou forem ambíguos,
solicitar o preenchimento explícito dos campos existentes na janela.

Para o novo modelo, consultar metadados confiáveis disponíveis no caso.
Quando não houver registro conclusivo do período de ajuste, mostrar o
intervalo disponível como proposta, identificado como **período disponível,
a conferir com o ajuste**. O tamanho do arquivo histórico, sozinho, não
comprova quais anos foram usados para estimar o modelo. A janela deverá
deixar visível a origem da proposta e permitir a correção antes da geração.

Gravar no relatório o período escolhido, sua origem e os limites efetivamente
encontrados por usina. Se o usuário editar a proposta, identificar o período
como definido pelo usuário. Não dizer que foi detectado automaticamente.

### 5.3. Aplicação do recorte

O histórico de referência de cada modelo deverá ser recortado **antes** de:

- agrupar os meses para Welch, Levene e KS;
- calcular médias e desvios históricos dos gráficos;
- preparar os boxplots mensais;
- calcular correlações históricas mensais e anuais;
- calcular as 12 MLTs da análise de sequências;
- formar as janelas históricas e seus resumos;
- calcular P50 e P90 históricos.

Não reutilizar entre os modelos um resultado histórico calculado com outro
recorte. Cache e identificação dos resultados devem incluir esse período.

Os parâmetros de ajuste armazenados nos Parquets não substituem os valores
das amostras históricas utilizados nesses testes.

### 5.4. Conveniência da janela

Reaproveitar o estilo do comparador: janela clara, campos de caminhos,
botões Selecionar, resumo das entradas e progresso em linguagem simples.
Lembrar os últimos caminhos e períodos, mas reconferi-los contra os novos
arquivos selecionados. Nunca aplicar um período antigo fora da nova fonte.

A geração deverá rodar sem congelar a janela. Prevenir geração duplicada
durante um processamento. Não pedir autorizações adicionais para operações
de leitura e geração já solicitadas.

## 6. Correspondências e validação das fontes

### 6.1. Mesmas usinas e mesmas datas em Comparação

Validar antes de gerar o relatório:

- igualdade do conjunto de meses/anos sintéticos, incluindo limites mensais;
- igualdade do conjunto de usinas, associado por nome único normalizado;
- correspondência com o cadastro e o histórico do deck;
- ausência de ambiguidades e de identificações duplicadas.

Diferenças de usinas ou de horizonte entre os modelos devem **interromper a
geração**, com mensagem identificando os itens incompatíveis. Não usar apenas
a interseção, não completar ausências com zero e não cortar um dos modelos
automaticamente para fazê-los coincidir.

Não presumir igualdade de `hydro_id`, `stage_id` ou ordem das linhas entre
as fontes. Usar os mapas NEWAVE quando presentes. Nomes normalizados e
aliases explícitos podem ser usados; aproximações por semelhança não.

O calendário comum de apresentação será cronológico e trará mês/ano. IDs
originais podem continuar nos memoriais, devidamente identificados por fonte.

### 6.2. Parquets e dimensões

Aceitar os formatos já suportados pelo avaliador, com as colunas mínimas de
cenário, estágio, nó, usina e vazão incremental. Não exigir parâmetros AR
para executar os testes de vazões.

Preservar a regra NEWAVE: `node_id` pode ser nulo quando seus metadados
declararem que esse campo não está disponível. Não inventar um nó COBRE.

Não fixar 2000 cenários, 72 estágios, seis anos ou 159 usinas. Esses números
são características do estudo usado na validação, não limites do programa.
O pareamento de cenários ocorre **dentro de cada modelo**, não entre os dois.

### 6.3. Falhas estruturais e resultados indisponíveis

Falhas de estrutura, fonte, correspondência, datas ou chaves obrigatórias
devem ser comunicadas e impedir a publicação de um relatório aparentemente
completo. Preservar as validações atuais de duplicatas e esquema.

Casos estatísticos sem solução válida devem conservar o comportamento do
núcleo atual: resultado não calculado, com motivo e contagem. Não converter
ausência, constante, não finito ou erro numérico em aprovação ou p-valor zero.
Não uniformizar tratamentos diferentes entre testes sem justificar e validar.

Mensagens sobre vazão constante ou nula só devem ser usadas quando esse for
realmente o diagnóstico. Outras causas precisam de descrição própria.

## 7. Contrato estatístico preservado

### 7.1. Regras comuns

- Significância `alfa = 0,05` fixa.
- Reprovar quando `p < 0,05`; não reprovar quando `p >= 0,05`.
- Não aplicar correções, novos testes, normalizações ou estimadores para
  aproximar modelos ou mudar o resultado da validação anterior.
- Os três primeiros testes são independentes por UHE e estágio.
- Comparar o conjunto sintético de um estágio com os anos históricos do
  **mesmo mês**, dentro do período de referência daquele modelo.
- Não realizar um teste aglutinando estágios ou usinas.
- Preservar zeros, repetições e valores finitos negativos quando aceitos
  pela função original; não truncar vazões ou retirar outliers.
- Números não arredondados alimentam decisões e ordenação; formatação é visual.

### 7.2. Teste de médias — Welch bilateral

Manter médias, variâncias amostrais, erro padrão da diferença, estatística t,
graus de liberdade de Welch–Satterthwaite e p-valor bilateral do código validado:

```text
E² = s_s²/n_s + s_h²/n_h
t = (media_s - media_h) / raiz(E²)
gl = (s_s²/n_s + s_h²/n_h)² /
     [(s_s²/n_s)²/(n_s-1) + (s_h²/n_h)²/(n_h-1)]
p = 2 * stats.t.sf(abs(t), gl)
```

Os símbolos `s_s²` e `s_h²` já representam variâncias. Não acrescentar outro
quadrado ao calcular o erro padrão. Manter o critério atual dos desvios
usados nos gráficos, sem trocar silenciosamente estimadores de apresentação.

### 7.3. Teste de variâncias — Levene original

Usar centro na **média**, conforme o código atual, não a variante com mediana.
Para cada observação, calcular o desvio absoluto em relação à média do seu
grupo; depois, a ANOVA desses desvios, os dois graus de liberdade e a cauda
superior da distribuição F.

Preservar os memoriais: médias dos grupos; médias dos desvios; média geral;
somas de quadrados entre e dentro; quadrados médios; estatística W; graus
de liberdade; p-valor; decisão e motivo de não cálculo.

### 7.4. Teste de distribuição — KS bilateral de duas amostras

Preservar a variante já validada:

```text
D = max_x abs(F_s(x) - F_h(x))
n_efetivo = n_s * n_h / (n_s + n_h)
Z = D * raiz(n_efetivo)
p = stats.kstwobign.sf(Z)
```

Não substituir esse p-valor por `ks_2samp` exato, outro algoritmo assintótico
ou teste de normalidade. Empates continuam nas amostras; cada distribuição
empírica usa seu próprio denominador.

### 7.5. Correlação espacial mensal por estágio

Preservar Pearson de lag zero:

- sintético: pares de UHEs no mesmo estágio, pareados pelo mesmo cenário;
- histórico: pares de UHEs no mesmo mês, pareados pelo mesmo ano histórico.

O gráfico de correlação média por bacia é a média aritmética assinada das
correlações individuais da UHE selecionada com as UHEs da bacia.
**Excluir a própria UHE antes da média**, inclusive em sua bacia.
Zero entra na média; coeficientes indefinidos não entram. Informar contagens.

Essa média de coeficientes não é a correlação entre vazões somadas de bacias.

### 7.6. Correlação anual entre bacias

Para cada mês e cenário, somar as vazões incrementais das UHEs de cada bacia.
Exigir a composição completa, sem somar uma bacia parcialmente quando
faltarem valores. Usar o cadastro ONS interno com subdivisões, uma bacia por UHE.

Para cada ano civil completo, calcular a média aritmética dos 12 totais
mensais. Para cada cenário, correlacionar essas médias anuais entre duas
bacias, pareando os mesmos anos. Cada cenário gera um coeficiente por par.

No histórico de cada modelo, repetir a agregação das mesmas UHEs e calcular
uma correlação usando os anos completos comuns ao par dentro de seu recorte.
O histórico produz um coeficiente por par, não uma distribuição de 90 janelas.

Nas tabelas resumidas, calcular Q1, Q2 e Q3 sobre os coeficientes sintéticos
válidos, com interpolação linear explicitada. Q2 é a mediana. Informar a
quantidade de cenários válidos/indisponíveis e de anos históricos pareados.

Usar anos completos, quantidade dinâmica de anos e ao menos dois pares
anuais válidos. Séries constantes ou numericamente instáveis ficam sem r.
Não substituir correlação indefinida por zero. Excluir autocorrelações e
duplicatas simétricas nas tabelas de pares de bacias.

Essa análise é descritiva. A agregação anual é a interpretação adotada no
projeto; não atribuí-la como procedimento comprovado do artigo de 1982.

### 7.7. Sequências negativas e intensidade

Calcular as 12 MLTs com todo o histórico **recortado para aquele modelo**.
Uma sequência reúne meses consecutivos com vazão estritamente abaixo da
MLT do mês. Igualdade encerra o evento. Eventos atravessam a mudança de ano.

Manter o tratamento das extremidades como um ponto virtual acima da MLT,
sem alterar observações nem acrescentar meses ao comprimento.

Para cada evento j:

```text
C_j = quantidade de meses do evento
S_j = soma(Q_t - MLT_mes(t)) dentro do evento
I_j = S_j / C_j
```

Soma e comprimento usados na intensidade pertencem **ao mesmo evento**.
Calcular todas as intensidades e só então selecionar a mais severa.

O maior comprimento, o maior módulo da soma e o maior módulo da intensidade
de uma trajetória podem pertencer a três sequências diferentes.
Não dividir a maior soma pelo maior comprimento escolhidos separadamente.
Não substituir máxima intensidade por intensidade da sequência de maior soma.

As médias por trajetória são médias aritméticas dos eventos, incluindo
intensidade sem ponderação pelo comprimento. Uma trajetória válida sem
eventos recebe zero em todos os resumos; não recebe um evento artificial.

### 7.8. Janelas históricas anuais sobrepostas

Preservar a regra atual, individualmente para o histórico de cada modelo:

1. Mesmo mês inicial e mesma duração mensal do horizonte sintético.
2. Para os estudos encerrados em dezembro, ancorar no dezembro mais recente
   disponível, sem ultrapassar o recorte histórico.
3. Deslocar início e fim **12 meses para trás** para cada nova janela.
4. Manter somente janelas completas dentro dos limites históricos.
5. Meses ausentes dentro de uma janela invalidam essa janela, sem mudar
   os limites ou preenchê-la com zeros.

Exemplos com histórico até dezembro/2025:

| Horizonte sintético | Primeira janela | Segunda janela |
| --- | --- | --- |
| Janeiro/2026–dezembro/2031, 72 meses | Janeiro/2020–dezembro/2025 | Janeiro/2019–dezembro/2024 |
| Agosto/2026–dezembro/2031, 65 meses | Agosto/2020–dezembro/2025 | Agosto/2019–dezembro/2024 |

Não fixar a duração em seis anos. Manter a atenção ao mês inicial.
Calcular meses não utilizados pela **união** das janelas, sem contar os
meses compartilhados duas vezes. Informar passo e sobreposição no memorial.

As janelas não são independentes. Essa dependência não autoriza p-valores
de novos testes sobre os resumos; P50/P90 permanecem descritivos.

### 7.9. P90 e P50 gerais de sequências

Para cada UHE e fonte, calcular os dois percentis dos seguintes valores por
trajetória: maior comprimento; maior módulo da soma; maior módulo da intensidade.
Usar somente trajetórias calculadas e números finitos, preservando zeros.

Usar `np.quantile(..., method="linear")`, sem arredondar antes de comparar.
Não misturar eventos individuais com os resumos por trajetória.

Para cada percentil e medida:

```text
percentual = 100 * usinas(percentil_sintético > percentil_histórico)
                    / usinas_comparáveis
```

Usina comparável: ao menos um valor válido em cada fonte, naquela medida.
P90/P50 histórico zero é válido: não há divisão por esse número.
Igualdade entra no denominador, não no numerador. Sem comparáveis, mostrar
indisponível, nunca 0% artificial. Cada UHE tem um voto, independentemente
do número de trajetórias válidas.

Esses percentuais contam **usinas**, não cenários. Não equivalem à proporção
de cenários que superam a pior sequência de todo o histórico da referência.

## 8. Visão geral do SIN — indicadores nas respectivas análises

**Atualização v1.1:** não existe uma aba separada de resumo. Os conteúdos abaixo
ficam no início da respectiva aba, antes dos memoriais. A correlação espacial
inclui o gráfico anual entre bacias; as demais análises gerais usam tabelas.

### 8.1. Médias, variâncias e distribuição

Cada seção terá um filtro deslizante próprio de estágios, imediatamente
antes dos resultados. O filtro será compartilhado pelos dois modelos,
alinhado pelo mesmo mês/ano. Mostrar também mês/ano nos extremos, além da
posição de estágio, para não depender dos IDs originais.

Ordem de apresentação, por seção:

1. Seis indicadores do novo modelo e depois os seis do NEWAVE.
2. Tabela **Resumo do teste por estágio** do novo modelo e depois do NEWAVE.
3. **Ranking de usinas por estágios reprovados** do novo modelo e depois do NEWAVE.
4. Diagnósticos e contagens de resultados indisponíveis por modelo.

Em Análise, mostrar somente os blocos do modelo escolhido.

Os seis indicadores, sempre nesta ordem:

| Ordem | Indicador | Denominador/regra |
| --- | --- | --- |
| 1 | Combinações calculadas | UHE–estágio com teste calculado e p válido. |
| 2 | Combinações reprovadas | Entre as calculadas, p < 0,05. |
| 3 | Combinações aprovadas (%) | Calculadas não reprovadas / calculadas. |
| 4 | Total de usinas no teste | UHEs com ao menos uma combinação calculada no intervalo. |
| 5 | Usinas reprovadas em ao menos um estágio | UHEs com uma ou mais reprovações no intervalo. |
| 6 | Usinas completamente aprovadas (%) | UHEs com todos os estágios selecionados calculados e nenhum reprovado / total de usinas no teste. |

Uma UHE com estágio não calculado não pode ser considerada completamente
aprovada só porque não apresentou reprovação. Nenhum denominador nulo deve
produzir porcentagem artificial.

A tabela por estágio mostrará identificação temporal, combinações testadas,
reprovações e percentual de reprovações, conservando as contagens auditáveis.
O ranking mostrará posição, usina, estágios reprovados, calculados e não
calculados. Ordenar por reprovações decrescentes, preservar empates na mesma
posição e usar nome como desempate de apresentação. Não contar falha de
cálculo como reprovação. Preservar os IDs nos memoriais de identificação.

### 8.2. Correlação espacial no resumo

Mostrar **somente a correlação anual entre bacias**, em tabela resumida.
Uma linha por par de bacias:

- bacia A e bacia B;
- correlação histórica;
- Q1, mediana/Q2 e Q3 dos coeficientes sintéticos;
- cenários válidos e indisponíveis;
- quantidade de anos sintéticos e anos históricos pareados;
- observação/motivo quando o coeficiente não estiver disponível.

Novo modelo primeiro, NEWAVE abaixo. Não mostrar boxplots ou gráficos
nessa visualização. Não acrescentar índices de aprovação para correlação.

### 8.3. Sequências no resumo

Manter os seis indicadores atuais:

- P90: maior comprimento, maior módulo da soma, maior módulo da intensidade;
- P50: as mesmas três medidas.

Intercalar por percentil: P90 novo modelo, P90 NEWAVE, P50 novo modelo,
P50 NEWAVE. Após cada conjunto, oferecer contagens e tabelas de conferência,
também intercaladas pelo mesmo conteúdo.

As tabelas por UHE conterão percentis das duas fontes, tamanhos das amostras,
unidade, resultado maior/igual/menor/sem comparação e motivo.
Sem seletor de estágios: os indicadores usam o horizonte completo.

## 9. Visão geral do SIN — cinco abas específicas

Todas serão **exclusivamente de indicadores e tabelas**, com memoriais de
cálculo para todas as usinas. Não repetir os gráficos individuais nessas abas.

### 9.1. Teste de médias

Tabela completa por UHE e estágio, reaproveitando os campos do resultado
atual: amostras; médias; desvios/variâncias; diferença; erro padrão; t;
graus de liberdade; p; alfa; decisão; status; motivo; identificação das fontes
e meses históricos utilizados.

### 9.2. Teste de variâncias

Tabela completa por UHE e estágio, com todos os escalares do Levene atual,
incluindo médias dos desvios absolutos, somas de quadrados, quadrados médios,
dois graus de liberdade, W, p e diagnóstico. Identificar centro na média.

### 9.3. Teste de distribuição

Tabela completa por UHE e estágio: N, tamanho efetivo, D, Z, p, vazão x* da
maior distância, contagens e acumuladas em x*, repetições, decisão e motivo.
Os pontos das distribuições empíricas devem continuar disponíveis no
memorial detalhado da UHE/estágio, carregado sob demanda no próprio HTML.

### 9.4. Correlação espacial

Conter o detalhamento da correlação anual entre bacias:

- quartis por par;
- coeficientes por cenário e par, com quantidade de anos e diagnóstico;
- médias anuais por bacia, ano e cenário;
- médias anuais históricas e anos efetivamente pareados;
- composição das bacias e UHEs não identificadas.

**Escolha complementar adotada:** incluir também, em seção recolhível,
o memorial mensal de lag zero UHE × UHE × estágio já existente no avaliador,
sem gráficos, para permitir auditar os dois visuais do modo por usina.
Esse memorial não entra no resumo inicial, que permanece somente anual.

O memorial mensal conterá contagens pareadas, médias, desvios, covariância,
r, status e motivo. Pares simétricos podem ser armazenados uma vez, mas a
consulta deve identificar corretamente referência e comparada, inclusive
as respectivas médias/desvios quando a orientação for invertida.

### 9.5. Análise de sequências

Disponibilizar os memoriais atuais completos:

- resumos de todas as trajetórias sintéticas e históricas;
- MLTs mensais e suas contagens;
- janelas históricas, sobreposição, status e motivos;
- intervalos fora da união das janelas;
- eventos individuais com início, fim, C, S, I e marcações das extremidades;
- diagnósticos de UHEs e trajetórias indisponíveis.

O memorial preservará S e I assinados. Quando houver colunas de módulo,
rotulá-las explicitamente, sem substituir os valores originais.

### 9.6. Filtros das tabelas gerais

Como escolha de implementação, fornecer busca por nome e filtros próprios
por aba. Nas três primeiras: intervalo de estágios e resultado/status.
Em correlação: bacia/par e estágio quando o memorial mensal estiver aberto.
Em sequências: nome, fonte, trajetória e status, sem encurtar o horizonte.

Esses filtros servem à consulta; não são um seletor geral de UHE do relatório
e não alteram os controles das outras abas. Filtros de um mesmo conteúdo
controlam simultaneamente as duas tabelas de modelos, sem misturar dados.

## 10. Resultado por Usina — filtros independentes

Cada aba terá seu próprio seletor pesquisável por **nome da usina**.
Não usar ID como busca principal, não exigir conhecer o código da UHE e
não transferir a seleção automaticamente para outra aba.

Em Comparação, a seleção dentro daquela aba será aplicada aos dois modelos.
Essa aplicação conjunta é uma escolha complementar para manter a comparação
visual da mesma UHE e do mesmo intervalo.

| Aba | Filtros |
| --- | --- |
| Teste de médias | Nome da UHE + intervalo deslizante de estágios. |
| Teste de variâncias | Nome da UHE + intervalo deslizante de estágios. |
| Teste de distribuição | Nome da UHE + intervalo deslizante de estágios + estágio específico para distribuição/KS. |
| Correlação espacial | Nome da UHE + estágio específico + bacia do detalhamento. |
| Análise de sequências | Nome da UHE + Máximo/Média + trajetória do memorial; sem intervalo de estágios. |

Nos três primeiros testes, o intervalo altera os gráficos e memoriais
visíveis, sem recalcular o teste: todos os estágios já estão no HTML.
No KS, o estágio específico deve pertencer ao intervalo escolhido.

Não mostrar nos detalhes individuais os blocos gerais que foram concentrados
nas respectivas abas da visão do SIN: contadores gerais, ranking e resumo de todas as UHEs.
Preservar os memoriais individuais correspondentes aos gráficos.

## 11. Resultado por Usina — gráficos e ordem

### 11.1. Regra de intercalação

Para cada tipo de gráfico, primeiro novo modelo × histórico, depois NEWAVE
× histórico, antes de avançar ao tipo seguinte. Não colocar todos os gráficos
de um modelo antes de todos os gráficos do outro.

Cada título identificará teste, UHE, modelo, período sintético e referência
histórica relevante. A diferença entre os períodos históricos deve estar
visível sem exigir consultar outra aba.

### 11.2. Teste de médias

1. Média por estágio em linha e desvio padrão como área sombreada.
2. **Boxplots das vazões incrementais por estágio**, substituindo o gráfico
   de diferença das médias e erro padrão.
3. Gráfico de p-valor por estágio, com barras verdes/vermelhas, alfa e
   percentual de testes aprovados fora da área dos dados.
4. Memorial da UHE no intervalo.

No boxplot, cada estágio terá a distribuição sintética e, ao lado, o
histórico do mês correspondente. Usar **todos os cenários válidos** e todos
os valores históricos daquele mês no recorte do modelo. Não retirar
outliers, zeros ou negativos finitos nem substituir as observações por médias.
Mostrar quartis, mediana, hastes e outliers, conforme o visual original.

Não incluir slack nesse gráfico. Preservar no memorial do Welch os campos
de diferença e erro padrão, embora seu antigo gráfico tenha sido retirado.

### 11.3. Teste de variâncias

1. Módulo dos desvios padrão histórico e sintético por estágio, em linhas.
2. Diferença dos desvios padrão, com a convenção de sinal atual identificada.
3. P-valor por estágio no mesmo padrão de aprovação do teste de médias.
4. Memorial Levene da UHE no intervalo.

### 11.4. Teste de distribuição

1. Curvas de distribuição de vazões no estágio escolhido, como no avaliador.
2. Curvas acumuladas do KS e marcação da distância D.
3. P-valor por estágio para o intervalo.
4. Memorial da UHE e pontos do KS do estágio escolhido.

A curva de densidade é uma visualização; o teste continua usando as amostras
e distribuições empíricas originais. Não calcular p a partir da curva suavizada.

### 11.5. Correlação espacial

Somente os dois gráficos mensais por estágio:

1. Média das correlações da UHE selecionada com as demais UHEs, por bacia.
2. Correlações individuais apenas com as UHEs da bacia escolhida.

Manter a exclusão da autocorrelação da UHE, o cadastro ONS com subdivisões,
as contagens de pares e os memoriais correspondentes.
Não acrescentar aqui o boxplot anual entre bacias: essa análise ficará
nas tabelas da visão geral, conforme a definição de navegação.

### 11.6. Análise de sequências

Manter quatro gráficos:

1. Quantidade de sequências negativas por trajetória.
2. Comprimento das sequências.
3. Módulo da soma dos déficits.
4. Módulo da intensidade dos déficits.

Cada gráfico mostrará o par de boxplots modelo/histórico, próximos e
centralizados, como no ajuste atual. Em Comparação, repetir esse par em
outro gráfico logo abaixo para o NEWAVE.

O seletor terá apenas **Máximo** e **Média**. Adotar Máximo como seleção
inicial, por estar alinhado aos indicadores gerais dos extremos. Quantidade
não muda com esse seletor. Para Máximo em soma/intensidade, usar o maior módulo.

Cada ponto da amostra do boxplot é um resumo de trajetória, não um evento
isolado. A linha interna é a mediana entre trajetórias, mesmo na opção Média.
Preservar todos os outliers e zeros válidos e as diferentes contagens por fonte.

Incluir memoriais individuais, MLTs, janelas e consulta de uma trajetória.
Não adicionar seletor de estágios nem controles que encurtem essas trajetórias.

## 12. Estilo visual, cores e tabelas

Reaproveitar o padrão do comparador: fundo claro, cartões brancos, bordas
discretas, títulos azuis, espaçamento consistente e tipografia do sistema.
Sem fontes ou folhas de estilo externas.

| Papel | Cor definida |
| --- | --- |
| Novo modelo | Ciano `#09B6CB`. |
| NEWAVE | Laranja queimado `#C56A1A`, escolha complementar para o tom solicitado. |
| Histórico | Preto `#000000`, com preenchimentos cinza translúcidos quando necessário. |
| Teste não reprovado | Verde `#16A34A`. |
| Teste reprovado | Vermelho `#DC2626`. |
| Não calculado/indisponível | Cinza, acompanhado de texto e motivo. |
| Linha de significância | Laranja forte `#FF8C00`, sólida e claramente identificada. |

As cores verde/vermelho dos p-valores indicam decisão, não identidade de
modelo. Usar título e cabeçalho de modelo para manter essa distinção.
Gráficos derivados sem duas séries deverão ter fonte e significado explícitos.

Em Comparação, usar escalas e eixos compatíveis entre os dois gráficos do
mesmo tipo, cobrindo os valores completos das duas fontes. Não esconder
outliers para fazer um modelo parecer mais próximo do histórico.

Nas tabelas:

- busca, paginação e ordenação numérica real por cabeçalho;
- 50 linhas por página por padrão, com opções 25, 50, 100 e 200;
- barras horizontais acima e abaixo, sincronizadas;
- cabeçalho fixo na rolagem vertical;
- uma identificação clara de modelo e período por tabela;
- vírgula decimal e **nenhum separador de milhar**;
- percentuais com duas casas e demais valores geralmente com seis;
- p-valores pequenos em notação científica, para não aparentarem zero por
  mero arredondamento; representação completa acessível na inspeção;
- ausências como `—`, nunca zero;
- mesma ordenação/filtro de consulta aplicado ao par de tabelas quando
  isso ajudar a localizar a mesma UHE/estágio, sem recalcular estatísticas.

Memoriais não podem perder campos de cálculo existentes apenas para caber
na tela. Organizar grupos de colunas ou usar rolagem, mantendo identificação,
unidade e status. Textos e nomes terão tratamento seguro, sem interpretar HTML.

## 13. HTML único, completo e viável no navegador

### 13.1. Contrato de consulta

O relatório deverá funcionar ao abrir o `.html` diretamente no navegador,
inclusive após movê-lo para outra pasta ou computador. Não depender de
Python, Streamlit, servidor local, CDN, fontes remotas ou arquivos auxiliares.

JavaScript embutido poderá alternar abas, filtrar, ordenar e desenhar os
gráficos. Todos os cálculos estatísticos serão feitos antes, no Python.
O navegador poderá recalcular apenas contagens e resumos de apresentação
do intervalo visível, com os resultados já incorporados.

Não incluir botões de baixar Excel/CSV. O único produto de consulta será
o HTML. Desabilitar controles de gráficos que sugiram exportações não previstas.

### 13.2. Estratégia para o volume

Um relatório com todos os memoriais terá muito mais dados que o comparador
de parâmetros. Não prometer um tamanho pequeno nem retirar dados para
reduzir o arquivo. Medir tamanho, tempo e memória com o caso real.

Adotar as seguintes medidas de implementação:

1. Carregar as tabelas iniciais de resumo em um bloco pequeno.
2. Incorporar os dados pesados em blocos compactados e identificados por
   modelo, análise, UHE/estágio ou par de bacias.
3. Manter o descompactador e as bibliotecas necessários dentro do próprio
   HTML, com suas licenças. Não buscar recursos pela rede.
4. Descompactar e montar apenas os blocos solicitados pelo usuário.
5. Paginar/virtualizar linhas: nunca criar milhões de elementos de tabela.
6. Usar índices numéricos e dicionários para nomes/datas repetidos, mantendo
   números de cálculo em precisão equivalente à original.
7. Compartilhar no arquivo dados idênticos de referência, mas nunca
   confundir referências históricas com recortes diferentes.
8. Gerenciar um cache limitado de dados e gráficos abertos; destruir os
   gráficos desativados quando necessário para liberar memória.
9. Usar processamento fora da atualização principal da página quando o
   volume exigir, com mensagens de carregamento e sem travar a navegação.

O carregamento sob demanda será **dentro do arquivo**, não uma requisição
a arquivos do computador. A publicação precisa ser testada no protocolo
`file://`, não apenas em um servidor de desenvolvimento.

### 13.3. Gráficos sem duplicar desnecessariamente as entradas

Não incorporar duas cópias dos Parquets completos como JSON de objetos.
Reutilizar representações de resultados e amostras já organizadas.

Para boxplots, pode-se incorporar estatísticas pré-calculadas e todos os
outliers visíveis em vez de repetir todos os pontos internos. Isso somente
será aceito após comprovar que quartis, mediana, hastes e outliers coincidem
com o Plotly usado no programa de referência, considerando **todos os dados**.
Não presumir que implementações diferentes de quartis são idênticas.

Os pontos exatos necessários para distribuições empíricas, inspeções de KS
e memoriais devem continuar disponíveis. Simplificação visual não poderá
alterar D, Z, p ou ocultar um campo de cálculo prometido.

O detalhe mensal de trajetórias não exige guardar a mesma observação em
dezenas de janelas: incorporar referências a séries de origem compartilhadas
e reconstruir a consulta mensal no HTML, sem precisar reler o Parquet.

### 13.4. Memoriais completos e definição de completude

Completo significa permitir consultar todas as linhas dos resultados e
memoriais especificados, mesmo que não estejam todas no DOM simultaneamente.
Não significa duplicar cada observação bruta em todas as tabelas ou mostrar
todos os números ao mesmo tempo.

Se uma escolha de compactação ou gráfico não conseguir preservar essa
completude, ajustar a estratégia antes de considerar a entrega concluída.
Não migrar silenciosamente para relatórios externos ou arquivos auxiliares.

## 14. Geração, nomes e rastreabilidade

### 14.1. Nomes obrigatórios

```text
analise_novo_modelo_AAAAMMDD_HHMMSS.html
analise_newave_AAAAMMDD_HHMMSS.html
comparacao_novo_modelo_newave_AAAAMMDD_HHMMSS.html
```

Usar data e hora de Brasília, obtidas no momento da gravação. Se já existir
um nome, acrescentar um sufixo único sem apagar o relatório anterior.
Gravar por padrão em `relatorios/` do novo projeto.

### 14.2. Conteúdo de identificação

O HTML deverá registrar:

- modo de geração e modelos presentes;
- instante de geração e fuso;
- versões dos cálculos, do programa e do cadastro de bacias;
- nomes das fontes, tamanho e identificação de integridade;
- pasta do deck e arquivos efetivamente localizados;
- horizonte sintético, número de UHEs e cenários por modelo;
- histórico disponível, período selecionado e origem dessa seleção;
- métodos estatísticos e significância fixa de 5%;
- contagens e motivos de resultados não calculados;
- confirmação de que a referência de cada modelo é o histórico correspondente.

As informações mais extensas podem ficar em seção recolhível de metodologia
e fontes, sem acrescentar uma sétima aba nem misturar dados técnicos à consulta.

### 14.3. Publicação do arquivo

Validar fontes antes do cálculo; verificar se mudaram durante o processamento.
Construir o HTML em arquivo temporário próprio e publicá-lo atomicamente
apenas após concluir cálculos, validação do conteúdo e gravação.

Em caso de falha, apresentar mensagem clara e preservar relatórios anteriores.
Arquivos de origem são somente lidos. Metadados e nomes incorporados ao HTML
devem ser escapados; não permitir encerrar tags ou executar conteúdo dos insumos.

## 15. Projeto independente e reaproveitamento dos geradores

Estrutura planejada, ainda não criada nesta entrega além de `documentacao/`:

```text
AVALIADOR_VAZOES_HTML/
  GERAR_RELATORIO_HTML.bat
  GERAR_PARQUET_NOVO_MODELO.bat
  GERAR_PARQUET_NEWAVE.bat
  requirements.txt
  aplicacao/         # Janela, orquestração e execução por linha de comando
  calculos/          # Núcleos matemáticos e organizadores locais
  dados/             # Validadores, metadados, correspondências e bacias ONS
  geradores/         # Cópias independentes dos dois geradores atuais
  infraestrutura/   # Dependências, caminhos, versões e utilidades
  relatorio/         # Preparação de tabelas, gráficos, índices e arquivo final
  recursos/          # Template, CSS, JavaScript e bibliotecas locais/licenças
  documentacao/      # Este plano e manual de uso
  testes/            # Regressão numérica, integração e navegador
  relatorios/        # HTMLs finais, um arquivo por execução
  outputs/           # Verificações, logs e evidências de desenvolvimento
  parquet gerado novo modelo/
  parquet gerado newave/
  .python_packages/  # Dependências locais, quando necessárias
```

Todos os `.py` deverão permanecer organizados em pastas. Não copiar entradas
gigantes nem bibliotecas instaladas apenas para criar o novo projeto.

Os geradores serão cópias locais, com saídas apontando para as duas pastas
do novo projeto. Preservar o esquema, valores, validações, metadados,
correspondências NEWAVE e integração com PARPVAZ. Corrigir apenas caminhos
e referências necessárias à independência. Não alterar os geradores originais.

O avaliador HTML não deve importar módulos do projeto antigo em produção.
Extrair as dependências matemáticas da interface Streamlit nas cópias locais
quando necessário, comprovando paridade. O novo programa usará Tkinter para
a janela e não precisará manter um servidor Streamlit aberto.

Oferecer também uma entrada por linha de comando para reproduzir gerações e
executar auditorias. A significância continuará fixa, inclusive nessa entrada.

## 16. Plano de execução por etapas

### Etapa A — Congelar a referência

- Registrar versões e assinaturas dos módulos reaproveitados.
- Separar cópias locais de cálculos, dados e geradores.
- Portar os casos de validação pertinentes, mantendo referências numéricas.
- Comprovar que os módulos carregados pertencem ao novo projeto.

### Etapa B — Entradas e recortes

- Implementar janela, modos, seleção da pasta e Parquets.
- Validar os conjuntos de UHEs e mês/ano.
- Resolver períodos históricos, origem da proposta e edição.
- Criar o modelo interno de fontes por modelo e sua rastreabilidade.

### Etapa C — Cálculos completos

- Calcular os três testes para todas as combinações.
- Calcular correlações mensais e anuais, sem duplicar pares simétricos.
- Calcular sequências, janelas, eventos e P50/P90.
- Preparar dados dos gráficos e memoriais, com diagnósticos preservados.

### Etapa D — Prova de volume antes do acabamento

- Serializar o conteúdo real dos dois modelos com todos os memoriais.
- Medir tamanho do HTML, tempo para abrir, memória e latência de consulta.
- Validar carregamento parcial, paginação e recuperação de memória.
- Otimizar estrutura/compactação sem amostrar ou retirar dados.

### Etapa E — Visão geral

- Reunir indicadores e detalhamento em cada uma das cinco abas gerais.
- Incluir os boxplots anuais na correlação geral; nas outras abas gerais, manter tabelas.
- Verificar intercalação por conteúdo e contagens após filtros.

### Etapa F — Resultado por Usina

- Construir seletores independentes em cada aba.
- Reproduzir os gráficos definidos, cores e intercalação.
- Incluir o boxplot de vazões no teste de médias.
- Limitar sequências a Máximo/Média e ao horizonte completo.

### Etapa G — Publicação e verificação final

- Incorporar todos os recursos e testar consulta sem rede/servidor.
- Validar a janela, os três modos de geração e nomes de saída.
- Gerar arquivos reais, conferir resultados e documentar o uso.

## 17. Verificações e critérios de aceite

### 17.1. Fontes e recortes

- Análise com cada modelo e Comparação com ambos.
- IDs diferentes, nomes normalizados únicos e datas iguais.
- Bloqueio de UHE exclusiva, mês exclusivo, ambiguidade e esquema inválido.
- Histórico NEWAVE identificado por metadados e período editado pelo usuário.
- Referências com início fora de janeiro e fim anterior ao da fonte completa.
- Nenhuma alteração de arquivo de entrada ou projeto original.

### 17.2. Paridade numérica

- Comparar com as funções atuais usando as mesmas entradas e o mesmo recorte.
- Preservar Welch, Levene com média e KS limite bilateral.
- Conferir p exatamente no limiar e percentuais com denominador zero.
- Conferir seis contadores, completude de aprovação e ranking com empates.
- Verificar exclusão da autocorrelação antes da média por bacia.
- Conferir correlação anual com agregação prévia das vazões e histórico próprio.
- Conferir eventos com duração e soma da mesma sequência na intensidade.
- Verificar janelas de 72 e 65 meses, passo de 12, bordas, sobreposições,
  lacunas e reconciliação pela união.
- Conferir P50/P90, módulos, zeros, igualdade e exclusões por medida.
- Usar resultados conhecidos do SciPy/R quando o método for correspondente,
  sem substituir o método original por outro apenas para obter coincidência.

### 17.3. Navegação e filtros

- Cinco abas gerais com resumos e memoriais; correlação com boxplots anuais. Cinco abas por UHE.
- Ausência de seletor geral de UHE.
- Buscar pelo nome em cada aba, sem interferir nas outras.
- Em Comparação, mesmo filtro no par de modelos e ordem novo modelo/NEWAVE.
- Testar intervalo parcial, mudanças de etapa, filtro sem resultados e limpeza.
- Confirmar que filtro de consulta não muda dados nem fórmulas.
- Confirmar que sequências não oferecem estágio nem Mínimo.
- Confirmar que o boxplot substituiu o antigo gráfico de diferenças no Welch.

### 17.4. Apresentação e consulta integral

- Quartis, hastes e outliers dos boxplots iguais à referência visual validada.
- Cores corretas e histórico preto legível em todos os gráficos.
- P-valores com verde/vermelho e alfa sólido, sem indicador sobre os dados.
- Tabelas ordenadas numericamente, com vírgula e sem milhar.
- Rolagens superior/inferior sincronizadas após filtros e paginação.
- Conferir totais de linhas, primeira/última página e uma amostra distribuída
  de linhas de todos os memoriais contra as tabelas calculadas no Python.
- Confirmar que nenhum dado de outro modelo/histórico aparece por erro de cache.
- Abrir o HTML movido de pasta e com a rede desativada; sem recursos externos.
- Testar nomes com caracteres especiais e inexistência de exportações externas.

### 17.5. Volume e evidências

Usar o caso real, além de exemplos pequenos: aproximadamente 159 UHEs,
72 meses e 2000 cenários por modelo, sem transformar esses números em limites.
Registrar tamanho do arquivo, memória máxima observada, tempo de geração,
primeira abertura e consultas pesadas.

Metas iniciais de engenharia: primeira visão utilizável em até 10 segundos
no ambiente de referência, alternância de conteúdo já carregado em até
2 segundos e indicação de progresso para consultas mais demoradas.
Essas metas precisam ser medidas, sem prometer tamanho ou velocidade antes
do protótipo. Falhas de desempenho exigem otimização, não retirada de memoriais.

Salvar evidências e resultados em `outputs/verificacao/`, sem substituir os
relatórios anteriores. A entrega não estará concluída apenas porque existe
um HTML: cálculos, completude, navegação e consulta offline precisam passar.

## 18. Escolhas complementares assumidas neste plano

Conforme autorização para presumir os pontos restantes:

| Escolha | Definição adotada |
| --- | --- |
| Nome da pasta | `AVALIADOR_VAZOES_HTML`. |
| Visualização inicial | Visão geral do SIN, Teste de médias, horizonte completo. |
| Seleção inicial individual | Nenhuma UHE escolhida até selecionar pelo nome naquela aba. |
| Filtros entre modelos | Compartilhados somente dentro do mesmo conteúdo/aba. |
| Filtros entre abas | Independentes, preservados durante a navegação. |
| KS individual | Estágio específico dentro do intervalo selecionado. |
| Sequências individual | Máximo inicialmente, com Média disponível. |
| Detalhe SIN de correlação | Boxplots anuais entre bacias, quartis e memoriais anuais; memorial mensal recolhível. |
| NEWAVE | Tom inicial `#C56A1A`. |
| Datas e IDs | Pareamento por mês/ano e nome; IDs originais preservados nos memoriais. |
| Quantidade de cenários | Identificada por modelo; não presumir igualdade de IDs entre modelos. |
| Saída | Pasta `relatorios/`, abertura automática após sucesso, sem sobrescrever. |
| Recursos gráficos | Plotly local incorporado uma vez, sem CDN. |
| Memoriais grandes | Compactação interna, índices, paginação e carregamento sob demanda. |
| Produto entregue ao leitor | Apenas o HTML final; temporários e evidências ficam no ambiente de geração. |

Essas escolhas fecham o mapeamento sem novas perguntas. A implementação
deverá seguir este documento e registrar qualquer impossibilidade concreta,
sem alterar silenciosamente uma decisão funcional ou estatística.

## 19. Fora do escopo

- Testes estatísticos entre novo modelo e NEWAVE.
- Diferenças/tolerâncias de parâmetros PARP como no comparador anterior.
- Novos testes, correções de p-valor ou classificação de vencedor entre modelos.
- Outros gráficos na visão geral do SIN além dos boxplots anuais entre bacias.
- Downloads Excel/CSV, relatórios auxiliares obrigatórios ou servidor de consulta.
- Alterar os programas anteriores ou os arquivos de origem.
- Incluir usinas/datas incompatíveis por interseção silenciosa.
- Trocar intensidade máxima por intensidade associada à maior soma.
- Reduzir o número de cenários, eventos ou linhas para aparentar melhor desempenho.

## 20. Registro da implementação inicial (v1.0)

Foram implementados os dois modos de geração, as seis abas gerais sem gráficos,
as cinco abas por usina com seleções independentes, os filtros e todos os
memoriais. Os históricos são recortados separadamente antes das contas.
Os geradores reaproveitados são cópias locais; os projetos anteriores permanecem
preservados. O manifesto de reaproveitamento registra os arquivos e seus hashes.

As hipóteses, estatísticas, p-valores e percentis de avaliação são calculados em
Python. Na consulta, JavaScript avalia as curvas de densidade e os pontos das
empíricas a partir de **todas** as amostras incorporadas, usando os parâmetros
de suavização definidos em Python. Isso é a construção do desenho; o D, Z,
p-valor e a decisão vêm do cálculo Python. A distância desenhada foi conferida
contra o D original. O Plotly monta os boxplots das amostras completas com
quartis lineares. Os indicadores P50/P90 de avaliação já vêm calculados.
Este detalhamento explicita o limite entre cálculo da avaliação e apresentação
previsto na seção 13.1.

Para o volume real, as amostras, matrizes de correlação e cada tipo de memorial
de sequências são guardados em blocos separados, compactados e incorporados ao
mesmo HTML. Uma consulta de resumos não precisa descompactar os eventos nem as
vazões dos gráficos. As tabelas gerais de sequências usam índices de linhas;
apenas a página visível é convertida em elementos da tabela. A busca e a
ordenação consultam todo o conteúdo, com progresso, sem reduzir observações.

A geração histórica de sequências foi vetorizada em lote, mantendo o mesmo
núcleo matemático e reposicionando as datas de cada janela. Sua equivalência
com a rotina anterior foi verificada nos testes e no caso real de Camargos.
Uma leitura de resultado agregado do DuckDB passou a consumir o resultado
inteiro antes de registrar outra tabela, para compatibilidade com a versão
instalada. Nenhuma fórmula estatística foi alterada por essas adaptações.

O caso real tem 159 usinas, 72 estágios e 2000 cenários em cada modelo. O HTML
completo contém aproximadamente 763 MB e abriu a primeira visão em 4,873 segundos
na máquina de verificação. Os resultados numéricos, testes offline, tamanhos,
memória observada e capturas estão registrados no documento de verificação.


## 21. Atualização aprovada — v1.1

A aba Resultados gerais foi removida. A visão do SIN passa a ter cinco abas:

- Médias, variâncias e distribuição: intervalo de estágios; seis indicadores de
  cada modelo; resumos por estágio; ranking; filtros e memoriais completos.
- Correlação espacial: seletor de bacia de referência, boxplots das correlações
  anuais entre bacias e ponto histórico, seguido dos quartis e memoriais.
- Sequências: P90/P50 e suas contagens, seguido dos memoriais existentes.

Cada tipo de conteúdo continua intercalando novo modelo e NEWAVE. O intervalo
atua sobre todos os resultados do teste; a busca de usina e o filtro de decisão
na seção do memorial ficam explicitamente limitados a essa seção.

O gráfico anual usa os coeficientes já calculados, um por cenário/par de bacias.
Trocar a bacia de referência também permite visualizar o par na ordem inversa,
usando a simetria de Pearson, sem alterar seu valor. O histórico é um ponto preto.
Anos incompletos e correlações indefinidas continuam identificados, sem conversão
para zero. A visão por usina mantém as análises mensais já existentes.

Essa atualização substitui a organização inicial de seis abas e a restrição de
nenhum gráfico na visão geral. Os demais critérios estatísticos permanecem válidos.
