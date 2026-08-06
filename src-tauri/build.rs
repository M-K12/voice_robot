use std::env;
use std::path::PathBuf;

fn main() {
    println!("cargo:rustc-check-cfg=cfg(mobile)");
    tauri_build::build();

    // 如果用户已经手动设置了 SHERPA_ONNX_LIB_DIR，则优先使用用户的设置
    if env::var("SHERPA_ONNX_LIB_DIR").is_ok() {
        return;
    }

    // 根据编译目标平台自动推导 sherpa-onnx 库路径
    // CARGO_MANIFEST_DIR 指向 src-tauri/ 目录
    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    let project_root = manifest_dir.parent().unwrap(); // voice_robot/

    let target = env::var("TARGET").unwrap_or_default();

    let lib_subdir = if target.contains("windows") {
        "sherpa/sherpa_lib/sherpa-onnx-v1.13.2-win-x64-static-MT-Release-lib/lib"
    } else if target.contains("linux") {
        "sherpa/sherpa_lib/sherpa-onnx-linux-x64/lib"
    } else {
        // 其他平台暂不自动设置，留给用户手动配置
        return;
    };

    let lib_path = project_root.join(lib_subdir);

    if lib_path.exists() {
        println!(
            "cargo:rustc-env=SHERPA_ONNX_LIB_DIR={}",
            lib_path.display()
        );
        // 告诉 sherpa-onnx crate 的 build script 在哪里找库
        // 同时设置为进程级环境变量，供下游 -sys crate 的 build script 使用
        env::set_var("SHERPA_ONNX_LIB_DIR", &lib_path);
        println!(
            "cargo:warning=Auto-detected SHERPA_ONNX_LIB_DIR={}",
            lib_path.display()
        );
    } else {
        println!(
            "cargo:warning=Sherpa library path not found: {}. \
             Please set SHERPA_ONNX_LIB_DIR manually or download the library.",
            lib_path.display()
        );
    }
}
