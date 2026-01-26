#!/bin/bash
# HammerDB Installation Script
# Downloads and installs HammerDB for CLI usage
# Linux: Uses .deb package installer
# macOS: Uses tar.gz archive

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
HAMMERDB_VERSION="${HAMMERDB_VERSION:-4.10}"
UBUNTU_VERSION="${UBUNTU_VERSION:-24}"

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
        ARCH_SUFFIX="amd64"
        ;;
    arm64|aarch64)
        ARCH_SUFFIX="arm64"
        ;;
    *)
        echo "Unsupported architecture: $ARCH"
        exit 1
        ;;
esac

# HammerDB download URL and installation method
if [ "$PLATFORM" = "Linux" ]; then
    # Use .deb package for Linux (Ubuntu/Debian)
    FILENAME="hammerdb_${HAMMERDB_VERSION}-1.ubu${UBUNTU_VERSION}.${ARCH_SUFFIX}.deb"
    DOWNLOAD_URL="https://github.com/TPC-Council/HammerDB/releases/download/v${HAMMERDB_VERSION}/${FILENAME}"
    INSTALL_DIR="/usr/share/hammerdb-${HAMMERDB_VERSION}"
else
    # Use tar.gz for macOS
    FILENAME="HammerDB-${HAMMERDB_VERSION}-macOS.tar.gz"
    DOWNLOAD_URL="https://github.com/TPC-Council/HammerDB/releases/download/v${HAMMERDB_VERSION}/${FILENAME}"
    INSTALL_DIR="${BASE_DIR}/HammerDB-${HAMMERDB_VERSION}"
fi

echo "=== HammerDB Installation ==="
echo "Version: ${HAMMERDB_VERSION}"
echo "Platform: ${PLATFORM}"
echo "Download URL: ${DOWNLOAD_URL}"
if [ "$PLATFORM" = "Linux" ]; then
    echo "Ubuntu version: ${UBUNTU_VERSION}"
fi
echo "Install directory: ${INSTALL_DIR}"
echo ""

# Check if already installed
if [ "$PLATFORM" = "Linux" ]; then
    if dpkg -l hammerdb 2>/dev/null | grep -q "^ii"; then
        echo "HammerDB is already installed via package manager."
        echo "To reinstall, first remove with: sudo apt-get remove hammerdb"
        exit 0
    fi
else
    if [ -d "$INSTALL_DIR" ]; then
        echo "HammerDB ${HAMMERDB_VERSION} is already installed at ${INSTALL_DIR}"
        echo "To reinstall, remove the directory first: rm -rf ${INSTALL_DIR}"
        exit 0
    fi
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

if [ "$PLATFORM" = "Linux" ]; then
    echo "Installing HammerDB .deb package..."
    sudo apt-get install -f "./${FILENAME}"

    # Verify installation
    if command -v hammerdbcli &> /dev/null; then
        echo ""
        echo "=== Installation Complete ==="
        echo "HammerDB installed via package manager"
        echo ""
        echo "Creating symlink..."
        ln -sf "${INSTALL_DIR}" "${BASE_DIR}/hammerdb"
        echo "Symlink created: ${BASE_DIR}/hammerdb -> ${INSTALL_DIR}"
        echo ""
        echo "Test with: hammerdbcli"
    else
        echo "Error: Installation verification failed"
        exit 1
    fi
else
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
fi
