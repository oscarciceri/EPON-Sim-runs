#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
runner.py
=========
Orquestrador de simulações por arquivos (fila baseada em diretórios), feito para substituir
o run.cpp antigo.

Ideia geral:
- Você tem um diretório com tarefas pendentes (ex.: /home/oscar/a_tasks).
- Cada tarefa é um arquivo de texto cujo conteúdo (primeira linha não vazia) é um comando a executar
  (normalmente: java -jar EPON-Sim.jar ...).
- Vários workers rodam em paralelo. Cada worker:
  1) "pega" (claim) uma tarefa movendo-a de forma atômica de a_tasks -> b_running
  2) executa o comando
  3) ao terminar, move o arquivo marcador para c_finished (ou d_failed se falhar)
  4) opcionalmente grava um log por tarefa (stdout + stderr)

Por que isso é melhor que o run.cpp antigo?
- Evita condição de corrida (dois processos pegando a mesma tarefa).
- Evita arquivo intermediário compartilhado (tipo primerArchivo.txt).
- Reduz overhead de system("ls/head/mv") em loop.
- Permite logs por tarefa e controle melhor de ociosidade.

Melhoria adicionada agora:
- Para cada tarefa, imprime:
    * horário de início (inicio_ts)
    * horário de término (fim_ts)
    * duração em segundos (duracao_s)
- Também grava essas informações no arquivo de log (se --logs for usado).

Nota sobre tempo:
- Para "hora" (timestamp legível) usamos datetime.now().
- Para "duração" usamos time.monotonic() (correto para medir tempo decorrido, não sofre ajuste do relógio).
"""

import argparse
import os
import time
import shlex
import random
import subprocess
from pathlib import Path
from multiprocessing import Process
from typing import Optional, List
from datetime import datetime


def now_str() -> str:
    """
    Retorna a data/hora local como string legível.
    Ex.: 2026-02-16 14:03:22
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_first_nonempty_line(p: Path) -> str:
    """
    Lê o arquivo de tarefa e retorna a primeira linha não vazia.
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
    Isso é crucial para evitar corrida entre workers: só 1 worker consegue mover (claimar) a tarefa.

    Por que o move é importante?
    - O "claim" da tarefa é, na prática, "eu consegui mover o arquivo de a_tasks para b_running".
    - Se 2 workers tentarem pegar o mesmo arquivo, só 1 vai conseguir mover. O outro falha e tenta outro.

    Retorna True se moveu, False se não conseguiu.
    """
    try:
        # rename() tende a ser atômico no mesmo filesystem
        src.rename(dst)
        return True
    except FileNotFoundError:
        # Outro worker pode ter movido antes (tarefa já "sumiu")
        return False
    except OSError:
        # Fallback: os.replace também substitui se existir
        # (também costuma ser atômico no mesmo filesystem)
        try:
            os.replace(str(src), str(dst))
            return True
        except Exception:
            return False


def claim_one_task(tasks_dir: Path, running_dir: Path) -> Optional[Path]:
    """
    Tenta "pegar" uma tarefa pendente.

    Implementação:
    - Lista arquivos em tasks_dir (ordenado para previsibilidade).
    - Tenta mover cada arquivo para running_dir.
    - O primeiro move que der certo define a tarefa "claimada".

    Se não houver tarefa ou se outras instâncias ganharem a corrida, retorna None.
    """
    try:
        # Aqui pegamos "qualquer arquivo" (como no seu original).
        # Se você quiser ignorar .swp/.tmp/dotfiles, dá para filtrar aqui.
        entries = sorted([p for p in tasks_dir.iterdir() if p.is_file()])
    except FileNotFoundError:
        return None

    for src in entries:
        dst = running_dir / src.name
        if atomic_move(src, dst):
            return dst

    return None


def append_timing_to_log(log_file: Path, start_ts: str, end_ts: str, duration_s: float) -> None:
    """
    Acrescenta informações de tempo no final do log da tarefa.
    Faz append para não interferir com o stdout/stderr capturado.
    """
    try:
        with log_file.open("a", encoding="utf-8", errors="ignore") as f:
            f.write("\nSTART_TS: {}\n".format(start_ts))
            f.write("END_TS: {}\n".format(end_ts))
            f.write("DURATION_S: {:.3f}\n".format(duration_s))
    except Exception:
        # Se falhar, não derruba o worker
        pass


