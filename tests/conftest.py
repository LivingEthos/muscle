"""
Shared pytest fixtures for MUSCLE tests.
"""

import tempfile
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest


@pytest.fixture
def mock_subprocess() -> Generator[MagicMock, None, None]:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        yield mock_run


@pytest.fixture
def mock_shutil_which() -> Generator[MagicMock, None, None]:
    with patch("shutil.which") as mock_which:
        mock_which.return_value = "/usr/bin/tool"
        yield mock_which


@pytest.fixture
def temp_project_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_requests() -> Generator[MagicMock, None, None]:
    with patch("requests.post") as mock_post:
        with patch("requests.get") as mock_get:
            with patch("requests.patch") as mock_patch:
                mock_post.return_value = Mock(status_code=200, json=lambda: {}, text="")
                mock_get.return_value = Mock(status_code=200, json=lambda: {}, text="")
                mock_patch.return_value = Mock(status_code=200, json=lambda: {}, text="")
                m = MagicMock()
                m.post = mock_post
                m.get = mock_get
                m.patch = mock_patch
                yield m


@pytest.fixture
def mock_path(temp_project_dir: Path) -> Generator[MagicMock, None, None]:
    with patch("pathlib.Path") as mock_path:

        def create_path(path_str):
            p = MagicMock(spec=Path)
            p.absolute.return_value = p
            p.exists.return_value = True
            p.is_file.return_value = True
            p.is_dir.return_value = True
            p.__truediv__ = lambda self, other: create_path(str(self) + "/" + str(other))
            p.__fspath__ = lambda self: str(path_str)
            return p

        instance = create_path(str(temp_project_dir))
        mock_path.return_value = instance
        mock_path.cwd.return_value = temp_project_dir
        mock_path.home.return_value = Path(temp_project_dir).parent
        yield mock_path


@pytest.fixture
def mock_sqlite3() -> Generator[MagicMock, None, None]:
    with patch("sqlite3.connect") as mock_connect:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.commit.return_value = None
        mock_conn.close.return_value = None
        mock_cursor.execute.return_value = None
        mock_cursor.fetchall.return_value = []
        mock_cursor.fetchone.return_value = None
        mock_cursor.lastrowid = 1
        mock_connect.return_value = mock_conn
        yield mock_connect, mock_conn, mock_cursor
