"""Parâmetros mensais padronizados do PAR(p)-A impresso pelo NEWAVE."""

from dataclasses import dataclass
from datetime import date
import hashlib
import math
from pathlib import Path
import re

from dados.metadados_vazoes import normalizar_nome_usina


MESES = ("JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ")
SERIE = re.compile(r"SERIE\s+DE VAZOES\s+DA USINA\s+(.+?)\s+\(CONFIGURACAO No\.\s*(\d+)\)", re.I)
PERIODO = re.compile(r"^\s*PERIODO\s*:\s*([A-Z]{3})/(\S+)\s*$")
AR = re.compile(r"COEFICIENTES DA EQUACAO DE REGRESSAO DE UM PROCESSO AR\(\s*(\d+)\)")


@dataclass
class ParametrosParNewave:
    cadastro: dict
    parametros: dict
    configuracao: int
    historicos: dict
    sha256: str


def _texto(caminho):
    dados = Path(caminho).read_bytes()
    try:
        return dados.decode("utf-8-sig")
    except UnicodeDecodeError:
        return dados.decode("latin1")


def validar_arquivo_parpvaz(caminho):
    p = Path(caminho).resolve()
    if not p.is_file():
        raise ValueError(f"Arquivo parpvaz.dat não encontrado: {p}")
    with p.open("rb") as f:
        cabecalho = f.read(4096).decode("latin1")
    if "ANALISE DO HISTORICO DE VAZAO INCREMENTAL" not in cabecalho:
        raise ValueError("Selecione o relatório parpvaz.dat de vazões incrementais individualizadas.")
    return p


def _numeros(linha, tamanho, contexto):
    campos = linha.split()
    if len(campos) != tamanho:
        raise ValueError(f"{contexto}: esperados {tamanho} valores, encontrados {len(campos)}.")
    try:
        valores = [float(v.replace("D", "E").replace("d", "e")) for v in campos]
    except ValueError as erro:
        raise ValueError(f"{contexto}: valor não numérico.") from erro
    if not all(math.isfinite(v) for v in valores):
        raise ValueError(f"{contexto}: valor não finito.")
    return valores


def _estatistica(linhas, inicio, contexto):
    # A linha mensal é obrigatória: não tomar números de outra seção por estatísticas.
    cabecalho = False
    for s in linhas[inicio + 1:inicio + 10]:
        if s.split() == list(MESES):
            cabecalho = True
        elif cabecalho and s.strip():
            return _numeros(s, 12, contexto)
    raise ValueError(f"{contexto}: estatística mensal ausente.")


