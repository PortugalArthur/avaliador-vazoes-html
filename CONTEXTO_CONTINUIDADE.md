# Contexto para continuar — Avaliador de Vazões HTML — edição completa

Atualizado em **25/11/2026**.

## Estado publicado

- Código de trabalho na branch `main`. A release **v1.2.2** foi empacotada a partir do commit `c7b01ac`. [Código da release](https://github.com/PortugalArthur/avaliador-vazoes-html/tree/v1.2.2)
- O pacote portátil é para **Windows x64** e inclui CPython, Tcl/Tk e dependências, com a variante compatível do Polars. [Baixar o ZIP](https://github.com/PortugalArthur/avaliador-vazoes-html/releases/download/v1.2.2/AVALIADOR_VAZOES_HTML_WINDOWS_X64.zip) · [SHA-256](https://github.com/PortugalArthur/avaliador-vazoes-html/releases/download/v1.2.2/AVALIADOR_VAZOES_HTML_WINDOWS_X64.sha256)
- A outra edição fica em um repositório separado. [Somente Novo Modelo](https://github.com/PortugalArthur/Avaliador_Vazoes_Novo_Modelo_Apenas)

## O que foi feito

A v1.2.1 passou a oferecer o ZIP portátil com um inicializador único para os atalhos. A release foi montada sobre o código que já estava no GitHub e ainda exibia os boxplots anuais de correlação entre bacias na visão geral do SIN. A v1.2.2 incorporou a análise por estágio da pasta principal e o raio espectral anual por usina no ranking do teste de médias, quando o Parquet contém os parâmetros do ajuste.

A cópia local de distribuição foi aposentada após a comparação dos resultados. A edição dedicada ao Novo Modelo ganhou seu próprio repositório.

Nesta edição, é possível:

- Analisar o Novo Modelo (COBRE) ou o NEWAVE individualmente.
- Comparar Novo Modelo × NEWAVE.
- Comparar duas versões do Novo Modelo, com o deck e o período histórico de cada uma.

Na **Visão geral do SIN → Correlação espacial**, escolha **Bacia A** e **Bacia B**. Para cada estágio, o sintético calcula Pearson sobre as somas das vazões incrementais, pareadas pelo mesmo cenário. O histórico pareia os totais do mesmo mês civil pelo mesmo ano. O relatório inclui a composição das bacias, os totais pareados e as contagens do memorial. [Interface](recursos/interacao.js) · [Cálculo por bacia](recursos/correlacao_bacias.js)

## Rodar em outro computador

1. Baixe o ZIP portátil na release e extraia todo o conteúdo em uma pasta gravável.
2. Mantenha a pasta `_python` junto aos atalhos e execute `GERAR_RELATORIO_HTML.bat`.
3. Selecione o deck, o Parquet de cenários e o período histórico de cada fonte. Os arquivos de estudo devem ser levados separadamente. O deck fornece `system/hydros.json`, `stages.json` e `scenarios/inflow_history.parquet`.
4. Gere um HTML novo para ver a interface desta release. Cada relatório já gerado incorpora os recursos da versão que o criou.

`GERAR_PARQUET_NOVO_MODELO.bat` e `GERAR_PARQUET_NEWAVE.bat` geram os Parquets para cada fonte. Os atalhos `EXPORTAR_PARQUET_EXCEL.bat` e `EXPORTAR_HISTORICO_EXCEL.bat` ajudam a conferir os insumos. [Guia de uso](documentacao/README.md)

## Continuar o desenvolvimento

Clone o repositório e abra a pasta no VS Code. Para os comandos de desenvolvimento no Windows, use Python x64 completo com Tcl/Tk e pip. Os testes JavaScript usam Node.js quando disponível.

```powershell
git clone https://github.com/PortugalArthur/avaliador-vazoes-html.git
cd avaliador-vazoes-html
python -m pip install -r requirements.txt
python -m unittest discover -s testes -v
```

- [Entradas e geração](aplicacao/executar.py) · [Carregamento de fontes e histórico](aplicacao/fontes.py) · [Motor do relatório](relatorio/motor.py).
- [Inicializador dos atalhos](iniciar_avaliador.bat) · [Empacotador Windows](infraestrutura/empacotar_portatil.py) · [Workflow de release](.github/workflows/distribuir-windows.yml).

Para preparar um ZIP local a partir de um commit, execute o empacotador. Ele arquiva os arquivos versionados, inclui o Python e testa os atalhos com o PATH restrito.

```powershell
python -m infraestrutura.empacotar_portatil --destino outputs/distribuicao --ref HEAD
```

Para publicar outra versão, atualize `VERSAO` em `aplicacao/executar.py` e acompanhe o workflow em `main`. Ele verifica o pacote antes de publicar o ZIP e o SHA-256. Uma release existente é preservada.

## Validação registrada

- **75 testes automatizados** passaram na revisão da v1.2.2.
- O HTML foi aberto offline em quatro modos — Novo Modelo, NEWAVE, Novo Modelo × NEWAVE e Novo Modelo × Novo Modelo. Foram conferidas as barras por estágio, a troca de bacia e o memorial.
- Os cinco atalhos do ZIP oficial foram executados com o PATH restrito aos utilitários do Windows. O ZIP baixado foi conferido por SHA-256.

A comparação entre as edições locais e o código da v1.2.2 completa usou os mesmos decks, Parquets e períodos históricos. Os blocos de resultados nos modos em comum foram idênticos. [Execução do empacotamento](https://github.com/PortugalArthur/avaliador-vazoes-html/actions/runs/45664736236)

## Diagnóstico em aberto na edição completa

Foi relatada a mensagem **“A sintaxe do nome do arquivo, do nome do diretório ou do rótulo do volume está incorreta”** ao abrir os atalhos depois de extrair um ZIP na Área de Trabalho. A falha não foi reproduzida com o artefato oficial da v1.2.2. A extração que apresentou o erro ainda precisa ser conferida.

Abra um terminal na pasta extraída em que `_python` está ao lado das `.bat` e execute o atalho com a opção de diagnóstico.

```cmd
cmd /d /c "GERAR_RELATORIO_HTML.bat --verificar-ambiente"
```

Se o erro voltar, registre o nome do ZIP usado, o caminho completo da pasta, se `_python\python.exe` está presente e a saída integral do comando. Essa comparação permite investigar a extração ou a inicialização sem alterar os dados do estudo.
