"""在本地运行：python build_colab_zip.py。递归打包多目录工程源码与配置。"""

from pathlib import Path
import zipfile

from colab_training_demo.utils.code_sync import iter_project_files


def project_files(root):
    return iter_project_files(root)


def build(destination=None):
    root = Path(__file__).resolve().parent
    destination = Path(destination) if destination else root / "dist" / "colab_training_demo.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in project_files(root):
            archive.write(path, Path("colab_training_demo") / path.relative_to(root))
    print(destination)
    return destination


if __name__ == "__main__":
    build()
