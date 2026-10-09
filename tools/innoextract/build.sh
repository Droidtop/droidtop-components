#!/usr/bin/env bash
# Builds innoextract for one Android ABI from its upstream source release, with Boost, xz and bzip2
# built from their upstream releases and linked in statically, so the one binary needs only Android's
# own libc, libm and libdl. It is a position-independent dynamic executable, which Android's
# /system/bin/linker64 can start from app storage (droidtop runs it that way, as it runs Wine).
#
# Usage: tools/innoextract/build.sh <arm64-v8a|x86_64> <output dir>
# Needs ANDROID_NDK_HOME (or ANDROID_NDK_LATEST_HOME), cmake, ninja, curl, python3.
set -euo pipefail

ABI="${1:?abi: arm64-v8a or x86_64}"
OUT="$(realpath -m "${2:?output dir}")"
NDK="${ANDROID_NDK_HOME:-${ANDROID_NDK_LATEST_HOME:?no NDK}}"
API=24

INNOEXTRACT_VERSION=1.9
INNOEXTRACT_URL="https://github.com/dscharrer/innoextract/releases/download/1.9/innoextract-1.9.tar.gz"
INNOEXTRACT_SHA256=6344a69fc1ed847d4ed3e272e0da5998948c6b828cb7af39c6321aba6cf88126
# Boost 1.84 is the last release with boost::filesystem::copy_option, which innoextract 1.9 uses.
BOOST_URL="https://github.com/boostorg/boost/releases/download/boost-1.84.0/boost-1.84.0.tar.xz"
BOOST_SHA256=2e64e5d79a738d0fa6fb546c6e5c2bd28f88d268a2a080546f74e5ff98f29d0e
XZ_URL="https://github.com/tukaani-project/xz/releases/download/v5.8.1/xz-5.8.1.tar.xz"
XZ_SHA256=0b54f79df85912504de0b14aec7971e3f964491af1812d83447005807513cd9e
BZIP2_URL="https://sourceware.org/pub/bzip2/bzip2-1.0.8.tar.gz"
BZIP2_SHA256=ab5a03176ee106d3f0fa90e381da478ddae405918153cca248e682cd0c4a2269

case "$ABI" in
  arm64-v8a) TRIPLE=aarch64-linux-android; B2_ARCH=arm ;;
  x86_64)    TRIPLE=x86_64-linux-android;  B2_ARCH=x86 ;;
  *) echo "unknown abi $ABI" >&2; exit 2 ;;
esac

TOOLCHAIN="$NDK/toolchains/llvm/prebuilt/linux-x86_64"
CC="$TOOLCHAIN/bin/${TRIPLE}${API}-clang"
CXX="$TOOLCHAIN/bin/${TRIPLE}${API}-clang++"
AR="$TOOLCHAIN/bin/llvm-ar"
RANLIB="$TOOLCHAIN/bin/llvm-ranlib"
STRIP="$TOOLCHAIN/bin/llvm-strip"
JOBS="$(nproc)"

WORK="$(mktemp -d)"
PREFIX="$WORK/prefix"
mkdir -p "$PREFIX/lib" "$PREFIX/include" "$OUT"
cd "$WORK"

fetch() { # url sha256 file
  curl -fsSL --retry 3 -o "$3" "$1"
  echo "$2  $3" | sha256sum -c -
}
fetch "$INNOEXTRACT_URL" "$INNOEXTRACT_SHA256" innoextract.tar.gz
fetch "$BOOST_URL" "$BOOST_SHA256" boost.tar.xz
fetch "$XZ_URL" "$XZ_SHA256" xz.tar.xz
fetch "$BZIP2_URL" "$BZIP2_SHA256" bzip2.tar.gz
mkdir innoextract boost xz bzip2
tar -xzf innoextract.tar.gz -C innoextract --strip-components=1
tar -xJf boost.tar.xz -C boost --strip-components=1
tar -xJf xz.tar.xz -C xz --strip-components=1
tar -xzf bzip2.tar.gz -C bzip2 --strip-components=1

