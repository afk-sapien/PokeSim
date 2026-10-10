#!/bin/sh
# Install the released application in a user-owned, isolated Python environment.
set -eu

unsupported() {
    printf '%s\n' "PokeSim 0.5 has no emulator build for this platform: $1." \
        'Supported: Linux x86-64 and ARM64 (glibc), macOS Intel and Apple Silicon, and Windows x64 (use install.ps1).' \
        'The Docker image (linux/amd64) is the alternative: see the Docker guide in the PokeSim documentation.' \
        'Nothing was installed. Do not run "pip install pokesim": that installs an unrelated project from PyPI.' \
        'Do not install pyboy-rs or pokesim-core from PyPI either: they are published only as GitHub release files.' >&2
    exit 1
}

main() {
    platform=$(uname -s)
    if [ "$platform" != Linux ] && [ "$platform" != Darwin ]
    then
        case "$platform" in
            MINGW*|MSYS*|CYGWIN*)
                printf '%s\n' 'Use install.ps1 in Windows PowerShell, or run this installer in Linux or macOS.' >&2
                exit 1
                ;;
        esac
        unsupported "$platform $(uname -m)"
    fi
    machine=$(uname -m)
    case "$platform $machine" in
        'Linux x86_64'|'Linux aarch64'|'Darwin x86_64'|'Darwin arm64') ;;
        *)
            unsupported "$platform $machine"
            ;;
    esac
    if [ "$platform" = Linux ]
    then
        # Only glibc wheels exist for the emulator, so Alpine and other musl systems are unsupported.
        for loader in /lib/ld-musl-* /usr/lib/ld-musl-*
        do
            if [ -e "$loader" ]
            then
                unsupported "$platform $machine (musl libc)"
            fi
        done
    fi
    if [ "$(id -u)" = 0 ]
    then
        printf '%s\n' 'Run this installer as your normal user, without sudo.' >&2
        exit 1
    fi
    version=0.5.0
    package=${POKESIM_INSTALL_PACKAGE:-https://github.com/afk-sapien/PokeSim/releases/download/v${version}/pokesim-${version}-py3-none-any.whl}
    if command -v uv >/dev/null 2>&1
    then
        uv_bin=$(command -v uv)
    elif [ -x "$HOME/.local/bin/uv" ]
    then
        uv_bin="$HOME/.local/bin/uv"
    else
        command -v curl >/dev/null 2>&1 || {
            printf '%s\n' 'Install curl with your system package manager, then retry.' >&2
            exit 1
        }
        installer=$(mktemp)
        trap 'rm -f "$installer"' EXIT HUP INT TERM
        printf '%s\n' 'Installing uv for your user account...'
        curl --fail --show-error --silent --location --retry 3 https://astral.sh/uv/install.sh -o "$installer"
        UV_INSTALL_DIR="$HOME/.local/bin" UV_NO_MODIFY_PATH=1 sh "$installer"
        uv_bin="$HOME/.local/bin/uv"
        rm -f "$installer"
        trap - EXIT HUP INT TERM
    fi
    printf '%s\n' 'Installing PokeSim with managed Python 3.12. No Git or system Python is needed.'
    "$uv_bin" tool install --python 3.12 --managed-python --upgrade "$package"
    bin_dir=$("$uv_bin" tool dir --bin)
    "$bin_dir/pokesim-desktop" --help >/dev/null
    printf '\n%s\n' 'PokeSim is installed. Start it with:'
    printf '  "%s/pokesim-desktop"\n' "$bin_dir"
    printf '\n%s\n' 'Your browser will open the Library. Add your own Red, Blue, Gold, Silver or Crystal ROM in Settings, Game cartridges.'
    printf '%s\n' 'For the short pokesim-desktop command, add the tool directory to PATH with:'
    printf '  "%s" tool update-shell\n' "$uv_bin"
    printf '%s\n' 'Then open a new terminal. Save and quit PokeSim before rerunning this installer to update.'
}

# Read the entire script before executing, including when piped into sh.
main "$@"
