#!/bin/bash
# Выкатить закоммиченный код «Схем границ» на pi5 и пересобрать контейнер.
#   scripts/deploy-pi5.sh
# compose-файл и метки доступа лежат в my_pi5-server (stack/boundary);
# его scripts/deploy.sh делает сам `docker compose up --build`.
# Выкатывается только закоммиченное (git archive HEAD); .env и data/ на Pi сохраняются.
set -euo pipefail
cd "$(dirname "$0")/.."
pi5_repo=${PI5_SERVER_REPO:-../my_pi5-server}
[ -x "$pi5_repo/scripts/deploy.sh" ] || { echo "my_pi5-server не найден в $pi5_repo"; exit 1; }
[ -z "$(git status --porcelain)" ] || echo "внимание: незакоммиченные изменения не выкатываются" >&2
echo "выкатываю $(git rev-parse --short HEAD)"

git archive --format=tar HEAD | ssh pi5 'set -e
  sudo install -d -o $USER -g $USER /opt/pi5 /opt/pi5/boundary
  cd /opt/pi5/boundary
  rm -rf src.new && mkdir src.new && tar xf - -C src.new
  rm -rf src && mv src.new src'

"$pi5_repo/scripts/deploy.sh" boundary
