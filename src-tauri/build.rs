// build.rs — 配置 Porcupine 动态库链接
use std::{env, fs, path::PathBuf};

fn main() {
    tauri_build::build();

    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    // Porcupine C SDK 相对于 src-tauri 目录
    let porcupine_lib = manifest_dir
        .parent()
        .unwrap()
        .join("porcupine")
        .join("lib");

    #[cfg(target_os = "windows")]
    let lib_dir = porcupine_lib.join("windows").join("amd64");
    #[cfg(target_os = "linux")]
    let lib_dir = porcupine_lib.join("linux").join("x86_64");
    #[cfg(target_os = "macos")]
    let lib_dir = porcupine_lib.join("mac").join("x86_64");

    println!("cargo:rustc-link-search=native={}", lib_dir.display());

    // 自动把 DLL 复制到 target 输出目录，确保运行时能找到
    #[cfg(target_os = "windows")]
    {
        let out_dir = PathBuf::from(env::var("OUT_DIR").unwrap());
        // OUT_DIR 通常是 target/debug/build/voice-robot-.../out
        // 我们需要 target/debug 目录（即上上上级）
        let target_dir = out_dir
            .ancestors()
            .nth(3)
            .unwrap()
            .to_path_buf();

        let dll_src = lib_dir.join("libpv_porcupine.dll");
        let dll_dst = target_dir.join("libpv_porcupine.dll");

        if dll_src.exists() {
            fs::copy(&dll_src, &dll_dst)
                .unwrap_or_else(|e| panic!("复制 DLL 失败: {e}"));
            println!("cargo:rerun-if-changed={}", dll_src.display());
        }

        // 另外，libpv_porcupine.dll 依赖此 dll，不复制会导致 STATUS_DLL_NOT_FOUND
        let cuda_dll_src = lib_dir.join("pv_ypu_impl_cuda_porcupine.dll");
        let cuda_dll_dst = target_dir.join("pv_ypu_impl_cuda_porcupine.dll");
        if cuda_dll_src.exists() {
            let _ = fs::copy(&cuda_dll_src, &cuda_dll_dst);
            println!("cargo:rerun-if-changed={}", cuda_dll_src.display());
        }

        println!("cargo:rustc-env=PV_LIB_DIR={}", lib_dir.display());
    }
}
