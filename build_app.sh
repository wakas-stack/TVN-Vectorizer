#!/bin/zsh
# Build "dist/Vectorizer Local.app": a self-contained Mac app (Apple Silicon + Intel)
# with its own Python, so it runs on another Mac without installing anything.
#
#   ./build_app.sh   builds dist/Vectorizer Local (Mac)/ (app + read-me) and dist/Vectorizer-Local-Mac.zip
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PBS_TAG=20261021
PY_VER=3.12.15
BUILD="$HERE/build"
CACHE="$BUILD/cache"
PKG="$HERE/dist/Vectorizer Local (Mac)"            # what you copy to another Mac
APP="$PKG/Vectorizer Local.app"
NATIVE_PY="$HERE/.venv/bin/python"          # only used to run pip during the build
mkdir -p "$CACHE"

say() { print -P "%B==> $*%b"; }

# ---------------------------------------------------------------- Python runtimes
SUMS="$CACHE/SHA256SUMS-$PBS_TAG"
[[ -f "$SUMS" ]] || curl -fsSL -o "$SUMS" "https://github.com/astral-sh/python-build-standalone/releases/download/$PBS_TAG/SHA256SUMS"

typeset -A PBS_ARCH=(arm64 aarch64 x86_64 x86_64)
typeset -A WHEEL_PLAT=(arm64 macosx_11_0_arm64 x86_64 macosx_10_13_x86_64)

rm -rf "$BUILD/rt" && mkdir -p "$BUILD/rt"
for A in arm64 x86_64; do
  TAR="cpython-$PY_VER+$PBS_TAG-${PBS_ARCH[$A]}-apple-darwin-install_only_stripped.tar.gz"
  if [[ ! -f "$CACHE/$TAR" ]]; then
    say "Downloading Python $PY_VER for $A"
    curl -fsSL -o "$CACHE/$TAR" "https://github.com/astral-sh/python-build-standalone/releases/download/$PBS_TAG/${TAR//+/%2B}"
  fi
  want=$(grep " $TAR\$" "$SUMS" | cut -d' ' -f1)
  got=$(shasum -a 256 "$CACHE/$TAR" | cut -d' ' -f1)
  [[ -n "$want" && "$want" == "$got" ]] || { echo "Checksum mismatch for $TAR"; exit 1; }
  mkdir -p "$BUILD/rt/$A" && tar -xzf "$CACHE/$TAR" -C "$BUILD/rt/$A"

  # ------------------------------------------------------------ libraries
  WH="$CACHE/wheels-$A"
  mkdir -p "$WH"
  say "Collecting libraries for $A"
  grep -v proxy_tools "$HERE/requirements-app.txt" > "$BUILD/req-binary.txt"
  "$NATIVE_PY" -m pip download -q -r "$BUILD/req-binary.txt" --no-deps -d "$WH" \
      --platform "${WHEEL_PLAT[$A]}" --python-version 3.12 --implementation cp --abi cp312 --only-binary=:all:
  # proxy_tools (pure Python) only ships as source, so build its wheel once
  [[ -n "$(print -l "$WH"/proxy_tools-*.whl(N))" ]] || "$NATIVE_PY" -m pip wheel -q --no-deps "proxy_tools==0.1.0" -w "$WH"
  SITE="$BUILD/rt/$A/python/lib/python3.12/site-packages"
  "$NATIVE_PY" -m pip install -q --no-index --find-links "$WH" --no-deps --target "$SITE" \
      --platform "${WHEEL_PLAT[$A]}" --python-version 3.12 --implementation cp --abi cp312 --only-binary=:all: \
      -r "$HERE/requirements-app.txt" --upgrade

  # ------------------------------------------------------------ slim down
  L="$BUILD/rt/$A/python/lib"
  rm -rf "$L/python3.12/test" "$L/python3.12/idlelib" "$L/python3.12/tkinter" "$L/python3.12/turtledemo" \
         "$L/python3.12/ensurepip" "$L/python3.12/lib2to3" "$L"/tcl* "$L"/tk* "$L"/itcl* "$L"/thread* \
         "$L/python3.12/site-packages/pip" "$L/python3.12/site-packages"/pip-*.dist-info \
         "$L/python3.12/lib-dynload"/_tkinter* "$BUILD/rt/$A/python/share" \
         "$L/python3.12/site-packages/PyObjCTest"
  find "$BUILD/rt/$A/python" -name "__pycache__" -type d -prune -exec rm -rf {} +
  find "$L/python3.12/site-packages" -type d \( -name tests -o -name testing \) -path "*numpy*" -prune -exec rm -rf {} +
  # compiled bytecode is the same on both Mac types; the app bundle may be read-only later
  "$NATIVE_PY" -m compileall -q -j 0 "$L/python3.12" >/dev/null || true
done

# ---------------------------------------------------------------- icon
say "Making the icon"
ICONSET="$BUILD/AppIcon.iconset"
rm -rf "$ICONSET" && mkdir -p "$ICONSET"
"$NATIVE_PY" -I "$HERE/make_icon.py" "$ICONSET"
iconutil -c icns "$ICONSET" -o "$BUILD/AppIcon.icns"

# ---------------------------------------------------------------- assemble the .app
say "Assembling $APP"
rm -rf "$HERE/dist" && mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/app"
cp "$HERE/READ-ME-FIRST.txt" "$PKG/"
for A in arm64 x86_64; do
  mv "$BUILD/rt/$A/python" "$APP/Contents/Resources/runtime-$A"
  # the interpreter lives in Contents/MacOS so macOS treats the window as this app (name, icon, Dock)
  cp "$APP/Contents/Resources/runtime-$A/bin/python3.12" "$APP/Contents/MacOS/python-$A"
done
cp "$HERE"/{app.py,engine.py,precise.py,export.py,patch.py,gang.py,desktop.py,selftest.py} "$APP/Contents/Resources/app/"
rsync -a --exclude ".DS_Store" "$HERE/static" "$APP/Contents/Resources/app/"
"$NATIVE_PY" -m compileall -q "$APP/Contents/Resources/app" >/dev/null
cp "$BUILD/AppIcon.icns" "$APP/Contents/Resources/"

cat > "$APP/Contents/MacOS/Vectorizer Local" <<'LAUNCH'
#!/bin/bash
# Picks the Python built for this Mac (Apple Silicon or Intel) and starts the app.
DIR="$(cd "$(dirname "$0")" && pwd)"
RES="$DIR/../Resources"
case "$(uname -m)" in arm64) A=arm64 ;; *) A=x86_64 ;; esac
export PYTHONHOME="$RES/runtime-$A"
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
unset PYTHONPATH PYTHONSTARTUP
exec "$DIR/python-$A" -s "$RES/app/desktop.py" "$@"
LAUNCH
chmod +x "$APP/Contents/MacOS/Vectorizer Local"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Vectorizer Local</string>
  <key>CFBundleDisplayName</key><string>Vectorizer Local</string>
  <key>CFBundleIdentifier</key><string>local.vectorizer.desktop</string>
  <key>CFBundleExecutable</key><string>Vectorizer Local</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.graphics-design</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

# ad-hoc signature, so Apple Silicon accepts the bundle as one signed unit
codesign --force --deep --sign - "$APP" 2>/dev/null || echo "(ad-hoc signing skipped)"

say "Zipping"
( cd "$HERE/dist" && ditto -c -k --sequesterRsrc --keepParent "Vectorizer Local (Mac)" "Vectorizer-Local-Mac.zip" )
du -sh "$APP" "$HERE/dist/Vectorizer-Local-Mac.zip"
say "Done"
