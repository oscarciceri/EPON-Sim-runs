#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
runner.py
=========
Orquestrador de simulações por arquivos (file-based queue), feito para substituir o run.cpp antigo.

Ideia geral:
- Você tem um diretório com tarefas pendentes (ex.: /home/oscar/a_tasks).
- Cada tarefa é um arquivo de texto cujo conteúdo (primeira linha não vazia) é um comando a executar
  (normalmente algo como: java -jar EPON-Sim.jar ...).
- Vários workers rodam em paralelo. Cada worker:
  1) "pega" (claim) uma tarefa movendo-a ATOMICAMENTE de a_tasks -> b_running
  2) executa o comando
  3) ao terminar, move o arquivo marcador para c_finished (ou d_failed se falhar)
  4) opcionalmente grava um log por tarefa (stdout + stderr)

Por que isso é melhor que o run.cpp antigo?
- Evita condição de corrida (dois processos pegando a mesma tarefa).
- Não cria "primerArchivo.txt" compartilhado.
- Evita chamar "ls/head/mv" via system() repetidamente.
- Permite logs por tarefa e melhor controle de timeout de ociosidade.
"""

import argparse
import os
import time
import shlex
import random
import subprocess
from pathlib import Path
from multiprocessing import Process


def read_first_nonempty_line(p: Path) -> str:
    """
    Lê o arquivo de tarefa e retorna a primeira linha não vazia (strip).
    Se falhar ou estiver vazio, retorna string vazia.
    """
    try:
        for line in p.read_text(errors="ignore").splitlines():
            line = line.strip()
            if line:
                return line
    except Exception:
        pass
    return ""


def atomic_move(src: Path, dst: Path) -> bool:
    """
    Move o arquivo de forma "atômica" quando possível (mesmo filesystem).
    - Em geral, rename/replace no mesmo FS é atômico.
    - Isso é crucial para evitar corrida entre workers: só 1 worker "ganha" o move.

    Retorna True se moveu, False se não conseguiu.
    """
    try:
        # rename() tende a ser atômico dentro do mesmo filesystem
        src.rename(dst)
        return True
    except FileNotFoundError:
        # Outro worker pode ter movido antes (tarefa já "sumiu")
        return False
    except OSError:
        # Tenta fallback com os.replace, que também substitui se existir
        try:
            os.replace(str(src), str(dst))
            return True
        except Exception:
            return False


def claim_one_task(tasks_dir: Path, running_dir: Path) -> Path | None:
    """
    Tenta "pegar" uma tarefa pendente.
    Implementação:
    - Lista arquivos em tasks_dir (ordenado para previsibilidade)
    - Tenta mover cada arquivo para running_dir
    - O primeiro move que der certo define a tarefa "claimada"

    Se não houver tarefa ou se outras instâncias ganharem a corrida, retorna None.
    """
    try:
        entries = sorted([p for p in tasks_dir.iterdir() if p.is_file()])
    except FileNotFoundError:
        return None

    for src in entries:
        dst = running_dir / src.name
        if atomic_move(src, dst):
            return dst

    return None


def run_command(cmdline: str, log_file: Path | None, use_shell: bool, cwd: str | None) -> int:
    """
    Executa o comando e retorna o return code.
    - Se log_file != None: grava stdout+stderr no arquivo de log.
    - use_shell:
        False (recomendado): executa via shlex.split (mais seguro)
        True: executa com shell=True (use apenas se realmente precisar de expansão de shell)
    - cwd: diretório de trabalho opcional para o processo filho
    """
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)

        with log_file.open("w", encoding="utf-8", errors="ignore") as f:
            f.write(f"CMD: {cmdline}\n\n")
            f.flush()

            if use_shell:
                p = subprocess.run(
                    cmdline,
                    shell=True,
                    cwd=cwd,
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            else:
                args = shlex.split(cmdline)
                p = subprocess.run(
                    args,
                    shell=False,
                    cwd=cwd,
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    text=True,
                )

            f.write(f"\n\nRETURN_CODE: {p.returncode}\n")
            return p.returncode

    # Sem log em arquivo (imprime direto no terminal)
    if use_shell:
        p = subprocess.run(cmdline, shell=True, cwd=cwd)
    else:
        args = shlex.split(cmdline)
        p = subprocess.run(args, shell=False, cwd=cwd)

    return p.returncode


def worker_loop(
    wid: int,
    tasks_dir: Path,
    running_dir: Path,
    finished_dir: Path,
    failed_dir: Path | None,
    logs_dir: Path | None,
    poll: float,
    post_move_delay: float,
    idle_timeout: float,
    jitter: float,
    use_shell: bool,
    cwd: str | None,
):
    """
    Loop principal de um worker.

    Parâmetros importantes:
    - poll: intervalo base (segundos) para checar novas tarefas quando não há nada.
    - jitter: ruído aleatório somado ao poll para evitar "thundering herd"
      (todos os workers acordando ao mesmo tempo e batendo no FS).
    - post_move_delay: delay após mover a tarefa para running
      (você comentou que mover instantâneo demais pode congestionar no servidor/FS).
    - idle_timeout: se ficar ocioso por N segundos sem achar tarefa, o worker encerra.
      (use 0 para "nunca encerrar por ociosidade".)
    """
    running_dir.mkdir(parents=True, exist_ok=True)
    finished_dir.mkdir(parents=True, exist_ok=True)
    if failed_dir:
        failed_dir.mkdir(parents=True, exist_ok=True)
    if logs_dir:
        logs_dir.mkdir(parents=True, exist_ok=True)

    idle_start = time.monotonic()

    while True:
        # 1) Tenta pegar uma tarefa
        task_path = claim_one_task(tasks_dir, running_dir)

        # 2) Se não pegou, entra em modo ocioso
        if task_path is None:
            if idle_timeout > 0 and (time.monotonic() - idle_start) >= idle_timeout:
                print(f"[worker {wid}] idle-timeout atingido, encerrando.")
                return
            time.sleep(poll + random.uniform(0, jitter))
            continue

        # Encontrou tarefa => reseta contador de ociosidade
        idle_start = time.monotonic()

        # 3) Delay opcional para evitar "martelar" o FS
        if post_move_delay > 0:
            time.sleep(post_move_delay)

        # 4) Lê o comando dentro do arquivo de tarefa
        cmd = read_first_nonempty_line(task_path)

        # Se o arquivo está vazio/corrompido, marca como falha (ou finished se não tiver failed_dir)
        if not cmd:
            target = (failed_dir or finished_dir) / task_path.name
            atomic_move(task_path, target)
            print(f"[worker {wid}] tarefa vazia: {task_path.name} -> {target.name}")
            continue

        # 5) Executa o comando
        log_file = (logs_dir / f"{task_path.stem}.log") if logs_dir else None
        print(f"[worker {wid}] executando: {task_path.name}")
        rc = run_command(cmd, log_file, use_shell=use_shell, cwd=cwd)

        # 6) Move marcador para finished ou failed
        if rc == 0:
            target = finished_dir / task_path.name
        else:
            target = (failed_dir or finished_dir) / task_path.name

        atomic_move(task_path, target)
        print(f"[worker {wid}] finalizado rc={rc}: {task_path.name} -> {target.name}")


def main():
    """
    Parseia argumentos de linha de comando e inicia 1 ou N workers.
    """
    ap = argparse.ArgumentParser(description="Runner paralelo baseado em diretórios (a_tasks/b_running/c_finished).")

    # Diretórios principais (fila por arquivos)
    ap.add_argument("--tasks", required=True, help="Diretório com tarefas pendentes (ex.: /home/oscar/a_tasks)")
    ap.add_argument("--running", required=True, help="Diretório para tarefas em execução (ex.: b_running)")
    ap.add_argument("--finished", required=True, help="Diretório para tarefas finalizadas (ex.: c_finished)")

    # Opcionais
    ap.add_argument("--failed", default=None, help="Diretório para tarefas com erro (ex.: d_failed)")
    ap.add_argument("--logs", default=None, help="Diretório para logs por tarefa (stdout/stderr)")

    # Concorrência
    ap.add_argument("--workers", type=int, default=1, help="Quantidade de workers paralelos")

    # Controle de polling e delays
    ap.add_argument("--poll", type=float, default=1.0, help="Intervalo de polling (segundos) quando não há tarefas")
    ap.add_argument("--post-move-delay", type=float, default=0.2, help="Delay após mover a tarefa para running")
    ap.add_argument("--idle-timeout", type=float, default=1800.0, help="Encerra após N segundos ocioso (0 = nunca)")
    ap.add_argument("--jitter", type=float, default=0.2, help="Jitter aleatório somado ao poll")

    # Execução do comando
    ap.add_argument("--shell", action="store_true", help="Executa com shell=True (use só se necessário)")
    ap.add_argument("--cwd", default=None, help="Diretório de trabalho opcional para executar os comandos")

    args = ap.parse_args()

    tasks_dir = Path(args.tasks)
    running_dir = Path(args.running)
    finished_dir = Path(args.finished)
    failed_dir = Path(args.failed) if args.failed else None
    logs_dir = Path(args.logs) if args.logs else None

    # Caso simples: 1 worker no processo principal
    if args.workers <= 1:
        worker_loop(
            wid=0,
            tasks_dir=tasks_dir,
            running_dir=running_dir,
            finished_dir=finished_dir,
            failed_dir=failed_dir,
            logs_dir=logs_dir,
            poll=args.poll,
            post_move_delay=args.post_move_delay,
            idle_timeout=args.idle_timeout,
            jitter=args.jitter,
            use_shell=args.shell,
            cwd=args.cwd,
        )
        return

    # Modo paralelo: cria N processos
    procs: list[Process] = []
    for wid in range(args.workers):
        p = Process(
            target=worker_loop,
            args=(
                wid,
                tasks_dir,
                running_dir,
                finished_dir,
                failed_dir,
                logs_dir,
                args.poll,
                args.post_move_delay,
                args.idle_timeout,
                args.jitter,
                args.shell,
                args.cwd,
            ),
            daemon=False,
        )
        p.start()
        procs.append(p)

        # Pequeno espaçamento para reduzir pico de acessos ao FS no start
        time.sleep(0.1)

    # Aguarda todos os workers terminarem
    for p in procs:
        p.join()


if __name__ == "__main__":
    main()