def ler_parametros_parpvaz(caminho, max_order):
    """Extrai apenas primeira/terceira linhas e estatísticas; não persiste outras escalas."""
    arquivo = validar_arquivo_parpvaz(caminho)
    if isinstance(max_order, bool) or not isinstance(max_order, int) or max_order < 0:
        raise ValueError("O limite de lags deve ser inteiro não negativo.")
    # split('\n') preserva as linhas físicas vazias de AR(0); splitlines também
    # separaria form feeds e poderia deslocar as quatro linhas do bloco.
    linhas = _texto(arquivo).replace("\r\n", "\n").replace("\f", "").split("\n")
    primeiro = next((i for i, s in enumerate(linhas) if SERIE.search(s)), None)
    if primeiro is None:
        raise ValueError("parpvaz.dat sem séries de vazões por usina.")
    cadastro, por_nome = {}, {}
    for s in linhas[:primeiro]:
        if not re.match(r"^\s*\d+\s", s):
            continue
        try:
            codigo, nome, posto = int(s[:8]), s[9:21].strip(), int(s[21:26])
        except ValueError as erro:
            raise ValueError("Tabela inicial NUM/NOME/POS inválida no parpvaz.dat.") from erro
        _numeros(s[26:], 24, f"Cadastro NEWAVE {codigo}")
        normal = normalizar_nome_usina(nome)
        if not nome or codigo in cadastro or normal in por_nome:
            raise ValueError(f"Cadastro NEWAVE duplicado ou ambíguo: {codigo}, {nome}.")
        cadastro[codigo] = dict(nome=nome, posto=posto)
        por_nome[normal] = codigo
    if not cadastro:
        raise ValueError("Tabela inicial de usinas ausente no parpvaz.dat.")

    blocos, configuracoes, ajustes, ordens = {}, set(), {}, {}
    atual = bloco = None
    for i in range(primeiro, len(linhas)):
        s = linhas[i]
        cab = SERIE.search(s)
        if cab:
            nome, config = cab[1].strip(), int(cab[2])
            atual = por_nome.get(normalizar_nome_usina(nome))
            if atual is None:
                raise ValueError(f"Série de UHE sem cadastro no parpvaz.dat: {nome}.")
            configuracoes.add(config)
            if len(configuracoes) > 1:
                raise ValueError("Múltiplas configurações no parpvaz.dat; associação mensal ambígua.")
            lista = blocos.setdefault(atual, [])
            if len(lista) >= 2:
                raise ValueError(f"UHE {nome}: séries/configurações concorrentes no parpvaz.dat.")
            bloco = dict(anos=[], valores=[])
            lista.append(bloco)
        elif re.match(r"^\d{4}\s", s) and bloco is not None and len(blocos[atual]) <= 2:
            # Séries de ruídos usam índice do ano precedido por espaços e ficam fora daqui.
            bloco["anos"].append(int(s[:4]))
            bloco["valores"].extend(_numeros(s[4:], 12, f"UHE {atual}, histórico {s[:4]}"))
        elif "MEDIA AMOSTRAL DAS VAZOES" in s or "DESVIO PADRAO AMOSTRAL DAS VAZOES" in s:
            if bloco is None:
                raise ValueError("Estatística sem bloco histórico no parpvaz.dat.")
            campo = "media" if "MEDIA AMOSTRAL" in s else "desvio"
            if campo in bloco:
                raise ValueError(f"UHE {atual}: estatística {campo} duplicada.")
            bloco[campo] = _estatistica(linhas, i, f"UHE {atual}, {campo}")
            if campo == "desvio" and any(v < 0 for v in bloco[campo]):
                raise ValueError(f"UHE {atual}: desvio padrão negativo.")
        elif "ORDEM FINAL DO MODELO AUTORREGRESSIVO PARA CADA PERIODO" in s:
            if atual in ordens:
                raise ValueError(f"UHE {atual}: ordem final duplicada.")
            dados = []
            for t in linhas[i + 1:i + 12]:
                if re.match(r"^\s*(POS|PRE|\d{4})\s+", t):
                    dados.append(t.split())
            if len(dados) != 1 or dados[0][0] != "POS" or len(dados[0]) != 13:
                raise ValueError(f"UHE {atual}: ordem final ausente ou múltiplos períodos/configurações.")
            try:
                ordem = [int(x) for x in dados[0][1:]]
            except ValueError as erro:
                raise ValueError(f"UHE {atual}: ordem final não inteira.") from erro
            if any(p < 0 or p > max_order for p in ordem):
                raise ValueError(f"UHE {atual}: ordem final excede o limite de lags {max_order}.")
            ordens[atual] = ordem
        elif AR.search(s):
            cab = AR.search(s)
            anterior = next((t for t in reversed(linhas[max(primeiro, i - 5):i]) if t.strip()), "")
            periodo = PERIODO.match(anterior)
            if atual is None or not periodo or periodo[1] not in MESES or periodo[2] != "POS":
                raise ValueError("Bloco de coeficientes sem UHE/mês POS único no parpvaz.dat.")
            mes, p = MESES.index(periodo[1]) + 1, int(cab[1])
            chave = (atual, mes)
            if chave in ajustes:
                raise ValueError(f"UHE/mês {chave}: ajuste duplicado ou configuração concorrente.")
            if p > max_order:
                raise ValueError(f"UHE/mês {chave}: AR({p}) excede o limite de lags {max_order}.")
            if i + 4 >= len(linhas):
                raise ValueError(f"UHE/mês {chave}: bloco de coeficientes incompleto.")
            # Não pular vazios: para p=0 as duas primeiras linhas são vazias.
            phi = _numeros(linhas[i + 1], p, f"UHE/mês {chave}, primeira linha")
            _numeros(linhas[i + 2], p, f"UHE/mês {chave}, segunda linha")
            theta = _numeros(linhas[i + 3], 1, f"UHE/mês {chave}, terceira linha")[0]
            _numeros(linhas[i + 4], 1, f"UHE/mês {chave}, quarta linha")
            ajustes[chave] = dict(ar_order=p, annual_coefficient=theta,
                                 **{f"ar_coefficient_lag_{k}": phi[k - 1] if k <= p else None
                                    for k in range(1, max_order + 1)})

    historicos = {}
    for codigo, registro in cadastro.items():
        series = blocos.get(codigo, [])
        if len(series) != 2:
            raise ValueError(f"UHE {registro['nome']}: esperados dois blocos históricos.")
        q, a = series
        for b in series:
            anos = b["anos"]
            if (not anos or anos != list(range(anos[0], anos[-1] + 1))
                    or not all(k in b for k in ("media", "desvio"))):
                raise ValueError(f"UHE {codigo}: histórico/estatísticas incompletos ou anos repetidos.")
        if q["anos"] != a["anos"]:
            raise ValueError(f"UHE {codigo}: históricos mensal e anual com anos diferentes.")
        # Confere o segundo bloco sem recalcular/substituir as estatísticas impressas.
        valores, anuais = q["valores"], a["valores"]
        for t in range(12, len(valores)):
            if abs(sum(valores[t - 12:t]) / 12 - anuais[t]) > .011:
                raise ValueError(f"UHE {codigo}: segundo bloco não corresponde à média dos 12 meses anteriores.")
        historicos[codigo] = (q["anos"][0], q["anos"][-1])
        for mes in range(1, 13):
            chave = codigo, mes
            if chave not in ajustes or codigo not in ordens or ajustes[chave]["ar_order"] != ordens[codigo][mes - 1]:
                raise ValueError(f"UHE/mês {chave}: coeficientes ausentes ou divergentes da ordem final.")
            ajustes[chave].update(seasonal_mean_m3s=q["media"][mes - 1],
                                  seasonal_std_m3s=q["desvio"][mes - 1],
                                  annual_mean_m3s=a["media"][mes - 1],
                                  annual_std_m3s=a["desvio"][mes - 1])
    return ParametrosParNewave(cadastro, ajustes, next(iter(configuracoes)), historicos,
                              hashlib.sha256(arquivo.read_bytes()).hexdigest())


