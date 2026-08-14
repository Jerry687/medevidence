#!/usr/bin/env bash
set -euo pipefail

readonly POWERSHELL_VERSION="7.6.4"
readonly LINUX_ARCHIVE="powershell-7.6.4-linux-x64.tar.gz"
readonly LINUX_SHA256="4471b5a36bfe86ec7af8525d36bb1cacba0128e7aac22d05cc064bc00e604721"
readonly WINDOWS_ARCHIVE="PowerShell-7.6.4-win-x64.zip"
readonly WINDOWS_SHA256="80832551c52809301e6071c8bac977beb5a2f1ec953eb4db9f94deb953333793"
readonly RELEASE_ROOT="https://github.com/PowerShell/PowerShell/releases/download/v${POWERSHELL_VERSION}"

: "${RUNNER_OS:?RUNNER_OS is required}"
: "${RUNNER_TEMP:?RUNNER_TEMP is required}"
: "${GITHUB_PATH:?GITHUB_PATH is required}"

case "${RUNNER_OS}" in
  Linux)
    archive_name="${LINUX_ARCHIVE}"
    archive_sha256="${LINUX_SHA256}"
    executable_name="pwsh"
    ;;
  Windows)
    archive_name="${WINDOWS_ARCHIVE}"
    archive_sha256="${WINDOWS_SHA256}"
    executable_name="pwsh.exe"
    ;;
  *)
    echo "Unsupported GitHub Actions runner OS: ${RUNNER_OS}" >&2
    exit 1
    ;;
esac

install_root="${RUNNER_TEMP}/medevidence-pwsh-${POWERSHELL_VERSION}"
archive_path="${RUNNER_TEMP}/${archive_name}"
mkdir -p "${install_root}"

curl --fail --location --proto '=https' --tlsv1.2 \
  --silent --show-error \
  --output "${archive_path}" \
  "${RELEASE_ROOT}/${archive_name}"
(
  cd "${RUNNER_TEMP}"
  printf '%s  %s\n' "${archive_sha256}" "${archive_name}" | sha256sum --check --strict
)
if [[ "${RUNNER_OS}" == "Windows" ]]; then
  /c/Windows/System32/tar.exe \
    --extract --file "${archive_path}" --directory "${install_root}"
else
  tar --extract --file "${archive_path}" --directory "${install_root}"
fi

pwsh_path="${install_root}/${executable_name}"
chmod +x "${pwsh_path}"
printf '%s\n' "${install_root}" >> "${GITHUB_PATH}"
"${pwsh_path}" -NoLogo -NoProfile -File ./scripts/assert-pwsh-runtime.ps1