def run_command(cmdline: str, log_file: Optional[Path], use_shell: bool, cwd: Optional[str]) -> int:
    """
    Executa o comando e retorna o return code (rc).

    - Se log_file != None: grava stdout+stderr no arquivo de log.
      Isso é essencial em simulações longas, pois você consegue auditar depois.

    - use_shell:
        False (recomendado): executa via shlex.split (mais seguro).
        True: executa com shell=True (use apenas se realmente precisar de features do shell).

    - cwd: diretório de trabalho opcional para o processo filho
           (ex.: se o comando depende de paths relativos).
    """
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("w", encoding="utf-8", errors="ignore") as f:
            # Cabeçalho do log (o resto do output vem do comando)
            f.write("CMD: {}\n\n".format(cmdline))
            f.flush()

            if use_shell:
                p = subprocess.run(
                    cmdline,
                    shell=True,
                    cwd=cwd,
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    text=True,  # Python 3.7+ ok
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

            # rc do processo (sucesso geralmente é 0)
            f.write("\n\nRETURN_CODE: {}\n".format(p.returncode))
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
    failed_dir: Optional[Path],
    logs_dir: Optional[Path],
    poll: float,
    post_move_delay: float,
    idle_timeout: float,
    jitter: float,
    use_shell: bool,
    cwd: Optional[str],
) -> None:
    """
    Loop principal de um worker.

    Parâmetros importantes:
    - poll: intervalo base (segundos) para checar novas tarefas quando não há nada.
    - jitter: ruído aleatório somado ao poll para evitar "thundering herd"
      (todos os workers acordando ao mesmo tempo e batendo no filesystem).
    - post_move_delay: delay após mover a tarefa para running (reduz pico de I/O no FS).
    - idle_timeout: se ficar ocioso por N segundos sem achar tarefa, o worker encerra.
      (use 0 para "nunca encerrar por ociosidade".)
    """
    running_dir.mkdir(parents=True, exist_ok=True)
    finished_dir.mkdir(parents=True, exist_ok=True)
    if failed_dir is not None:
        failed_dir.mkdir(parents=True, exist_ok=True)
    if logs_dir is not None:
        logs_dir.mkdir(parents=True, exist_ok=True)

    # Marca o início do período ocioso. Se ficar muito tempo sem tarefas, encerra.
    idle_start = time.monotonic()

    while True:
        # 1) Tenta pegar uma tarefa (claim atômico via move)
        task_path = claim_one_task(tasks_dir, running_dir)

        # 2) Se não pegou, entra em modo ocioso
        if task_path is None:
            if idle_timeout > 0 and (time.monotonic() - idle_start) >= idle_timeout:
                print("[worker {}] idle-timeout atingido, encerrando.".format(wid), flush=True)
                return
            time.sleep(poll + random.uniform(0, jitter))
            continue

        # Encontrou tarefa => reseta contador de ociosidade
        idle_start = time.monotonic()

        # 3) Delay opcional para evitar "martelar" o filesystem
        if post_move_delay > 0:
            time.sleep(post_move_delay)

        # 4) Lê o comando dentro do arquivo de tarefa
        cmd = read_first_nonempty_line(task_path)

        # Se o arquivo está vazio/corrompido, marca como falha (ou finished se não tiver failed_dir)
        if not cmd:
            target_dir = failed_dir if failed_dir is not None else finished_dir
            target = target_dir / task_path.name
            atomic_move(task_path, target)
            print("[worker {}] tarefa vazia: {} -> {}".format(wid, task_path.name, target.name), flush=True)
            continue

        # 5) Executa o comando + mede tempo
        # - log_file: um log por tarefa (mesmo nome do arquivo + .log)
        log_file = (logs_dir / "{}.log".format(task_path.stem)) if logs_dir is not None else None

        # Timestamp humano (para print/log)
        inicio_ts = now_str()
        # Timer monotônico para medir duração real (não depende de relógio do sistema)
        t0 = time.monotonic()

        print("[worker {}] inicio {} | executando: {}".format(wid, inicio_ts, task_path.name), flush=True)

        rc = run_command(cmd, log_file, use_shell=use_shell, cwd=cwd)

        t1 = time.monotonic()
        fim_ts = now_str()
        duracao_s = t1 - t0

        # 6) Move marcador para finished ou failed (de acordo com rc)
        if rc == 0:
            target_dir = finished_dir
            target = finished_dir / task_path.name
        else:
            target_dir = failed_dir if failed_dir is not None else finished_dir
            target = target_dir / task_path.name

        atomic_move(task_path, target)

        # Escreve timing no log (se existir)
        if log_file is not None:
            append_timing_to_log(log_file, inicio_ts, fim_ts, duracao_s)

        # Print final com pasta destino + tempo
        print(
            "[worker {}] fim {} | duracao {:.2f}s | rc={} | {} -> {}/{}".format(
                wid, fim_ts, duracao_s, rc, task_path.name, target_dir.name, target.name
            ),
            flush=True,
        )


def main() -> None:
    """
    Parseia argumentos de linha de comando e inicia 1 ou N workers.

    Exemplo típico:
      python3 runner.py --tasks /home/oscar/a_tasks --running b_running --finished c_finished \
        --failed d_failed --logs logs --workers 8 --poll 1 --post-move-delay 0.2 --idle-timeout 0
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
    procs: List[Process] = []
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
