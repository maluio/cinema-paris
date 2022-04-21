import datetime

import pytest
import os

import main
from main import MoviesSpider, render_html_file, Movie, Cinema
from scrapy.http import TextResponse, Request

from bs4 import BeautifulSoup

FIXTURES_PATH = f"{os.path.dirname(__file__)}/fixtures"


def load_file(name):
    with open(f"{FIXTURES_PATH}/{name}", "r") as f:
        content = f.read()
    return content


@pytest.fixture
def load_movies_1_html():
    return load_file("movies_1.html")


def test_movies(load_movies_1_html):
    url = "https://www.example.com"
    request = Request(url=url)
    response = TextResponse(url=url,
                            request=request,
                            body=load_movies_1_html.encode('utf-8'))

    spider = MoviesSpider()
    movies = []
    for item in spider.parse(response):
        if type(item) == dict:
            movies.append(Movie.parse_obj(item['movie']))

    assert len(movies) == 2

    movie_1 = movies[0]
    assert movie_1.title == 'Alouettes, le fil à la patte'
    assert movie_1.url == 'http://cip-paris.fr/film/alouettes-le-fil-a-la-patte'
    assert movie_1.image_url == '/uploads/media/default/0002/71/thumb_170643_default_md.jpeg'

    cinema_1 = movie_1.cinemas[0]
    assert len(movie_1.cinemas) == 1
    assert cinema_1.name == 'Reflet Médicis'
    assert cinema_1.url == 'http://cip-paris.fr/salle/reflet-medicis'
    assert len(cinema_1.show_times) == 1
    assert cinema_1.show_times[0] == datetime.datetime(2022, 3, 11, 19, 30)


@pytest.mark.parametrize("day, time ,expected",
                         [
                             ("ven 11/03", "16:10", datetime.datetime(year=2000, day=11, month=3, hour=16, minute=10)),
                             ("jeu 10/03", "20:45", datetime.datetime(year=2000, day=10, month=3, hour=20, minute=45)),
                         ])
def test_parse_show_time(day, time, expected):
    spider = MoviesSpider()

    assert spider.parse_show_time(day, time, 2000) == expected


def test_render_html(tmpdir):
    index_file = tmpdir + '/index.html'
    render_html_file(index_file, FIXTURES_PATH + '/movies_1.json', datetime.date(2022, 4, 15))

    assert len(tmpdir.listdir()) == 1

    with open(index_file, 'r') as f:
        content = f.read()

    soup = BeautifulSoup(content, 'html.parser')

    assert 'generated: ' in content
    assert 'Movie A' in content
    assert len(soup.find_all(id="Cinema A")) == 1
    assert len(soup.find_all(href="#Cinema A")) == 1
    assert len(soup.find_all(id="Cinema B")) == 1
    assert len(soup.find_all(href="#Cinema B")) == 1


def test_remove_obsolete_show_times():
    movies = [
        Movie(
            title='movie a',
            url='url a',
            image_url='/image1.jpeg',
            cinemas=[
                Cinema(
                    name='cinema1',
                    url='url b',
                    show_times=[datetime.datetime(year=2000, month=1, day=14)]
                )
            ]
        ),
        Movie(
            title='movie b',
            url='url b',
            image_url='/image1.jpeg',
            cinemas=[
                Cinema(
                    name='cinema1',
                    url='url b',
                    show_times=[
                        datetime.datetime(year=2000, month=1, day=14),
                        datetime.datetime(year=2000, month=1, day=15)
                    ]
                )
            ]
        ),
        Movie(
            title='movie c',
            url='url c',
            image_url='/image1.jpeg',
            cinemas=[
                Cinema(
                    name='cinema1',
                    url='url b',
                    show_times=[datetime.datetime(year=2000, month=1, day=26)]
                )
            ]
        ),
    ]

    post_movies = main.remove_obsolete_show_times(movies, datetime.date(year=2000, month=1, day=15))

    assert len(post_movies) == 1
    assert post_movies[0].title == 'movie b'
    assert len(post_movies[0].cinemas[0].show_times) == 1
    assert post_movies[0].cinemas[0].show_times[0] == datetime.datetime(year=2000, month=1, day=15)
