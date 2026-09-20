"""`pgproof configure`: interactive interview, non-interactive validation, TOML output."""

from pathlib import Path

from click.testing import CliRunner

from pgproof.cli.app import main

_A_MODEL = (
    "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column\n"
    "class Base(DeclarativeBase):\n    pass\n"
    "class Widget(Base):\n"
    "    __tablename__ = 'widgets'\n"
    "    id: Mapped[int] = mapped_column(primary_key=True)\n"
)

_A_MODEL_WITH_TENANT = (
    "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column\n"
    "class Base(DeclarativeBase):\n    pass\n"
    "class Widget(Base):\n"
    "    __tablename__ = 'widgets'\n"
    "    id: Mapped[int] = mapped_column(primary_key=True)\n"
    "    tenant_id: Mapped[int] = mapped_column()\n"
)


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_a_repository_with_no_tenant_signal_asks_six_questions(tmp_path: Path) -> None:
    _write(tmp_path, "myapp/__init__.py", "")
    _write(tmp_path, "myapp/models.py", _A_MODEL)
    answers = "\n".join(["a"] * 6) + "\n"
    result = CliRunner().invoke(main, ["--ascii", "configure", str(tmp_path)], input=answers)
    assert result.exit_code == 0
    assert result.output.count(" >:") == 6
    assert "core_tenant_model" not in result.output


def test_a_repository_with_a_tenant_id_column_asks_all_seven(tmp_path: Path) -> None:
    _write(tmp_path, "myapp/__init__.py", "")
    _write(tmp_path, "myapp/models.py", _A_MODEL_WITH_TENANT)
    answers = "\n".join(["a"] * 7) + "\n"
    result = CliRunner().invoke(main, ["--ascii", "configure", str(tmp_path)], input=answers)
    assert result.exit_code == 0
    assert result.output.count(" >:") == 7


def test_blank_answers_are_recorded_as_unknown(tmp_path: Path) -> None:
    _write(tmp_path, "myapp/__init__.py", "")
    _write(tmp_path, "myapp/models.py", _A_MODEL)
    result = CliRunner().invoke(main, ["configure", str(tmp_path)], input="\n" * 6)
    assert result.exit_code == 0
    toml_text = (tmp_path / "pgproof.toml").read_text()
    assert 'state = "unknown"' in toml_text
    assert "critical_operations = [" not in toml_text


def test_table_scale_answer_parses_table_current_and_future_rows(tmp_path: Path) -> None:
    _write(tmp_path, "myapp/__init__.py", "")
    _write(tmp_path, "myapp/models.py", _A_MODEL)
    answers = "checkout\norders:100:1000,\n" + "\n" * 4
    result = CliRunner().invoke(main, ["configure", str(tmp_path)], input=answers)
    assert result.exit_code == 0
    toml_text = (tmp_path / "pgproof.toml").read_text()
    assert 'table = "public.orders"' in toml_text
    assert 'current_rows = "100"' in toml_text
    assert 'rows_in_twelve_months = "1000"' in toml_text


def test_non_interactive_fails_with_the_missing_decision(tmp_path: Path) -> None:
    _write(tmp_path, "myapp/__init__.py", "")
    _write(tmp_path, "myapp/models.py", _A_MODEL)
    result = CliRunner().invoke(main, ["configure", str(tmp_path), "--non-interactive"])
    assert result.exit_code == 2
    assert "core_critical_operations" in result.output


def test_non_interactive_passes_once_the_config_already_answers_everything(tmp_path: Path) -> None:
    _write(tmp_path, "myapp/__init__.py", "")
    _write(tmp_path, "myapp/models.py", _A_MODEL)
    CliRunner().invoke(main, ["configure", str(tmp_path)], input="\n" * 6)
    result = CliRunner().invoke(main, ["configure", str(tmp_path), "--non-interactive"])
    assert result.exit_code == 0


def test_rerunning_configure_does_not_re_ask_an_already_answered_question(tmp_path: Path) -> None:
    _write(tmp_path, "myapp/__init__.py", "")
    _write(tmp_path, "myapp/models.py", _A_MODEL)
    CliRunner().invoke(main, ["configure", str(tmp_path)], input="checkout\n" + "\n" * 5)
    result = CliRunner().invoke(main, ["--ascii", "configure", str(tmp_path)], input="")
    assert result.exit_code == 0
    assert result.output.count(" >:") == 0
    assert "critical_operations" in (tmp_path / "pgproof.toml").read_text()


def test_writes_pgproof_toml_at_the_repository_root(tmp_path: Path) -> None:
    _write(tmp_path, "myapp/__init__.py", "")
    _write(tmp_path, "myapp/models.py", _A_MODEL)
    result = CliRunner().invoke(main, ["configure", str(tmp_path)], input="\n" * 6)
    assert result.exit_code == 0
    assert (tmp_path / "pgproof.toml").is_file()
    assert "pgproof.toml updated" in result.output


def test_help_documents_non_interactive() -> None:
    result = CliRunner().invoke(main, ["configure", "--help"])
    assert "--non-interactive" in result.output
