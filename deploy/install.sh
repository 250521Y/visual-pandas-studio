#!/usr/bin/env bash
# Run after uploading this project to /var/www/visual-pandas-studio.
set -euo pipefail
domain=""
email=""
http_only=0
while (($#)); do
  case "$1" in
    --domain) domain="${2:?Missing domain}"; shift 2 ;;
    --email) email="${2:?Missing certificate contact email}"; shift 2 ;;
    --http-only) http_only=1; shift ;;
    *) echo "Usage: sudo bash deploy/install.sh --domain DOMAIN --email EMAIL [--http-only]" >&2; exit 2 ;;
  esac
done
[[ $EUID == 0 ]] || { echo "Run with sudo." >&2; exit 2; }
[[ "$domain" =~ ^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$ && "$domain" == *.* ]] || { echo "Provide a valid domain name." >&2; exit 2; }
if (( !http_only )); then
  [[ "$email" == *@*.* && "$email" != *' '* ]] || { echo "Provide a certificate contact email, or use --http-only." >&2; exit 2; }
fi
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
[[ "$root" == /var/www/visual-pandas-studio ]] || { echo "Upload the project to /var/www/visual-pandas-studio first." >&2; exit 2; }
[[ -s "$root/frontend/dist/index.html" && -s "$root/backend/app/main.py" ]] || { echo "Built frontend or backend source is missing." >&2; exit 2; }
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx
python3 -m venv "$root/backend/.venv"
"$root/backend/.venv/bin/python" -m pip install -r "$root/backend/requirements.txt"
(cd "$root/backend" && .venv/bin/python -m pytest tests -q)
install -d -o www-data -g www-data -m 700 /var/lib/visual-pandas-studio
stamp="$(date +%Y%m%d-%H%M%S)"
for item in /etc/visual-pandas-studio.env /etc/nginx/conf.d/visual-pandas-studio.conf /etc/systemd/system/visual-pandas-studio.service; do
  if [[ -f "$item" ]]; then cp -p -- "$item" "$item.$stamp.bak"; fi
done
if [[ ! -f /etc/visual-pandas-studio.env ]]; then
  install -m 600 "$root/deploy/server.env.example" /etc/visual-pandas-studio.env
fi
# Preserve existing limits and data-directory settings; update only this site's origin.
python3 - "$domain" "$root" <<'PY'
from pathlib import Path
import sys
domain,root=sys.argv[1:]
env=Path('/etc/visual-pandas-studio.env')
lines=env.read_text().splitlines()
value='VPS_CORS_ORIGINS=https://'+domain+',http://'+domain
lines=[value if line.startswith('VPS_CORS_ORIGINS=') else line for line in lines]
if not any(line.startswith('VPS_CORS_ORIGINS=') for line in lines):lines.append(value)
env.write_text('\n'.join(lines)+'\n')
config=(Path(root)/'deploy/nginx.conf').read_text().replace('analysis.example.com',domain)
Path('/etc/nginx/conf.d/visual-pandas-studio.conf').write_text(config)
PY
install -m 644 "$root/deploy/visual-pandas-studio.service" /etc/systemd/system/visual-pandas-studio.service
nginx -t
systemctl daemon-reload
systemctl enable --now visual-pandas-studio
systemctl restart visual-pandas-studio
systemctl reload nginx
for attempt in $(seq 1 40); do
  if curl --fail --silent http://127.0.0.1:8000/api/health; then break; fi
  sleep .5
done
curl --fail --silent http://127.0.0.1:8000/api/health >/dev/null
if ((http_only)); then
  echo "HTTP service ready. HTTPS and public verification still required."
else
  certbot --nginx --non-interactive --agree-tos --redirect --email "$email" -d "$domain"
  certbot renew --dry-run
  "$root/backend/.venv/bin/python" "$root/deploy/verify_http.py" "https://$domain" --require-https --output "$root/artifacts/public-verification.json"
  echo "HTTPS and production smoke checks passed: https://$domain"
fi
