"""Instala localmente as bibliotecas ausentes usadas pelos programas do projeto."""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
import sysconfig
from collections.abc import Mapping


PASTA_PROJETO = Path(__file__).resolve().parents[1]
ETIQUETA_AMBIENTE = f"{sys.implementation.cache_tag}-{sysconfig.get_platform()}"
PASTA_DEPENDENCIAS = PASTA_PROJETO / ".python_packages" / ETIQUETA_AMBIENTE


def _adicionar_pasta_local() -> None:
    """Torna as bibliotecas locais visíveis também ao Streamlit iniciado em outro processo."""
    herdados = os.environ.get("PYTHONPATH", "").split(os.pathsep)
    for pasta in (PASTA_PROJETO, PASTA_DEPENDENCIAS):
        caminho = str(pasta)
        if caminho not in sys.path:
            sys.path.insert(0, caminho)
        if caminho not in herdados:
            herdados.insert(0, caminho)
    os.environ["PYTHONPATH"] = os.pathsep.join(p for p in herdados if p)


def _mostrar_falha(mensagem: str) -> None:
    """Exibe uma orientação legível no terminal e, quando possível, em uma janela."""
    print(mensagem, file=sys.stderr, flush=True)
    try:
        import tkinter as tk
        from tkinter import messagebox

        janela = tk.Tk()
        janela.withdraw()
        try:
            messagebox.showerror("Preparação do ambiente", mensagem, parent=janela)
        finally:
            janela.destroy()
    except Exception:
        pass


def _versao_numerica(texto: str) -> tuple[int, ...]:
    """Converte versões usuais em uma tupla comparável sem depender de outra biblioteca."""
    numeros = re.findall(r"\d+", texto)
    return tuple(int(numero) for numero in numeros[:4])


def _dependencia_disponivel(modulo: str, requisito: str) -> bool:
    """Confirma a importação do módulo e a versão mínima declarada no requisito."""
    if importlib.util.find_spec(modulo) is None:
        return False
    nome_distribuicao, separador, versao_minima = requisito.partition(">=")
    if not separador:
        return True
    try:
        versao_atual = importlib.metadata.version(nome_distribuicao.strip())
    except importlib.metadata.PackageNotFoundError:
        return False
    return _versao_numerica(versao_atual) >= _versao_numerica(versao_minima)


def garantir_dependencias(dependencias: Mapping[str, str]) -> None:
    """Instala na pasta do projeto somente os pacotes que ainda não podem ser importados."""
    if sys.version_info < (3, 10):
        mensagem = "Estes programas precisam do Python 3.10 ou mais recente."
        _mostrar_falha(mensagem)
        raise SystemExit(1)
    _adicionar_pasta_local()
    ausentes = [pacote for modulo, pacote in dependencias.items() if not _dependencia_disponivel(modulo, pacote)]
    if not ausentes:
        return

    PASTA_DEPENDENCIAS.mkdir(parents=True, exist_ok=True)
    print("Preparando as bibliotecas necessárias na primeira execução...", flush=True)
    comando = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--target",
        str(PASTA_DEPENDENCIAS),
        *ausentes,
    ]
    try:
        subprocess.run(comando, check=True)
    except (OSError, subprocess.CalledProcessError) as erro:
        mensagem = (
            "Não foi possível instalar automaticamente as bibliotecas necessárias.\n\n"
            "Confirme que o computador possui acesso à internet e que o Python foi instalado com o pip.\n\n"
            f"Detalhes: {erro}"
        )
        _mostrar_falha(mensagem)
        raise SystemExit(1) from erro

    importlib.invalidate_caches()
    ainda_ausentes = []
    for modulo, pacote in dependencias.items():
        if not _dependencia_disponivel(modulo, pacote):
            ainda_ausentes.append(modulo)
            continue
        try:
            importlib.import_module(modulo)
        except (ImportError, OSError):
            ainda_ausentes.append(modulo)
    if ainda_ausentes:
        mensagem = "A instalação terminou, mas estas bibliotecas ainda não puderam ser carregadas: " + ", ".join(ainda_ausentes)
        _mostrar_falha(mensagem)
        raise SystemExit(1)
