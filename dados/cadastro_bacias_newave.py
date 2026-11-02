"""Cadastro das bacias exibidas na aba 4, a partir de confhd.dat e ree.dat."""

from pathlib import Path

import pandas as pd

from dados.metadados_vazoes import normalizar_nome_usina


def localizar_cadastro_bacias(pasta):
    raiz = Path(pasta).expanduser().resolve()
    if not raiz.is_dir():
        raise ValueError("Selecione uma pasta válida do deck NEWAVE.")
    encontrados = {}
    for nome in ("confhd.dat", "ree.dat"):
        arquivos = [p for p in raiz.iterdir() if p.is_file() and p.name.casefold() == nome]
        if len(arquivos) != 1:
            raise ValueError(f"A pasta do deck NEWAVE deve conter um único arquivo {nome}.")
        encontrados[nome.split(".")[0]] = str(arquivos[0])
    return encontrados


def _linhas(caminho):
    conteudo = Path(caminho).read_bytes()
    if b"\x00" in conteudo:
        raise ValueError(f"{Path(caminho).name}: arquivo de texto inválido.")
    for codificacao in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return conteudo.decode(codificacao).splitlines()
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Não foi possível ler {Path(caminho).name}.")


def ler_cadastro_bacias(confhd, ree):
    """Lê campos de largura fixa, sem confundir número da UHE, posto e bacia."""
    bacias = {}
    iniciou = False
    terminou = False
    for numero_linha, linha in enumerate(_linhas(ree), 1):
        if not linha.strip():
            continue
        campo = linha[1:4].strip()
        if not campo.isdigit():
            if iniciou:
                raise ValueError(f"ree.dat: código de bacia inválido na linha {numero_linha}.")
            continue
        codigo = int(campo)
        if codigo == 999:
            terminou = True
            break  # O bloco seguinte não contém nomes de bacias.
        iniciou = True
        nome = linha[5:15].strip()
        if codigo <= 0 or not nome:
            raise ValueError(f"ree.dat: bacia inválida na linha {numero_linha}.")
        if codigo in bacias:
            raise ValueError(f"ree.dat: código de bacia {codigo} repetido.")
        bacias[codigo] = nome
    if not bacias or not terminou:
        raise ValueError("ree.dat: cadastro de bacias vazio ou sem o terminador 999.")

    usinas, codigos = [], set()
    iniciou = False
    for numero_linha, linha in enumerate(_linhas(confhd), 1):
        if not linha.strip():
            continue
        campo = linha[0:5].strip()
        if not campo.isdigit():
            if iniciou:
                raise ValueError(f"confhd.dat: código de usina inválido na linha {numero_linha}.")
            continue
        codigo = int(campo)
        if codigo == 999:
            break
        iniciou = True
        nome = linha[6:18].strip()
        try:
            bacia = int(linha[30:34].strip())
        except ValueError as erro:
            raise ValueError(f"confhd.dat: bacia inválida na linha {numero_linha}.") from erro
        if codigo <= 0 or not nome:
            raise ValueError(f"confhd.dat: usina inválida na linha {numero_linha}.")
        if codigo in codigos:
            raise ValueError(f"confhd.dat: código de usina {codigo} repetido.")
        if bacia not in bacias:
            raise ValueError(f"confhd.dat: a usina {nome} referencia a bacia {bacia}, ausente em ree.dat.")
        codigos.add(codigo)
        usinas.append({"codigo_newave": codigo, "nome_newave": nome,
                       "bacia_id": bacia, "Bacia": bacias[bacia]})
    if not usinas:
        raise ValueError("confhd.dat: nenhuma usina encontrada.")
    return pd.DataFrame(usinas)


def associar_usinas_bacias(nomes, cadastro):
    """Associação exata após normalização de nomes; nunca por igualdade de IDs."""
    por_nome = {}
    for linha in cadastro.to_dict("records"):
        por_nome.setdefault(normalizar_nome_usina(linha["nome_newave"]), []).append(linha)
    normalizados = {}
    linhas = []
    for hydro_id, nome in nomes.items():
        chave = normalizar_nome_usina(nome)
        if chave in normalizados:
            raise ValueError(f"Cadastro atual com nome de usina ambíguo: {nome}.")
        normalizados[chave] = hydro_id
        candidatas = por_nome.get(chave, [])
        if len(candidatas) > 1:
            raise ValueError(f"confhd.dat contém mais de uma usina correspondente a {nome}; associação ambígua.")
        cadastro_usina = candidatas[0] if candidatas else {}
        linhas.append({"hydro_id": int(hydro_id), "Usina": nome,
                       "codigo_newave": cadastro_usina.get("codigo_newave"),
                       "nome_newave": cadastro_usina.get("nome_newave"),
                       "bacia_id": cadastro_usina.get("bacia_id"),
                       "Bacia": cadastro_usina.get("Bacia")})
    resultado = pd.DataFrame(linhas, columns=["hydro_id", "Usina", "codigo_newave", "nome_newave", "bacia_id", "Bacia"])
    for coluna in ("codigo_newave", "bacia_id"):
        resultado[coluna] = resultado[coluna].astype("Int64")
    return resultado
