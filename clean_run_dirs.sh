#!/usr/bin/env bash
set -euo pipefail

# Ejecutar desde la raíz del repo (donde están a_tasks/, b_running/, resultados/, etc.)
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# Carpetas base a limpiar
BASE_DIRS=("a_tasks" "b_running" "c_finished" "logs")

# Construye lista final de carpetas a limpiar:
# - BASE_DIRS
# - cada subcarpeta inmediata dentro de resultados/
TARGET_DIRS=()

for d in "${BASE_DIRS[@]}"; do
  TARGET_DIRS+=("$d")
done

if [[ -d "resultados" ]]; then
  # Solo subcarpetas de primer nivel dentro de resultados/
  while IFS= read -r dir; do
    TARGET_DIRS+=("$dir")
  done < <(find "resultados" -mindepth 1 -maxdepth 1 -type d | sort)
fi

count_items() {
  local dir="$1"
  # Cuenta archivos regulares y symlinks (no directorios).
  find "$dir" -mindepth 1 \( -type f -o -type l \) 2>/dev/null | wc -l | tr -d ' '
}

delete_items() {
  local dir="$1"
  # Borra archivos y symlinks de forma recursiva, preservando directorios.
  find "$dir" -mindepth 1 \( -type f -o -type l \) -print -delete 2>/dev/null
}

echo "== Limpieza interactiva (sin borrar carpetas) =="
echo "Directorio raíz: $ROOT"
echo

TOTAL_DELETED=0

for dir in "${TARGET_DIRS[@]}"; do
  if [[ ! -d "$dir" ]]; then
    echo "[SKIP] No existe: $dir"
    echo
    continue
  fi

  n="$(count_items "$dir")"
  echo "---------------------------------------------"
  echo "Carpeta: $dir"
  echo "Archivos (y symlinks) a borrar: $n"

  if [[ "$n" -eq 0 ]]; then
    echo "Nada que borrar."
    echo
    continue
  fi

  read -r -p "¿Deseas eliminar estos $n archivos en '$dir'? [y/N] " ans
  case "${ans,,}" in
    y|yes|s|si)
      echo "Borrando en: $dir"
      # Borrado + conteo real borrado (en caso de cambios entre conteo y borrado)
      deleted_now="$(delete_items "$dir" | wc -l | tr -d ' ')"
      echo "Eliminados: $deleted_now"
      TOTAL_DELETED=$((TOTAL_DELETED + deleted_now))
      ;;
    *)
      echo "No se borró nada en: $dir"
      ;;
  esac
  echo
done

echo "============================================="
echo "Limpieza finalizada. Total eliminados: $TOTAL_DELETED"
