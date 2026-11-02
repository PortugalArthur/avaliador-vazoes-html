# Verificação do avaliador HTML

Verificação realizada em 02/11/2026, em Windows, com Python 3.12 e Chrome.
As evidências numéricas abaixo são da implementação inicial. A atualização
de organização e gráficos da versão 1.1 está registrada ao fim deste documento.
Os arquivos de estudo foram somente lidos. Os projetos anteriores foram preservados.
Os 38 testes automatizados passaram, sem falhas ou testes ignorados.

## Entrega funcional

O projeto oferece Análise de um modelo e Comparação com dois modelos, sempre
modelo × histórico. Foram verificadas a janela de seleção, a geração com cada
um dos três conjuntos de entradas e a recusa de sobrescrever relatórios existentes.

A correspondência entre modelos usa nome da usina e mês/ano. O caso pequeno de
teste possui IDs de usinas e estágios deliberadamente diferentes, horizonte
iniciado em agosto e históricos com finais diferentes. Foram verificados o
pareamento correto e o bloqueio de conjuntos de usinas, calendários, origens,
chaves duplicadas e períodos históricos incompatíveis.

O caso artificial está identificado como fixture em `outputs/verificacao/`.
Ele não substitui os dados reais nem foi usado para ajustar os resultados do estudo.

## Caso real

Entradas:

- Deck: `C:\Users\Pichau\Desktop\Series_sinsteticas\DECK_COBRE`.
- Novo modelo: `TESTES_ESTATISTICOS_COBRE\parquet gerado novo modelo\inflows_with_lags_000.parquet`.
- NEWAVE: `TESTES_ESTATISTICOS_COBRE\parquet gerado newave\inflows_newave_000.parquet`.

Os caminhos completos, tamanhos e hashes SHA-256 das fontes constam no próprio
HTML, na seção de metodologia e fontes.

| Item | Novo modelo | NEWAVE |
| --- | ---: | ---: |
| Usinas | 159 | 159 |
| Estágios | 72 | 72 |
| Horizonte sintético | jan/2026 a dez/2031 | jan/2026 a dez/2031 |
| Cenários | 2000 | 2000 |
| Histórico utilizado | jan/1931 a dez/2025 | jan/1931 a dez/2024 |
| Combinações por teste, incluindo não calculadas | 11448 | 11448 |
| Trajetórias sintéticas e históricas nos memoriais | 332310 | 332151 |
| Janelas históricas por UHE com histórico completo | 90 | 89 |
| Eventos de sequências, sintéticos e históricos | 3327796 | 3016708 |

O período NEWAVE foi obtido dos metadados PARPVAZ. Para o novo modelo foi usado
o histórico disponível no deck. Isso registra o recorte da avaliação; não constitui
uma inferência nova sobre o período usado internamente pelo ajuste do modelo.

## Evidências numéricas

- Em 100 pares de amostras de tamanhos 95 e 2000, Welch coincidiu com
  `scipy.stats.ttest_ind(equal_var=False)` e Levene coincidiu com
  `scipy.stats.levene(center='mean')`, dentro da tolerância numérica dos testes.
- A estatística D coincidiu com `scipy.stats.ks_2samp`. O p-valor foi conferido
  com `scipy.stats.kstwobign.sf(Z)`, que é a distribuição limite adotada neste
  projeto. Não foi substituído pelo p exato ou pela aproximação finita do KS.
- No caso real, os **432 testes de Camargos** — 72 estágios × 3 testes ×
  2 modelos — coincidiram com essas funções de referência.
- Os **477 pares de P90** — 159 usinas × comprimento, módulo da soma e módulo
  da intensidade — coincidiram com o arquivo de conferência do avaliador anterior.
  Foram comparados os percentis sintéticos e históricos, tamanhos e classificações.
- Todos os **2090 resumos de trajetórias de Camargos** do novo modelo coincidiram
  com a evidência anterior, incluindo as 90 janelas históricas.
- A execução em lote das sequências coincidiu com a função anterior executada
  janela a janela, incluindo datas, eventos, resumos e diagnósticos. O teste cobre
  também cenário incompleto, mês histórico ausente e usina com vazão zero.
- Testes específicos confirmaram intensidade `I = S/C` do mesmo evento, extremos
  independentes, zeros para trajetórias válidas sem eventos e recuo anual das janelas.
- Zeros e constantes foram preservados: Welch/Levene sem denominador válido ficam
  não calculados; duas distribuições constantes idênticas podem ter KS D=0 e p=1.

Foram reaproveitados testes dos dois geradores, cobrindo a extração dos parâmetros,
ordem final, coeficientes, escala, campos anuais, calendário, nó nulo no NEWAVE,
slack do bloco zero no novo modelo e preservação da saída quando ocorre falha.

## Completude e integridade

Os **2618 blocos incorporados** do relatório final foram integralmente
descompactados e verificados contra o índice, inclusive tamanhos, unicidade dos
IDs de bloco, dimensões dos vetores e contagens dos memoriais separados.

Na otimização que separou as amostras dos memoriais, os objetos reconstruídos
foram comparados aos objetos originais, sem alterar seus valores. Os **392 blocos
estatísticos que não precisavam ser particionados** mantiveram exatamente os
mesmos bytes compactados, conferidos por SHA-256.

As vazões são incorporadas como float64, preservando inclusive os valores não
finitos para diagnóstico; não são arredondadas para montar os gráficos. Tabelas
registram valores indisponíveis como nulos com status/motivo. Não houve amostragem
de cenários, eventos ou linhas dos memoriais.

Os hashes dos **29 arquivos originais reaproveitados** foram conferidos e
permaneceram iguais aos do início da cópia. O manifesto registra os hashes das
cópias locais e identifica as adaptações de integração.

