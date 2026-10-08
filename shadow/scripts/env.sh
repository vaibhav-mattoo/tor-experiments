# Common environment for the Shadow/Tor toolchain on Delta. Source me.
export _ZO_DOCTOR=0
export B=/work/hdd/bdpr/vmattoo2/tor-shadow
export OPT=$B/opt
export RUSTUP_HOME=$B/cache/rustup CARGO_HOME=$B/cache/cargo PIP_CACHE_DIR=$B/cache/pip
module load cmake/3.31.8 llvm/19.1.7 cray-python/3.12.12 >/dev/null 2>&1
export LIBCLANG_PATH=$(llvm-config --libdir 2>/dev/null)
# Delta's `cc` is the Cray wrapper (needs a PrgEnv module); use plain gcc for C/C++ and Rust linking.
export PATH=$(echo "$PATH" | tr ':' '\n' | grep -v '/craype/' | paste -sd:)
export CC=gcc CXX=g++ CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER=gcc
export PATH=$OPT/bin:$CARGO_HOME/bin:$PATH
export LD_LIBRARY_PATH=$OPT/lib:$OPT/lib64:${LD_LIBRARY_PATH:-}
export LIBRARY_PATH=$OPT/lib64:$OPT/lib:${LIBRARY_PATH:-}
export PKG_CONFIG_PATH=$OPT/lib/pkgconfig:$OPT/lib64/pkgconfig:${PKG_CONFIG_PATH:-}
[ -f $B/venv/bin/activate ] && source $B/venv/bin/activate
