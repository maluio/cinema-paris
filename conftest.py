import os
import pytest


def load_html(name):
    with open(f"{os.path.dirname(__file__)}/fixtures/{name}", "r") as f:
        content = f.read()
    return content


@pytest.fixture
def load_movies_1():
    return load_html("movies_1.html")
