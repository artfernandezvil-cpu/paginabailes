#!/bin/bash
cd -- "$(dirname -- "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  python3 launch.py
else
  echo "Instala Python 3.11 o superior desde https://www.python.org/downloads/ y abre este archivo nuevamente."
fi
read -r -p "Presiona Enter para cerrar esta ventana."
