import urllib.request
import tarfile
import os
import ssl
import shutil

# 定义 Linux x64 静态链接库包下载地址与镜像代理列表，防止大陆网络下载 GitHub 资源失败
urls = [
    "https://gh-proxy.com/https://github.com/k2-fsa/sherpa-onnx/releases/download/v1.13.2/sherpa-onnx-v1.13.2-linux-x64-static-no-tts-lib.tar.bz2",
    "https://mirror.ghproxy.com/https://github.com/k2-fsa/sherpa-onnx/releases/download/v1.13.2/sherpa-onnx-v1.13.2-linux-x64-static-no-tts-lib.tar.bz2",
    "https://github.moeyy.xyz/https://github.com/k2-fsa/sherpa-onnx/releases/download/v1.13.2/sherpa-onnx-v1.13.2-linux-x64-static-no-tts-lib.tar.bz2",
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/v1.13.2/sherpa-onnx-v1.13.2-linux-x64-static-no-tts-lib.tar.bz2"
]

dest_dir = "tmp_linux_lib"
dest_archive = os.path.join(dest_dir, "sherpa-onnx-linux-x64-static-no-tts-lib.tar.bz2")
os.makedirs(dest_dir, exist_ok=True)

# 绕过 SSL 证书检测，防范代理干扰
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

downloaded = False
for url in urls:
    print(f"Trying to download Linux x64 Sherpa library from: {url}")
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, context=ctx, timeout=30) as response:
            with open(dest_archive, 'wb') as out_file:
                size = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    out_file.write(chunk)
                    size += len(chunk)
                    print(f"  Downloaded {size / (1024*1024):.2f} MB", end="\r")
            print("\nDownload finished.")
            downloaded = True
            break
    except Exception as e:
        print(f"  Failed: {e}")

if not downloaded:
    print("All URLs failed. Please download the file manually.")
    exit(1)

print("Extracting Linux archive...")
extract_target = os.path.join(dest_dir, "extracted")
os.makedirs(extract_target, exist_ok=True)

try:
    with tarfile.open(dest_archive, "r:bz2") as tar:
        tar.extractall(path=extract_target)
    print("Extraction finished successfully.")
except Exception as e:
    print(f"Extraction failed: {e}")
    exit(1)

# 动态寻找解压出来的动态库文件夹并搬运
# 解压出来多为：tmp_linux_lib/extracted/sherpa-onnx-v1.13.2-linux-x64-static/lib
target_lib_dest = os.path.join("sherpa", "sherpa_lib", "sherpa-onnx-linux-x64", "lib")
os.makedirs(target_lib_dest, exist_ok=True)

moved = False
for root, dirs, files in os.walk(extract_target):
    if os.path.basename(root) == "lib":
        # 找到了库目录，执行移动
        print(f"Moving libraries from {root} to {target_lib_dest}...")
        for filename in files:
            src_file = os.path.join(root, filename)
            dest_file = os.path.join(target_lib_dest, filename)
            shutil.copy2(src_file, dest_file)
            print(f"  Copied: {filename}")
        moved = True
        break

if moved:
    print("Linux x64 library files successfully organized!")
    # 清理临时文件
    try:
        shutil.rmtree(dest_dir)
        print("Cleaned up temporary download directories.")
    except Exception as e:
        print(f"Cleanup warning: {e}")
else:
    print("Could not locate the 'lib' folder in the extracted archive.")
