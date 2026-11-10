# Avaliador de vazões em HTML

**Atualização de 06/11/2026 — versão local 1.2.0:** o modo Comparação também
aceita **Novo modelo × Novo modelo**, com deck, histórico e identificação de
versão por fonte. As contas foram preservadas. Consulte
[Comparação entre versões](COMPARACAO_ENTRE_VERSOES.md).

Novo projeto independente, na Área de Trabalho, para avaliar novo modelo
(COBRE), NEWAVE ou ambos contra seus respectivos históricos.

## Como gerar

1. Abra `GERAR_RELATORIO_HTML.bat`, na raiz deste projeto.
2. Escolha **Análise** e o modelo, ou **Comparação** para incluir ambos.
3. Selecione a raiz do deck COBRE. O programa encontra `system/hydros.json`,
   `stages.json` e `scenarios/inflow_history.parquet`.
4. Selecione o Parquet do novo modelo, do NEWAVE ou ambos, conforme o modo.
5. Confira início e fim inclusivos do histórico de **cada modelo**, em `AAAA-MM`.
   A proposta NEWAVE vem dos metadados PARPVAZ. Para o novo modelo, a proposta
   é o histórico disponível no deck: confirme se corresponde ao ajuste desejado.
6. Clique em **Gerar relatório HTML** e aguarde a conclusão.

O resultado abre no navegador e fica em `relatorios/`. O nome identifica o modo,
os modelos e a data/hora de Brasília. Relatórios existentes não são sobrescritos.
As últimas entradas são lembradas na próxima abertura.

Em Comparação, os dois Parquets precisam ter as mesmas usinas, identificadas pelo
nome, e exatamente os mesmos meses/anos sintéticos. Os IDs podem ser diferentes.
O número de cenários pode diferir; todas as observações de cada modelo são usadas.
Não existe número fixo de estágios ou de cenários no programa.

O período histórico escolhido é aplicado **antes** de todos os cálculos, inclusive
MLTs, correlações e janelas históricas. Não é necessário editar o Parquet original.
Se o período NEWAVE não puder ser identificado, o usuário deve informá-lo.

## Como consultar

**Visão geral do SIN** tem cinco abas, uma para cada análise. A aba separada de
resumo foi removida: médias, variâncias e distribuição reúnem seus indicadores,
resumo por estágio, ranking e memoriais. Os P90/P50 ficam em Análise de sequências.
Os resultados dos modelos são intercalados por conteúdo. O intervalo de estágios
afeta os indicadores e tabelas da própria aba; a busca e o filtro de resultado
abaixo do ranking atuam apenas sobre o memorial.

**Resultado por Usina** tem cinco abas. Busque a usina pelo nome em cada aba;
as seleções são independentes. Os gráficos aparecem em pares, novo modelo ×
histórico seguido de NEWAVE × histórico. Novo modelo é ciano; NEWAVE é laranja
amarronzado; histórico é preto.

- Médias: média e desvio padrão, boxplots das vazões completas e p-valores.
- Variâncias: desvios padrão, sua diferença e p-valores.
- Distribuição: densidades, distribuições acumuladas com distância KS e p-valores.
- Correlação espacial: correlação mensal da UHE por bacia e usinas da bacia.
- Sequências: quatro boxplots, com Máximo/Média, para o horizonte completo.

Na visão geral, Correlação espacial apresenta os **boxplots da correlação anual
entre bacias**, com seletor de bacia de referência, distribuição completa dos
coeficientes dos cenários e ponto histórico preto. O novo modelo aparece primeiro,
seguido de NEWAVE, com o mesmo eixo. Abaixo ficam os quartis e todos os memoriais.
Essa é a única análise com gráficos na visão geral. A análise de sequências apresenta P90 e P50 por usina e
os percentuais gerais. Correlações e percentis não recebem decisão de hipótese.

As tabelas oferecem busca, ordenação numérica, paginação e rolagem horizontal
superior e inferior. Memoriais maiores ficam recolhidos. Buscas e ordenações
abrangem todas as linhas, mesmo quando apenas uma página aparece. Durante consultas
grandes, o contador mostra o avanço. Para limitar uma consulta, use a busca por nome
da própria aba antes de abrir o memorial.

Os números visíveis usam vírgula decimal, sem separador de milhar. Passar o mouse
sobre uma célula numérica mostra sua precisão completa. As decisões usam os valores
originais, sem arredondar. Não calculado não significa reprovado.

O único arquivo de consulta é o HTML. Ele pode ser movido e aberto offline em outro
computador. Como inclui todos os dados e memoriais, pode ter centenas de megabytes.
Não é necessário manter os Parquets junto do relatório. A geração requer Python e
as dependências; a leitura requer somente um navegador atual.

## Geradores reaproveitados

`GERAR_PARQUET_NOVO_MODELO.bat` e `GERAR_PARQUET_NEWAVE.bat` executam cópias locais
das rotinas já usadas. Os seletores orientam quais pastas e arquivos são necessários.
As saídas dessas cópias ficam em `parquet gerado novo modelo/` e
`parquet gerado newave/`. A estrutura enriquecida dos Parquets é preservada.

Os geradores e dashboards dos outros projetos não foram alterados.

## Organização

| Pasta | Conteúdo |
| --- | --- |
| `aplicacao/` | Janela, linha de comando, leitura e correspondência das entradas. |
| `calculos/` | Cópias das contas e análises do avaliador. |
| `dados/` | Validação dos arquivos, metadados e cadastro interno de bacias. |
| `geradores/` | Geradores de Parquet do novo modelo e NEWAVE. |
| `relatorio/` | Execução das análises e empacotamento do HTML. |
| `recursos/` | Template, CSS, JavaScript e licenças das bibliotecas incorporadas. |
| `infraestrutura/` | Preparação das dependências locais. |
| `documentacao/` | Especificação, instruções e evidências de verificação. |
| `testes/` | Testes e utilitários de auditoria. |
| `outputs/verificacao/` | Logs, casos artificiais identificados e capturas de verificação. |
| `relatorios/` | Relatórios reais gerados. |

## Linha de comando

Na pasta do projeto:

```powershell
python -m aplicacao.executar --deck "C:\estudo\deck_cobre" --novo "C:\dados\novo.parquet" --newave "C:\dados\newave.parquet" --sem-abrir
```

Para um modelo, informe somente `--novo` ou somente `--newave`. Os recortes
opcionais são `--novo-inicio AAAA-MM`, `--novo-fim AAAA-MM`, `--newave-inicio`
e `--newave-fim`. Início e fim devem ser informados juntos. `--saida` aceita
um caminho `.html` que ainda não existe.

## Verificação

```powershell
python -m unittest discover -s testes -v
python -m testes.verificar_navegador "C:\caminho\relatorio.html" --pasta outputs/verificacao/navegador --real
```

O segundo comando é um teste de desenvolvimento com Chrome instalado, Playwright
e psutil. Não é necessário instalar essas ferramentas para usar o HTML.
O sinalizador `--real` corresponde ao caso de referência de 72 estágios e 2000
cenários. Os testes pequenos de desenvolvimento estão identificados como fixtures;
seus valores artificiais não são dados do estudo.

## Especificação

Leia o [plano completo de implementação](PLANO_IMPLEMENTACAO_AVALIADOR_HTML.md).

Ele reúne as decisões de entradas, históricos por modelo, cinco abas gerais,
cinco abas por usina, cálculos preservados, tabelas, gráficos, cores, geração
de HTML único, organização do projeto e critérios de validação.
