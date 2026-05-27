#!/usr/bin/env bash
# Initialise sops+age encrypted secrets for IRA
# Run once on a new machine: bash scripts/init-secrets.sh
set -euo pipefail

KEYS_DIR="${HOME}/.config/sops/age"
KEY_FILE="${KEYS_DIR}/keys.txt"

echo "=== IRA Secrets Initialisation ==="

# Install age if not present
if ! command -v age-keygen &>/dev/null; then
    echo "Installing age..."
    if command -v brew &>/dev/null; then
        brew install age
    elif command -v apt-get &>/dev/null; then
        sudo apt-get install -y age
    else
        echo "ERROR: Please install age manually: https://github.com/FiloSottile/age/releases"
        exit 1
    fi
fi

# Install sops if not present
if ! command -v sops &>/dev/null; then
    echo "Installing sops..."
    if command -v brew &>/dev/null; then
        brew install sops
    elif command -v apt-get &>/dev/null; then
        SOPS_VERSION="3.9.1"
        wget -q "https://github.com/getsops/sops/releases/download/v${SOPS_VERSION}/sops-v${SOPS_VERSION}.linux.amd64" -O /tmp/sops
        sudo install /tmp/sops /usr/local/bin/sops
    else
        echo "ERROR: Please install sops manually: https://github.com/getsops/sops/releases"
        exit 1
    fi
fi

# Generate age key if not already present
if [ ! -f "${KEY_FILE}" ]; then
    mkdir -p "${KEYS_DIR}"
    chmod 700 "${KEYS_DIR}"
    age-keygen -o "${KEY_FILE}"
    chmod 600 "${KEY_FILE}"
    echo "✅ Age key generated at ${KEY_FILE}"
    echo ""
    echo "⚠️  BACK UP THIS FILE NOW:"
    echo "   cp ${KEY_FILE} ~/your-secure-backup-location/"
    echo ""
else
    echo "✅ Age key already exists at ${KEY_FILE}"
fi

# Extract public key
PUBLIC_KEY=$(grep "public key:" "${KEY_FILE}" | awk '{print $NF}')
echo "Your age public key: ${PUBLIC_KEY}"

# Create .sops.yaml if not present
SOPS_CONFIG="$(dirname "${BASH_SOURCE[0]}")/../.sops.yaml"
if [ ! -f "${SOPS_CONFIG}" ]; then
    cat > "${SOPS_CONFIG}" << EOF
creation_rules:
  - path_regex: \.env\.enc$
    age: ${PUBLIC_KEY}
  - path_regex: secrets/.*\.yaml$
    age: ${PUBLIC_KEY}
EOF
    echo "✅ Created .sops.yaml with your public key"
fi

echo ""
echo "=== Next steps ==="
echo "1. Copy .env.example to .env and fill in your secrets"
echo "2. Run: sops -e .env > .env.enc"
echo "3. Run: git add .env.enc .sops.yaml && git commit -m 'secrets: add encrypted env'"
echo "4. NEVER commit the plaintext .env file"
echo ""
echo "To decrypt on a new machine:"
echo "  export SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt"
echo "  sops -d .env.enc > .env"
