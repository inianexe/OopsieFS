#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
COMMAND_PATH="$BIN_DIR/oopsiefs"
FUSE_COMMAND_PATH="$BIN_DIR/oopsiefs-fuse"
DESKTOP_FILE="$DESKTOP_DIR/oopsiefs.desktop"

mkdir -p "$BIN_DIR" "$DESKTOP_DIR"
chmod +x "$APP_DIR/run_oopsiefs.sh" "$APP_DIR/run_oopsiefs_fuse.sh"

cat > "$COMMAND_PATH" <<EOF
#!/usr/bin/env bash
exec "$APP_DIR/run_oopsiefs.sh" "\$@"
EOF
chmod +x "$COMMAND_PATH"

cat > "$FUSE_COMMAND_PATH" <<EOF
#!/usr/bin/env bash
exec "$APP_DIR/run_oopsiefs_fuse.sh" "\$@"
EOF
chmod +x "$FUSE_COMMAND_PATH"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=OopsieFS
Comment=Undoable file history and local file transfer
Exec=$COMMAND_PATH
Path=$APP_DIR
Terminal=false
Categories=Utility;FileTools;
StartupNotify=true
EOF

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
fi

echo "OopsieFS installed."
echo "Run it from your app launcher, or from a terminal with:"
echo "  oopsiefs"
echo
echo "Optional FUSE portal mount command:"
echo "  oopsiefs-fuse"
echo
echo "If 'oopsiefs' is not found, add this to your shell profile:"
echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
