"""app/ 의 모든 모듈이 Python 3.11에서도 구문 오류 없이 컴파일되는지 검사 (f-string 내 백슬래시 금지)."""
import pathlib
import py_compile

import pytest

FILES = sorted(pathlib.Path(__file__).resolve().parent.parent.glob("app/**/*.py"))


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_compiles(path, tmp_path):
    py_compile.compile(str(path), cfile=str(tmp_path / "x.pyc"), doraise=True)
