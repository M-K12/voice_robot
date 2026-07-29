import urllib.request
import tarfile
import os
import ssl

urls = [
    "https://gh-proxy.com/https://github.com/k2-fsa/sherpa-onnx/releases/download/v1.13.2/sherpa-onnx-v1.13.2-win-x64-static-MT-Release-lib.tar.bz2",
    "https://mirror.ghproxy.com/https://github.com/k2-fsa/sherpa-onnx/releases/download/v1.13.2/sherpa-onnx-v1.13.2-win-x64-static-MT-Release-lib.tar.bz2",
    "https://github.moeyy.xyz/https://github.com/k2-fsa/sherpa-onnx/releases/download/v1.13.2/sherpa-onnx-v1.13.2-win-x64-static-MT-Release-lib.tar.bz2",
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/v1.13.2/sherpa-onnx-v1.13.2-win-x64-static-MT-Release-lib.tar.bz2"
]

dest_dir = "sherpa_lib"
dest_archive = os.path.join(dest_dir, "sherpa-onnx-win-x64.tar.bz2")
os.makedirs(dest_dir, exist_ok=True)

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

downloaded = False
for url in urls:
    print(f"Trying to download from: {url}")
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

print("Extracting archive...")
try:
    with tarfile.open(dest_archive, "r:bz2") as tar:
        tar.extractall(path=dest_dir)
    print("Extraction finished successfully.")
except Exception as e:
    print(f"Extraction failed: {e}")
