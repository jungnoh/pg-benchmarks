#!/bin/bash
# HammerDB Installation Script
# Downloads and installs HammerDB for CLI usage

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
HAMMERDB_VERSION="${HAMMERDB_VERSION:-4.10}"

# Detect OS and architecture
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Linux)
        PLATFORM="Linux"
        ;;
    Darwin)
        PLATFORM="macos"
        ;;
    *)
        echo "Unsupported OS: $OS"
        exit 1
        ;;
esac

case "$ARCH" in
    x86_64|amd64)
        ARCH_SUFFIX="x86-64"
        ;;
    arm64|aarch64)
        ARCH_SUFFIX="arm64"
        ;;
    *)
        echo "Unsupported architecture: $ARCH"
        exit 1
        ;;
esac

# HammerDB download URL
if [ "$PLATFORM" = "Linux" ]; then
    FILENAME="HammerDB-${HAMMERDB_VERSION}-Linux.tar.gz"
    DOWNLOAD_URL="https://github.com/TPC-Council/HammerDB/releases/download/v${HAMMERDB_VERSION}/${FILENAME}"
else
    FILENAME="HammerDB-${HAMMERDB_VERSION}-macOS.tar.gz"
    DOWNLOAD_URL="https://github.com/TPC-Council/HammerDB/releases/download/v${HAMMERDB_VERSION}/${FILENAME}"
fi

INSTALL_DIR="${BASE_DIR}/HammerDB-${HAMMERDB_VERSION}"

echo "=== HammerDB Installation ==="
echo "Version: ${HAMMERDB_VERSION}"
echo "Platform: ${PLATFORM}"
echo "Download URL: ${DOWNLOAD_URL}"
echo "Install directory: ${INSTALL_DIR}"
echo ""

# Check if already installed
if [ -d "$INSTALL_DIR" ]; then
    echo "HammerDB ${HAMMERDB_VERSION} is already installed at ${INSTALL_DIR}"
    echo "To reinstall, remove the directory first: rm -rf ${INSTALL_DIR}"
    exit 0
fi

# Create temp directory for download
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

echo "Downloading HammerDB..."
cd "$TEMP_DIR"

if command -v curl &> /dev/null; then
    curl -L -o "$FILENAME" "$DOWNLOAD_URL"
elif command -v wget &> /dev/null; then
    wget -O "$FILENAME" "$DOWNLOAD_URL"
else
    echo "Error: Neither curl nor wget found. Please install one of them."
    exit 1
fi

echo "Extracting HammerDB..."
tar -xzf "$FILENAME" -C "$BASE_DIR"

# Verify installation
if [ -f "${INSTALL_DIR}/hammerdbcli" ]; then
    echo ""
    echo "=== Installation Complete ==="
    echo "HammerDB installed at: ${INSTALL_DIR}"
    echo ""
    echo "Creating symlink..."
    ln -sf "${INSTALL_DIR}" "${BASE_DIR}/hammerdb"
    echo "Symlink created: ${BASE_DIR}/hammerdb -> ${INSTALL_DIR}"
    echo ""
    echo "Test with: ${BASE_DIR}/hammerdb/hammerdbcli"
else
    echo "Error: Installation verification failed"
    exit 1
fi
