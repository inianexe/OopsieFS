#!/usr/bin/env bash
set -euo pipefail

rm -f "$HOME/.local/bin/oopsiefs"
rm -f "$HOME/.local/bin/oopsiefs-fuse"
rm -f "$HOME/.local/share/applications/oopsiefs.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
fi

echo "OopsieFS launcher removed."
echo "Metadata is preserved at ~/.local/share/oopsiefs."
