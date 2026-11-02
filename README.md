# Avaliador de vazões em HTML

Versão **1.1.0**. Avaliação de séries de vazões incrementais do novo modelo
(COBRE) e do NEWAVE contra seus respectivos históricos, em relatório HTML offline.

Abra **GERAR_RELATORIO_HTML.bat** para selecionar as entradas e gerar o relatório.

O programa oferece **Análise** de um modelo ou **Comparação** com os dois.
Cada modelo é avaliado contra seu histórico, com significância fixa de 5%.

Os relatórios são gravados em **relatorios/** e funcionam diretamente no
navegador, sem servidor ou conexão com a internet.

- [Como usar e organização das pastas](documentacao/README.md)
- [Especificação completa](documentacao/PLANO_IMPLEMENTACAO_AVALIADOR_HTML.md)
- [Verificação da implementação](documentacao/VERIFICACAO_IMPLEMENTACAO.md)

Os atalhos **GERAR_PARQUET_NOVO_MODELO.bat** e **GERAR_PARQUET_NEWAVE.bat**
executam as cópias independentes dos geradores reaproveitados.

## Requisitos e primeira execução

- Windows para a janela e os atalhos `.bat`.
- Python 3.10 ou superior, com `pip` e `Tkinter`, disponível pelo comando `python`.
  A execução foi verificada com Python 3.12.
- Internet para instalar bibliotecas ausentes na primeira execução.

As bibliotecas são verificadas e instaladas automaticamente em `.python_packages/`
quando necessário. Também é possível instalá-las com:

```powershell
python -m pip install -r requirements.txt
```

O repositório contém o programa, o cadastro de bacias, os testes, as licenças das
bibliotecas incorporadas e a documentação. Os insumos do estudo são selecionados
pelo usuário: pasta do deck COBRE e um ou dois Parquets de cenários. Relatórios,
insumos e bibliotecas instaladas localmente são ignorados pelo Git.

## Organização das análises

As duas visões têm cinco abas: Teste de médias, Teste de variâncias, Teste de
distribuição, Correlação espacial e Análise de sequências. A visão do SIN reúne
indicadores e memoriais na respectiva análise. Na correlação espacial, exibe os
boxplots anuais entre bacias com ponto histórico. A visão por usina mantém filtros
independentes em cada aba.

Welch bilateral, Levene com centro na média e KS com distribuição limite de
Kolmogorov usam significância fixa de 5%. Correlações e P50/P90 de sequências
são análises descritivas. Os cálculos e as tabelas completas são incorporados
no HTML; a consulta usa filtros, ordenação e paginação.

## Testes

Na pasta do projeto:

```powershell
python -m unittest discover -s testes -v
```

Os testes geram casos pequenos em diretórios temporários. Não é necessário
incluir os Parquets reais no repositório para executá-los. A verificação de
navegação offline é documentada em `documentacao/README.md`.
