#!/usr/bin/env bash
# Shows the document archive as "Smart Inventory Documents" instead of the upstream product
# name: sign-in pages, browser tab, web app texts and logo. Runs as root each time the
# archive container starts (mounted into /custom-cont-init.d). Idempotent; changes only
# display text inside the container, never documents or data.
set -u
NAME="${PAPERLESS_APP_TITLE:-Smart Inventory Documents}"
SRC=/usr/src/paperless

rebrand() {
  sed -i \
    -e 's/by Paperless-ngx//g' \
    -e 's/Thanks for being a part of the Paperless-ngx community!/Approved supplier invoices from Smart Inventory are filed here automatically./g' \
    -e "s/Paperless-ngx/${NAME}/g" \
    -e 's/Paperless will only/The archive will only/g' \
    -e 's/outside Paperless\./outside the archive./g' \
    "$@"
}

# Server-rendered pages (sign-in, password reset, e-mails).
find "$SRC/src/documents/templates" -type f \( -name '*.html' -o -name '*.txt' \) \
  -exec grep -l 'Paperless-ngx' {} + 2>/dev/null | while read -r f; do rebrand "$f"; done

# The web app (every language). Pre-compressed copies are removed so the edited files are served.
for f in "$SRC"/static/frontend/*/index.html "$SRC"/static/frontend/*/main.js \
         "$SRC"/static/frontend/*/manifest.webmanifest; do
  [ -f "$f" ] || continue
  if grep -q 'Paperless' "$f"; then
    rebrand "$f"
    rm -f "$f.gz" "$f.br"
  fi
done

# Smart Inventory logo (used when PAPERLESS_APP_LOGO=/logo/smart-inventory.png) and app icons.
mkdir -p "$SRC/media/logo"
cp /brand/logo.png "$SRC/media/logo/smart-inventory.png"
chown -R "${USERMAP_UID:-1000}:${USERMAP_GID:-1000}" "$SRC/media/logo"
for d in "$SRC"/static/frontend/*/; do
  for icon in icon-192.png icon-512.png icon-512-maskable.png apple-touch-icon.png; do
    [ -f "$d$icon" ] && cp /brand/logo.png "$d$icon" && rm -f "$d$icon.gz" "$d$icon.br"
  done
done
echo "[smart-inventory] archive shown as: ${NAME}"
