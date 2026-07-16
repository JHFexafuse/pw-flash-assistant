#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -eq 0 ]]; then
    echo "Bitte nicht als root starten. Das Tool fragt nur bei Bedarf nach sudo."
    exit 1
fi

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
mkdir -p "${BIN_DIR}"
chmod +x "${ROOT_DIR}/pwflash.sh" "${ROOT_DIR}/pwflash.py"
ln -sfn "${ROOT_DIR}/pwflash.sh" "${BIN_DIR}/pwflash"

case ":${PATH}:" in
    *":${BIN_DIR}:"*) ;;
    *)
        echo
        echo "Hinweis: ${BIN_DIR} ist noch nicht in PATH."
        echo "Neu anmelden oder folgenden Eintrag zur Shell-Konfiguration hinzufügen:"
        echo "export PATH=\"\$HOME/.local/bin:\$PATH\""
        ;;
esac

echo
echo "PrintWars Flash Assistant wurde installiert."
echo "Start: ${BIN_DIR}/pwflash"