def conferir_caso_newave(arquivo_parpvaz, relatorio, periodos):
    """Confere evidências disponíveis; não presume identidade completa de execuções."""
    pasta = Path(arquivo_parpvaz).resolve().parent
    conferidos = []
    dger = pasta / "dger.dat"
    if dger.is_file():
        linhas = _texto(dger).splitlines()
        rotulos = ("MES INICIO DO ESTUDO", "ANO INICIO DO ESTUDO", "No. DE ANOS DO EST", "No. DE ANOS POS FINAL")
        valores = {}
        for rotulo in rotulos:
            for s in linhas:
                m = re.match(re.escape(rotulo) + r"\s+(\d+)\b", s.strip(), re.I)
                if m:
                    valores[rotulo] = int(m[1])
        if len(valores) != 4 or valores[rotulos[2]] < 1:
            raise ValueError("dger.dat ao lado do parpvaz.dat sem horizonte válido para conferência.")
        inicio = date(valores[rotulos[1]], valores[rotulos[0]], 1)
        fim = date(valores[rotulos[1]] + valores[rotulos[2]] + valores[rotulos[3]] - 1, 12, 1)
        if min(periodos) < inicio or max(periodos) > fim:
            raise ValueError("Horizonte QINCR incompatível com o dger.dat ao lado do parpvaz.dat.")
        conferidos.append("dger.dat")
    ree = pasta / "ree.dat"
    if ree.is_file():
        inicios = []
        for s in _texto(ree).splitlines():
            campos = s.split()
            if campos and campos[0] == "999":
                break
            if campos and campos[0].isdigit():
                if len(campos) < 5:
                    raise ValueError("ree.dat não comprova horizonte completamente individualizado.")
                try:
                    inicios.append(date(int(campos[-1]), int(campos[-2]), 1))
                except ValueError as erro:
                    raise ValueError("Data de agregação inválida no ree.dat.") from erro
        if not inicios or min(inicios) <= max(periodos):
            raise ValueError("O ree.dat indica representação agregada dentro do horizonte QINCR; caso não suportado.")
        conferidos.append("ree.dat")
    confhd = pasta / "confhd.dat"
    if confhd.is_file():
        intervalos = {}
        for s in _texto(confhd).splitlines():
            m = re.match(r"^\s*(\d+)\s+.*?\s+(\d{4})\s+(\d{4})\s*$", s)
            if m:
                intervalos[int(m[1])] = (int(m[2]), int(m[3]))
        if any(intervalos.get(c) != anos for c, anos in relatorio.historicos.items()):
            raise ValueError("Limites históricos do confhd.dat divergem do parpvaz.dat.")
        conferidos.append("confhd.dat")
    pmo = pasta / "pmo.dat"
    if pmo.is_file():
        # Leitura sequencial do relatório grande, guardando apenas o intervalo.
        with pmo.open(encoding="latin1") as f:
            intervalos = {tuple(map(int, m.groups())) for s in f
                          if (m := re.search(r"Afluencias:\.*\s*(\d{4})\s*-\s*(\d{4})", s))}
        if intervalos and not set(relatorio.historicos.values()).issubset(intervalos):
            raise ValueError("Histórico de afluências do pmo.dat diverge do parpvaz.dat.")
        if intervalos:
            conferidos.append("pmo.dat")
    return conferidos


def associar_parametros_newave(relatorio, mapa, periodos):
    """NNN é o código NUM do NEWAVE; o hydro_id vem do cadastro de referência."""
    saida = {}
    for item in mapa:
        codigo = int(item["codigo_usina_arquivo"])
        registro = relatorio.cadastro.get(codigo)
        if registro is None or normalizar_nome_usina(registro["nome"]) != normalizar_nome_usina(item["nome_usina_arquivo"]):
            raise ValueError(f"QINCR {item['arquivo_origem']}: código/nome sem correspondência no parpvaz.dat.")
        for mes in {p.month for p in periodos}:
            saida[item["hydro_id"], mes] = relatorio.parametros[codigo, mes]
    return saida
