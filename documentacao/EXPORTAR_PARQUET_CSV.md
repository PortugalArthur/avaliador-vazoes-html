# Exportação de Parquet exclusivamente para Excel

Abra **EXPORTAR_PARQUET_EXCEL.bat** na raiz do avaliador. A ferramenta lê os Parquets gerados do novo modelo e do NEWAVE, com ou sem parâmetros enriquecidos. Também aceita `inflow_history.parquet` dos decks reais.

Use **Exportar Excel (.xlsx)…**. A opção CSV foi removida dos dois
exportadores, inclusive da rotina de gravação: destinos com outra extensão
são recusados. Os antigos atalhos foram renomeados de `_CSV.bat` para
`_EXCEL.bat`. Os arquivos já exportados anteriormente permanecem preservados.

## Janela específica do histórico

Abra **EXPORTAR_HISTORICO_EXCEL.bat**, na mesma pasta. Selecione o
`scenarios/inflow_history.parquet` do deck, opcionalmente carregue a pasta do
deck para obter os nomes das usinas, e filtre usina, intervalo de meses/anos e
mês do ano. Não há campos de estágios sintéticos ou cenários nessa janela.

Por exemplo: CAMARGOS, de 2022-01 a 2025-12, mês Janeiro. O Excel conterá os
janeiros existentes, cada ano na sua linha, com `value_m3s` original e as datas.
Não é calculada uma média de janeiros e nenhum ano ausente é preenchido.

Essa janela aceita históricos no formato `hydro_id`, `start_date`, `end_date`,
`value_m3s`. Não lê diretamente o arquivo binário `vazoes.dat` do NEWAVE.

## Como usar

1. Selecione o Parquet real que deseja consultar.
2. Para COBRE, opcionalmente selecione o deck correspondente para mostrar nomes e associar estágios às datas. Sem deck, pode filtrar por IDs. No NEWAVE, nomes e datas são lidos dos metadados do Parquet.
3. Busque a usina por nome ou ID. A busca seleciona as usinas exibidas; use Ctrl/clique para escolher mais de uma ou apenas uma. A exportação considera as selecionadas.
4. Selecione o intervalo de estágios e cenários. No histórico, selecione o período inicial/final. O mês do ano permite, por exemplo, exportar somente janeiros, preservando uma linha por ano existente.
5. Escolha as colunas. O botão **Somente identificação e vazões** evita exportar todos os parâmetros quando só deseja conferir as contas estatísticas.
6. Clique em **Atualizar prévia e contar linhas**. A prévia mostra no máximo 30 registros, mas informa a quantidade total filtrada.
7. Clique em **Exportar Excel (.xlsx)…** e escolha o local. Todas as linhas filtradas serão exportadas, não apenas as 30 da prévia.

O controle opcional de cadastro acrescenta `nome_usina`, `inicio_estagio` e `fim_estagio`, conforme os dados disponíveis. Essas colunas são identificações do cadastro, não parâmetros recalculados.

## Para fazer uma conferência manual com dados reais

Para a amostra sintética, selecione uma usina e um único estágio; depois restrinja a poucos IDs de cenário existentes. Para a amostra histórica, abra o histórico do deck, escolha a mesma usina, o mês correspondente ao estágio e o intervalo de anos desejado. Exporte as duas seleções separadamente.

**Um teste sobre quatro cenários e quatro anos históricos não terá, em geral, o mesmo resultado de um teste sobre 2000 cenários e 95 anos.** Para conferir exatamente uma linha do relatório completo, use no cálculo manual todas as observações que aquela linha utilizou. O exportador apenas entrega as linhas selecionadas; não altera o conjunto do relatório nem aplica esses filtros ao avaliador.

## Formato e preservação dos dados

- Formato: Excel `.xlsx`, com números em células numéricas, sem precisar interpretar delimitadores de texto.
- Sem separador de milhar. O separador decimal exibido acompanha a configuração do Excel.
- Nulos: célula vazia; zero continua zero. NaN/infinito, se presentes, são escritos explicitamente.
- Datas: ISO, como `2026-01-01`.
- Floats: gravados diretamente a partir da consulta, sem `round`, truncamento de casas ou substituição de valores. A precisão numérica é limitada pelo formato e pelo Excel.
- Colunas e valores originais preservados, salvo a seleção explícita de colunas/linhas. O cadastro só é acrescentado se marcado.
- Não calcula médias, desvios, p-valores ou qualquer teste. Não agrupa meses, não elimina duplicatas e não preenche dados ausentes.
- Ordenação: usina, estágio pela data quando disponível, cenário e nó; no histórico, usina e datas.
- O Parquet é somente lido. O Excel é preparado em arquivo temporário e publicado após a conclusão; falhas preservam uma saída anterior.

O arquivo deve estar acessível e conter as colunas identificadoras de cenários ou de histórico. Mapeamentos ausentes não são inventados: o filtro por mês de cenários exige calendário no Parquet ou no deck.

### Particularidades do Excel

- O `.xlsx` armazena números como números e usa formatos sem agrupamento de milhares. Seu separador decimal na tela segue a configuração do Excel.
- O Excel trabalha com aproximadamente **15 algarismos significativos**. Aumentar casas na tela não aumenta esse limite. A exportação não aplica arredondamento explícito nas vazões. [Documentação Microsoft](https://support.microsoft.com/en-us/excel/change-formula-recalculation-iteration-or-precision-in-excel).
- A apresentação permite até 30 casas decimais opcionais, sem zeros artificiais obrigatórios. Valores muito pequenos ou grandes usam notação científica com até 17 algarismos na apresentação. A formatação altera somente a exibição, não o valor consultado. O serializador da biblioteca XLSX grava até 16 algarismos significativos no arquivo; abrir e calcular no Excel continua sujeito à precisão do próprio programa.
- IDs inteiros com mais de 15 dígitos e valores `Decimal` com mais de 15 algarismos significativos são gravados como texto para preservar seus dígitos. Valores muito pequenos usam notação científica para não aparecerem como zero.
- Nulos ficam vazios; zero continua sendo um número. Textos são gravados como texto, não como fórmulas.
- Quando o limite de linhas de uma planilha é alcançado, o exportador continua na aba seguinte sem omitir registros.

## Verificação

Os testes de `testes/test_exportar_csv.py` cobrem os dois modelos, histórico, filtros combinados, calendário com IDs fora de ordem, seleção de colunas, cadastro, nulos, precisão numérica, prévia versus exportação completa e preservação das fontes/saídas em caso de falha.

O nome interno do módulo e deste guia foi mantido para preservar referências
existentes. Isso não disponibiliza exportação CSV. Os testes verificam também
a recusa desse formato sem alterar uma saída anterior.
