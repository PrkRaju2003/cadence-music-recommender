import pytest
from fastapi.testclient import TestClient

from cadence.api import create_app
from cadence.db import database, initialize
from cadence.seed import make_audio, seed


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / 'test.db'
    with database(path) as db:
        initialize(db)
        seed(db)
    return path


@pytest.fixture
def client(db_path):
    with TestClient(create_app(db_path)) as client:
        yield client


@pytest.fixture(scope='session')
def audio_files():
    make_audio()
