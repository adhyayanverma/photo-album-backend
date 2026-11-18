"""Inline the current Lambda source into template.yaml. Run from backend/: python cloudformation/build_template.py"""
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
LAMBDAS = HERE.parent / "lambdas"
INDENT = " " * 10  # under "ZipFile: |" (8 spaces) + 2


def indented(path):
    lines = path.read_text().splitlines()
    return "\n".join((INDENT + line) if line.strip() else "" for line in lines)


src = (HERE / "template.src.yaml").read_text()
out = (src.replace("__LF1_CODE__", indented(LAMBDAS / "index-photos" / "lambda_function.py"))
          .replace("__LF2_CODE__", indented(LAMBDAS / "search-photos" / "lambda_function.py")))
(HERE / "template.yaml").write_text(out)
print("wrote", HERE / "template.yaml")
