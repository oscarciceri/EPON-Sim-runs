#!/bin/bash
# execute_simulation.sh
# =====================
# Script para iniciar o runner.py com N workers.
# Ajuste os caminhos e o número de workers conforme seu servidor.

set -euo pipefail

# Vai para o diretório do script (garante paths relativos consistentes)
WORKDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$WORKDIR"

# -----------------------------------------------------------------------------
# CONFIGURAÇÃO DE DIRETÓRIOS
# -----------------------------------------------------------------------------
# TASKS_DIR: diretório onde ficam os arquivos de tarefa pendentes (gerados pelo seu generator)
# OBS: em geral você comentou que usa algo como /home/oscar/a_tasks
TASKS_DIR="/home/oscar/a_tasks"

# Diretórios locais do projeto para controlar o estado das tarefas
RUNNING_DIR="$WORKDIR/b_running"
FINISHED_DIR="$WORKDIR/c_finished"
FAILED_DIR="$WORKDIR/d_failed"

# Diretório opcional de logs (um log por tarefa)
LOG_DIR="$WORKDIR/logs"

# -----------------------------------------------------------------------------
# CONFIGURAÇÃO DE PARALELISMO
# -----------------------------------------------------------------------------
# Quantidade de workers (idealmente próximo ao número de cores/threads úteis,
# mas lembre que o gargalo pode ser I/O / JVM / disco / NFS)
NUM_WORKERS=2

# -----------------------------------------------------------------------------
# CONTROLE DE POLLING / DELAYS
# -----------------------------------------------------------------------------
# poll: intervalo de checagem quando não há tarefas
# post-move-delay: delay após mover arquivo para running (para não congestionar FS)
# idle-timeout: encerra runner após ficar ocioso X segundos (0 = nunca encerra)
POLL=1.0
POST_MOVE_DELAY=0.2
IDLE_TIMEOUT=1800

# -----------------------------------------------------------------------------
# EXECUÇÃO
# -----------------------------------------------------------------------------
python3 runner.py \
  --tasks "$TASKS_DIR" \
  --running "$RUNNING_DIR" \
  --finished "$FINISHED_DIR" \
  --failed "$FAILED_DIR" \
  --logs "$LOG_DIR" \
  --workers "$NUM_WORKERS" \
  --poll "$POLL" \
  --post-move-delay "$POST_MOVE_DELAY" \
  --idle-timeout "$IDLE_TIMEOUT"
