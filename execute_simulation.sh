#!/bin/bash
# execute_simulation.sh
# =====================
# Objetivo:
# - Preparar ambiente (limpar swaps, garantir diretórios)
# - Definir parâmetros (paths, workers, polling)
# - Rodar o runner.py com logs/prints suficientes para ver onde "travou"
#
# Dica:
# - Se no servidor "parar" em algum ponto, você vai ver o último [STEP X] impresso.

set -Eeuo pipefail

# ----------------------------------------------------------------------
# (DEBUG) Funções auxiliares
# ----------------------------------------------------------------------

# Imprime mensagens com timestamp (hora) para facilitar rastrear travamentos.
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# Em caso de erro, imprime linha e comando que falhou.
trap 'log "ERRO na linha $LINENO (rc=$?) - comando: $BASH_COMMAND"' ERR

# Opcional: habilita "rastreamento" de cada comando executado.
# Se quiser MUITO detalhe, descomente a linha abaixo:
# set -x
# PS4='[TRACE $(date "+%Y-%m-%d %H:%M:%S")] ${BASH_SOURCE}:${LINENO}: '

log "[STEP 0] Iniciando script"

# ----------------------------------------------------------------------
# (STEP 1) Limpeza de arquivos temporários (.swp) do Vim
# ----------------------------------------------------------------------
# Isso evita o runner tentar pegar arquivos que não são tarefas.
# Em FS remoto (NFS), rm/ls podem demorar se houver muitos arquivos.
log "[STEP 1] Limpando swaps do Vim em /home/oscar/a_tasks (se existirem)"
rm -f /local1/oscar/EPON-Sim-runs/a_tasks/.*.swp \
      /local1/oscar/EPON-Sim-runs/a_tasks/*.swp \
      /local1/oscar/EPON-Sim-runs/a_tasks/*.swo \
      /local1/oscar/EPON-Sim-runs/a_tasks/*.swx || true
log "[STEP 1] OK (limpeza swaps finalizada)"

# ----------------------------------------------------------------------
# (STEP 2) Determinar WORKDIR e mudar para ele
# ----------------------------------------------------------------------
# Isso garante que paths relativos (b_running, c_finished, etc.) funcionem.
log "[STEP 2] Definindo WORKDIR e entrando nele"
WORKDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
log "[STEP 2] WORKDIR=$WORKDIR"
cd "$WORKDIR"
log "[STEP 2] OK (cd para WORKDIR feito)"

# ----------------------------------------------------------------------
# (STEP 3) Configuração de diretórios
# ----------------------------------------------------------------------
log "[STEP 3] Configurando diretórios da fila"

# TASKS_DIR: onde ficam as tarefas pendentes (geradas pelo seu generator)
TASKS_DIR="/local1/oscar/EPON-Sim-runs/a_tasks"

# Diretórios locais do projeto para controlar o estado das tarefas
RUNNING_DIR="$WORKDIR/b_running"
FINISHED_DIR="$WORKDIR/c_finished"
FAILED_DIR="$WORKDIR/d_failed"

# Diretório opcional de logs (um log por tarefa)
LOG_DIR="$WORKDIR/logs"

log "[STEP 3] TASKS_DIR   =$TASKS_DIR"
log "[STEP 3] RUNNING_DIR =$RUNNING_DIR"
log "[STEP 3] FINISHED_DIR=$FINISHED_DIR"
log "[STEP 3] FAILED_DIR  =$FAILED_DIR"
log "[STEP 3] LOG_DIR     =$LOG_DIR"

# Garante que as pastas locais existam (evita falhas por diretório inexistente).
log "[STEP 3] Garantindo que pastas locais existam (mkdir -p)"
mkdir -p "$RUNNING_DIR" "$FINISHED_DIR" "$FAILED_DIR" "$LOG_DIR"
log "[STEP 3] OK (diretórios preparados)"

# (Opcional) Checagens rápidas: se o servidor travar aqui, o problema é FS/permissão.
log "[STEP 3] Checando acesso ao TASKS_DIR"
if [[ ! -d "$TASKS_DIR" ]]; then
  log "AVISO: TASKS_DIR não existe: $TASKS_DIR"
fi
# Listagem pode ser lenta em NFS: por isso é opcional. Descomente se precisar:
# log "[STEP 3] ls -la TASKS_DIR (pode demorar em NFS)"
# ls -la "$TASKS_DIR" | head -n 5

# ----------------------------------------------------------------------
# (STEP 4) Configuração de paralelismo e parâmetros de polling
# ----------------------------------------------------------------------
log "[STEP 4] Configurando paralelismo e parâmetros"

NUM_WORKERS=20

POLL=1.0
POST_MOVE_DELAY=0.2
IDLE_TIMEOUT=120

log "[STEP 4] NUM_WORKERS=$NUM_WORKERS"
log "[STEP 4] POLL=$POLL"
log "[STEP 4] POST_MOVE_DELAY=$POST_MOVE_DELAY"
log "[STEP 4] IDLE_TIMEOUT=$IDLE_TIMEOUT"

# ----------------------------------------------------------------------
# (STEP 5) Informações de ambiente (útil para servidor)
# ----------------------------------------------------------------------
# Às vezes no servidor "python3" aponta para outro ambiente/versão.
log "[STEP 5] Verificando python3"
command -v python3 >/dev/null 2>&1 && log "[STEP 5] python3=$(command -v python3)" || log "[STEP 5] python3 NÃO encontrado"
python3 --version || true

# ----------------------------------------------------------------------
# (STEP 6) Execução do runner
# ----------------------------------------------------------------------
# Colocamos PYTHONUNBUFFERED=1 e -u para imprimir logs imediatamente na tela
# (senão o output pode ficar "bufferizado" e parecer travado).
log "[STEP 6] Iniciando runner.py"

PYTHONUNBUFFERED=1 python3 -u runner.py \
  --tasks "$TASKS_DIR" \
  --running "$RUNNING_DIR" \
  --finished "$FINISHED_DIR" \
  --failed "$FAILED_DIR" \
  --logs "$LOG_DIR" \
  --workers "$NUM_WORKERS" \
  --poll "$POLL" \
  --post-move-delay "$POST_MOVE_DELAY" \
  --idle-timeout "$IDLE_TIMEOUT"

# Se chegar aqui, o runner terminou (por idle-timeout ou porque você parou).
log "[STEP 6] runner.py finalizou (rc=$?)"

log "[STEP 7] Script finalizado com sucesso"