## Consulta e apresentação

O teste com Chrome foi executado com rede desativada e abertura por `file://`.
Foram verificados:

- Seis abas na visão do SIN, todas sem gráficos.
- Cinco abas por usina, com filtros locais pelo nome.
- Novo modelo antes de NEWAVE em cada tipo de conteúdo.
- Seis gráficos individuais em médias, variâncias e distribuição; quatro em
  correlação espacial; oito em sequências, no modo Comparação.
- Boxplots mensais com os 144000 valores sintéticos por UHE e modelo, além dos
  históricos mensais correspondentes.
- Histórico preto, novo modelo ciano e NEWAVE laranja amarronzado.
- P-valores em barras, significância sólida e percentual aprovado fora da área de dados.
- Máximo/Média nas sequências, sem seletor de estágio; caixas próximas e unidades legíveis.
- Filtro de estágio aplicando o mesmo intervalo aos dois modelos.
- Memoriais paginados, busca global, ordenação numérica e rolagem horizontal sincronizada.
- Distância da curva empírica desenhada igual à estatística D calculada em Python.
- Ausência de erros de JavaScript e de requisições externas.

Foram inspecionadas visualmente as capturas reais de indicadores, médias/desvios,
boxplots mensais e sequências. Os gráficos são interativos e permitem ampliar o
intervalo visível pelo controle de zoom do próprio gráfico.

## Volume e desempenho observados

| Medida | Caso real |
| --- | ---: |
| Tamanho do HTML final | 763004139 bytes, aproximadamente 763 MB |
| Primeira visão utilizável | 4,873 segundos |
| Pico observado nos processos Chrome do teste | 2324,5 MiB |
| Execução inicial das contas e geração | aproximadamente 9 min 38 s |

O tempo da geração inicial foi medido antes da separação final dos blocos de
consulta; essa separação reutilizou os resultados já calculados. Os tempos dependem
da máquina, dos dados e dos outros programas em execução. A busca e a ordenação
de milhões de eventos são operações de consulta maiores e mostram progresso.

O tamanho resulta da inclusão dos dados e memoriais completos. A leitura do HTML
final requer somente o navegador. Python e bibliotecas são necessários na geração.

## Evidências locais

- `outputs/verificacao/testes_completos.log`: execução dos testes automatizados.
- `outputs/verificacao/janela.json`: inicialização e alternância dos modos da janela.
- `outputs/verificacao/real/geracao.json`: duração e contagens da geração real inicial.
- `outputs/verificacao/real/auditoria.json`: regressões numéricas e hashes originais.
- `outputs/verificacao/real/auditoria_final.json`: verificação integral do HTML final.
- `outputs/verificacao/real/final.json`: localização e contagens da entrega final.
- `outputs/verificacao/navegador_real/navegador.json`: verificação offline completa.
- `outputs/verificacao/navegador_real/*.png`: capturas reais inspecionadas.

As curvas de densidade e os pontos empíricos são desenhados em JavaScript com as
amostras completas incorporadas. Os parâmetros da suavização e todos os resultados
dos testes de hipótese são produzidos em Python. A apresentação não altera o
p-valor ou a decisão. Os métodos estatísticos preservam as limitações do avaliador
anterior; a verificação demonstra consistência de implementação, sem afirmar que
aprovação no teste prova igualdade entre as populações.

## Atualização 1.1 — cinco abas e correlação anual

A visão geral do SIN passou a ter cinco abas, sem a aba de resumo. Cada um dos
três primeiros testes reúne seus indicadores, resumo por estágio, ranking e
memorial; os indicadores P90/P50 ficam na análise de sequências. Foram conferidos
a ordem dos conteúdos, a intercalação dos modelos e o efeito do intervalo de
estágios. As buscas e o filtro de resultado do memorial são identificados como
controles dessa seção e não alteram os indicadores de todas as usinas.

Na correlação espacial da visão do SIN, foram incluídos os boxplots anuais por
bacia de referência. A comparação continua sendo de cada modelo com seu
histórico. O histórico é um ponto preto. A tabela de quartis e os memoriais
anuais e mensais permanecem disponíveis na mesma aba.

O relatório foi atualizado a partir do último relatório do usuário,
`comparacao_novo_modelo_newave_20261102_180748.html`, preservado integralmente.
Os 2618 blocos de dados incorporados foram copiados sem alteração e conferidos
por SHA-256. A atualização não executa novamente os cálculos estatísticos.

Nos testes do navegador, foram confrontados os valores desenhados com os
coeficientes incorporados, incluindo a troca da bacia de referência e o uso
do par na ordem inversa. No caso real, a referência Amazonas apresentou
14 caixas por modelo, formadas por 28000 coeficientes válidos, e 14 pontos
históricos por modelo. Todos coincidiram com os memoriais. Nenhum valor
indefinido foi convertido em zero.

O caso pequeno inclui bacia com correlação indefinida, IDs distintos e períodos
históricos diferentes. Também foi verificado que os cinco painéis por usina
continuam disponíveis com seus filtros próprios. A navegação foi executada
offline, com ausência de erros e requisições externas, e as capturas do gráfico
anual foram inspecionadas visualmente.

Os 39 testes automatizados passaram, incluindo a verificação de que atualizar
a interface conserva os blocos e preserva o relatório de origem.

Evidências desta atualização:

- `outputs/verificacao/alteracao_abas_testes.log`.
- `outputs/verificacao/alteracao_abas_fixture.log`.
- `outputs/verificacao/alteracao_abas/atualizacao_real.json`.
- `outputs/verificacao/alteracao_abas/navegador_real/navegador.json`.
- `outputs/verificacao/alteracao_abas/navegador_real/correlacao_anual_bacias.png`.