TOOLCHAIN_FILE="$NDK/build/cmake/android.toolchain.cmake"
CMAKE_COMMON=(-G Ninja -DCMAKE_TOOLCHAIN_FILE="$TOOLCHAIN_FILE" -DANDROID_ABI="$ABI" -DANDROID_PLATFORM="android-$API"
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PREFIX" -DCMAKE_POSITION_INDEPENDENT_CODE=ON
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5)

echo "== bzip2"
( cd bzip2
  for f in blocksort huffman crctable randtable compress decompress bzlib; do
    "$CC" -O2 -fPIC -D_FILE_OFFSET_BITS=64 -c "$f.c"
  done
  "$AR" rcs libbz2.a blocksort.o huffman.o crctable.o randtable.o compress.o decompress.o bzlib.o
  cp libbz2.a "$PREFIX/lib/"; cp bzlib.h "$PREFIX/include/" )

echo "== xz"
cmake -S xz -B xz/build "${CMAKE_COMMON[@]}" -DBUILD_SHARED_LIBS=OFF -DXZ_NLS=OFF \
  -DXZ_TOOL_XZ=OFF -DXZ_TOOL_XZDEC=OFF -DXZ_TOOL_LZMADEC=OFF -DXZ_TOOL_LZMAINFO=OFF -DXZ_TOOL_SYMLINKS=OFF -DXZ_TOOL_SCRIPTS=OFF
cmake --build xz/build -j"$JOBS"
cmake --install xz/build

echo "== boost"
( cd boost
  ./bootstrap.sh --with-toolset=gcc >/dev/null
  cat > user-config.jam <<JAM
using clang : android : $CXX : <archiver>$AR <ranlib>$RANLIB <compileflags>-fPIC <compileflags>-DBOOST_ASIO_DISABLE_STD_ALIGNED_ALLOC ;
JAM
  ./b2 -j"$JOBS" --user-config=user-config.jam --prefix="$PREFIX" --layout=system \
    toolset=clang-android target-os=android architecture="$B2_ARCH" address-model=64 abi=$([ "$ABI" = arm64-v8a ] && echo aapcs || echo sysv) binary-format=elf \
    link=static runtime-link=shared threading=multi variant=release cxxflags=-std=c++14 \
    -sBZIP2_INCLUDE="$PREFIX/include" -sBZIP2_LIBPATH="$PREFIX/lib" -sBZIP2_BINARY=bz2 \
    -sNO_LZMA=1 -sNO_ZSTD=1 \
    --with-iostreams --with-filesystem --with-program_options --with-date_time --with-system \
    install )

echo "== innoextract"
cmake -S innoextract -B innoextract/build "${CMAKE_COMMON[@]}" \
  -DCMAKE_PREFIX_PATH="$PREFIX" -DBOOST_ROOT="$PREFIX" -DBoost_NO_SYSTEM_PATHS=ON -DBoost_USE_STATIC_LIBS=ON \
  -DBoost_INCLUDE_DIR="$PREFIX/include" -DBoost_LIBRARY_DIR="$PREFIX/lib" \
  -DLZMA_INCLUDE_DIR="$PREFIX/include" -DLZMA_LIBRARY="$PREFIX/lib/liblzma.a" \
  -DUSE_LTO=OFF -DUSE_STATIC_LIBS=ON -DSET_WARNING_FLAGS=OFF -DCMAKE_EXE_LINKER_FLAGS="-static-libstdc++"
cmake --build innoextract/build -j"$JOBS"

BIN="innoextract/build/innoextract"
"$STRIP" "$BIN"
NAME="innoextract-${INNOEXTRACT_VERSION}-${ABI}"
cp "$BIN" "$OUT/$NAME"
echo "== result"
"$TOOLCHAIN/bin/llvm-readelf" -h "$OUT/$NAME" | grep -E "Type|Machine"
"$TOOLCHAIN/bin/llvm-readelf" -d "$OUT/$NAME" | grep -E "NEEDED|FLAGS" || true
"$TOOLCHAIN/bin/llvm-readelf" -l "$OUT/$NAME" | grep -i interpreter || true
sha256sum "$OUT/$NAME"
ls -l "$OUT/$NAME"
rm -rf "$WORK"
