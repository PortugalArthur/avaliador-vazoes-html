# Comparação entre versões — avaliador HTML 1.2.0

Implementação local em 06/11/2026, em `C:\Users\Pichau\Desktop\ONS\Vazoes\AVALIADOR_VAZOES_HTML`.

## Seleção

O `GERAR_RELATORIO_HTML.bat` continua abrindo a janela de geração. Permanecem **Análise** de um modelo e **Comparação** com duas fontes. Em Comparação, um novo seletor escolhe **Novo modelo × NEWAVE** ou **Novo modelo × Novo modelo**.

Para duas versões:

1. Selecionar deck A e Parquet A do novo modelo.
2. Selecionar Parquet B do novo modelo e seu respectivo deck B.
3. Informar nomes distintos, por exemplo `COBRE 0.19.1` e `COBRE 0.20.0`.
4. Conferir os períodos históricos A e B, propostos a partir dos respectivos decks e editáveis.
5. Gerar o relatório único.

Cada deck deve conter `system/hydros.json`, `stages.json` e `scenarios/inflow_history.parquet`. Pode-se escolher o mesmo deck nos dois campos se ele corresponder de fato aos dois estudos. Os Parquets devem ser arquivos distintos. Não é necessário alterar os metadados de um arquivo COBRE para NEWAVE.

A janela possui rolagem para acomodar os novos campos. Ao trocar o tipo de comparação, a segunda entrada é limpa para evitar reaproveitamento acidental de um arquivo da outra origem.

## Histórico e correspondência

O período A é validado contra os limites do histórico A; o B, contra o histórico B. O recorte usa os IDs do respectivo histórico e remapeia somente os IDs para corresponder à série analisada. Os valores de vazão são preservados.

Os IDs internos do deck A continuam sendo a identificação comum da interface. O programa associa as fontes por nome normalizado e confere exatamente o mesmo horizonte de mês/ano. IDs de usinas e estágios podem diferir entre versões. Falta de correspondência, ambiguidade ou período inválido interrompem a geração.

Para investigar especificamente o efeito da versão do programa, conferir que os estudos usam os mesmos insumos, períodos e configurações. O avaliador permite históricos diferentes e registra os arquivos e recortes usados, sem afirmar que eles são iguais.

## Contas e visualização

**Nenhum dos 16 arquivos Python de `calculos/` foi modificado.** Permanecem Welch bilateral, Levene com centro na média, KS com p-valor da distribuição limite, correlações, sequências negativas e indicadores P50/P90. Alfa permanece 0,05.

Cada fonte continua sendo avaliada **contra seu histórico**, não por um teste novo entre versões. Os nomes escolhidos aparecem nos gráficos, tabelas e identificação de fontes. A permanece ciano, B laranja e histórico preto. As cinco abas, as duas visões, filtros e memoriais permanecem.

O manifesto registra `tipo_comparacao`, os nomes, o arquivo histórico de cada fonte, seus limites disponíveis e período selecionado. Os três arquivos de cada deck e os dois Parquets entram na verificação de integridade. O nome automático do HTML distingue `comparacao_novo_modelo_novo_modelo` de `comparacao_novo_modelo_newave`.

CLI preservada, com opções adicionais:

```powershell
python -m aplicacao.executar --tipo-comparacao novo_novo --deck "C:\dados\deck_a" --novo "C:\dados\versao_a.parquet" --deck-referencia "C:\dados\deck_b" --newave "C:\dados\versao_b.parquet" --rotulo-novo "COBRE 0.19.1" --rotulo-referencia "COBRE 0.20.0" --sem-abrir
```

Por compatibilidade, `--newave` nomeia o segundo argumento mesmo quando seu conteúdo é COBRE B. `--novo-inicio`, `--novo-fim`, `--newave-inicio` e `--newave-fim` continuam permitindo escolher os recortes A e B.

## Evidências da adaptação

Suíte final: **43 testes passaram**, incluindo os 39 existentes e quatro casos novos.

- Hashes dos 16 módulos de cálculo conferidos antes/depois: inalterados.
- 144 blocos de resultados do modo anterior comparados com referência salva antes da alteração. Correspondência preservada; agregações paralelas float64 são verificadas com `rtol=2e-12`, `atol=1e-12`, sem arredondar os dados de produção ou mudar a regra de aprovação.
- Duas cópias de valores iguais produzem os mesmos resultados de todas as análises, dentro desse ruído numérico de agregação; não se espera aprovação universal, pois cada uma ainda é testada contra o histórico.
- Deck B com IDs próprios, período menor e valores históricos deliberadamente distintos em dados de teste: conferência do recorte e do p-valor pela função nativa do SciPy.
- Bloqueios de origem incorreta, deck ausente, calendário diferente, rótulos iguais, mesmo arquivo e período fora dos limites.
- Navegação offline no novo modo: cinco abas gerais e cinco por usina, nomes das versões, gráficos, boxplots anuais e seus pontos históricos, filtros, ordenação e barras de rolagem. Valores de correlação e D desenhados conferidos contra os dados incorporados; nenhuma requisição externa ou exceção no navegador.
- Seletor da janela, habilitação do deck B e encaminhamento de nomes/períodos conferidos em teste isolado das preferências pessoais.

Evidências locais em `outputs/verificacao/duas_versoes/`. A suíte completa e os novos testes ficam em `testes/`. Os dados reais e os geradores de Parquet foram preservados. Esta adaptação não publica automaticamente um novo commit ou tag no GitHub.
