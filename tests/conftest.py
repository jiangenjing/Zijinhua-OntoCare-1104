import shutil
import sqlite3
from contextlib import closing

import pytest

from ontocare.agent import Agent
from ontocare.app import create_app
from ontocare.data import ROOT
from ontocare.evaluation import http_server
from ontocare.retrieval import Retriever


@pytest.fixture(scope="session")
def test_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("ontocare")
    for name in ["data", "ontology", "evaluation", "web", "prompts", "actions"]:
        shutil.copytree(ROOT / name, root / name)
    (root / "local").mkdir()
    # Serving/evaluation may write concurrently; copying live database bytes is inconsistent.
    for name in ['service.sqlite', 'business.sqlite']:
        if (ROOT/'local'/name).exists():
            with closing(sqlite3.connect(ROOT/'local'/name)) as source, closing(sqlite3.connect(root/'local'/name)) as target:
                source.backup(target)
    if (ROOT / "local/catalog-media").exists():
        shutil.copytree(ROOT / "local/catalog-media", root / "local/catalog-media")
    return root


@pytest.fixture(scope="session")
def agent(test_root):
    # Core behavior tests deliberately exercise explicit BM25 fallback too.
    return Agent(test_root, Retriever(test_root))


@pytest.fixture(scope="session")
def app(test_root, agent):
    return create_app(test_root, agent)


@pytest.fixture(scope="session")
def base(app):
    with http_server(app) as url:
        yield url
