"""Arranque en una máquina limpia: directorios, Inicio y panel vacío."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture()
def clean_install(tmp_path: Path):
    """Aislar datos de usuario y crear el esquema en una base vacía."""
    db_path = tmp_path / "database.sqlite3"
    log_dir = tmp_path / "logs"
    patches = [
        patch("luciotech.config.get_data_dir", return_value=tmp_path),
        patch("luciotech.config.get_log_dir", return_value=log_dir),
        patch("luciotech.config.get_db_path", return_value=db_path),
        patch("luciotech.app.get_data_dir", return_value=tmp_path),
        patch("luciotech.app.get_log_dir", return_value=log_dir),
        patch("luciotech.database.connection.get_db_path", return_value=db_path),
        patch("luciotech.ui.main_window.get_data_dir", return_value=tmp_path),
    ]
    for item in patches:
        item.start()
    from luciotech.database.connection import init_db, reset_connection

    reset_connection()
    init_db()
    try:
        yield tmp_path
    finally:
        reset_connection()
        for item in patches:
            item.stop()


_app_holder: list[object] = []


def _app():
    from PyQt6.QtCore import QCoreApplication
    from luciotech.app import _SafeQApplication

    instance = QCoreApplication.instance()
    if instance is None:
        app = _SafeQApplication([])
        # PyQt6 no conserva la referencia del QApplication: si nadie la guarda,
        # el recolector de basura lo destruye y Qt aborta (qFatal) al crear
        # cualquier QWidget después. Conservar una referencia fuerte.
        _app_holder.append(app)
        return app
    return instance


def test_first_run_creates_sqlite_and_work_folders(clean_install: Path) -> None:
    assert (clean_install / "database.sqlite3").exists()
    from luciotech.app import _ensure_directories

    _ensure_directories()
    assert (clean_install / "attachments").is_dir()
    assert (clean_install / "backups").is_dir()
    assert (clean_install / "logs").is_dir()
    assert not (clean_install / "window_state.json").exists()


def test_first_run_selects_home_and_guides_empty_dashboard(clean_install: Path) -> None:
    app = _app()
    assert app is not None
    from luciotech.ui.main_window import MainWindow, Sidebar

    window = MainWindow()
    try:
        sidebar = window._sidebar.get_list()
        assert sidebar is not None
        assert sidebar.currentRow() == 0
        assert window._stack.currentWidget() is window._home_page
        assert window._home_page._active_value.text() == "0"
        assert window._home_page._recent_table.rowCount() == 0
        assert "Nueva recepción" in window._home_page._recent_hint.text()
        assert window.statusBar().currentMessage() == f"Sección: {Sidebar.SECTION_HOME}"
    finally:
        window.close()
