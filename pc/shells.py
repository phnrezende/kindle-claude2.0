"""Qual shell o Claude Code usa para rodar os comandos dos hooks e da statusLine.

No macOS e no Linux e o bash. No Windows e o Git Bash quando ele esta instalado,
e o PowerShell quando nao esta (documentacao dos hooks e da statusLine do Claude
Code). Os comandos que o setup grava e a statusLine antiga que o statusline.py
repassa precisam seguir a mesma escolha: no PowerShell, por exemplo, um caminho
entre aspas no comeco do comando so roda com o operador &.

So usa a biblioteca padrao e e leve: o statusline.py importa a cada atualizacao.
"""
import os
import shutil


def git_bash():
    """Caminho do bash.exe do Git for Windows, ou None se nao houver."""
    caminho = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")    # o mesmo ajuste do Claude Code
    if caminho and os.path.isfile(caminho):
        return caminho
    candidatos = []
    git = shutil.which("git")
    if git:
        # ...\Git\cmd\git.exe ou ...\Git\mingw64\bin\git.exe
        pasta = os.path.dirname(os.path.realpath(git))
        for raiz in (os.path.dirname(pasta), os.path.dirname(os.path.dirname(pasta))):
            candidatos += [os.path.join(raiz, "bin", "bash.exe"), os.path.join(raiz, "usr", "bin", "bash.exe")]
    bases = [os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432"), os.environ.get("ProgramFiles(x86)")]
    if os.environ.get("LOCALAPPDATA"):                   # instalacao so para o usuario
        bases.append(os.path.join(os.environ["LOCALAPPDATA"], "Programs"))
    for base in bases:
        if base:
            candidatos.append(os.path.join(base, "Git", "bin", "bash.exe"))
    for c in candidatos:
        if os.path.isfile(c):
            return c
    return None


def shell_do_claude(sistema=None):
    """"bash" ou "powershell": o shell que o Claude Code usa neste computador."""
    if (sistema or os.name) != "nt":
        return "bash"
    return "bash" if git_bash() else "powershell"


def argumentos(cmd, sistema=None):
    """Argumentos para rodar `cmd` (um comando de shell) como o Claude Code rodaria."""
    if (sistema or os.name) == "nt":
        bash = git_bash()
        if bash:
            return [bash, "-c", cmd]
        return ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd]
    bash = shutil.which("bash")
    return [bash, "-c", cmd] if bash else ["/bin/sh", "-c", cmd]
