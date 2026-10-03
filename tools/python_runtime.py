"""Bundle a Windows x64 Python runtime, including Agent dependencies."""

import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

PYTHON_VERSION = "3.13.14"


def install_windows_python(install_path: Path, maafw_version: str):
    if not maafw_version:
        raise ValueError("A MaaFramework version is required for Python dependencies")
    runtime = install_path / "python"
    runtime.mkdir(parents=True, exist_ok=True)
    url = (
        f"https://www.python.org/ftp/python/{PYTHON_VERSION}/"
        f"python-{PYTHON_VERSION}-embed-amd64.zip"
    )
    with tempfile.TemporaryDirectory() as temporary:
        archive = Path(temporary) / "python.zip"
        print(f"Downloading portable Python {PYTHON_VERSION}...")
        urllib.request.urlretrieve(url, archive)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(runtime)

    # Isolated embedded Python needs explicit paths, including the Agent directory.
    (runtime / "python313._pth").write_text(
        "python313.zip\n.\nLib/site-packages\n../agent\nimport site\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install",
            "--target", str(runtime / "Lib" / "site-packages"),
            "--platform", "win_amd64",
            "--python-version", "3.13",
            "--implementation", "cp",
            "--abi", "cp313",
            "--only-binary=:all:",
            "--upgrade", "--no-compile",
            f"maafw=={maafw_version.removeprefix('v')}",
        ],
        check=True,
    )

    # On Windows, also check native library loading; cross-builds cannot execute it.
    if sys.platform == "win32":
        subprocess.run(
            [
                str((runtime / "python.exe").resolve()), "-B", "-c",
                "import chart_player; from maa.toolkit import Toolkit; "
                "assert Toolkit.init_option('.'); print('Bundled Agent imports passed')",
            ],
            cwd=install_path,
            check=True,
        )
