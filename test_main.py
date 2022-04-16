import datetime

import pytest

from main import MoviesSpider
from scrapy.http import TextResponse, Request


def test_movies(load_movies_1):
    url = "https://www.example.com"
    request = Request(url=url)
    response = TextResponse(url=url,
                            request=request,
                            body=load_movies_1.encode('utf-8'))

    spider = MoviesSpider()
    items = []
    for item in spider.parse(response):
        if type(item) == dict:
            items.append(item)

    assert len(items) == 2

    assert items[0]['movie']['title'] == 'Alouettes, le fil à la patte'
    assert items[0]['movie']['url'] == 'http://cip-paris.fr/film/alouettes-le-fil-a-la-patte'
    assert len(items[0]['cinemas']) == 1
    assert items[0]['cinemas'][0]['name'] == 'Reflet Médicis'
    assert items[0]['cinemas'][0]['url'] == 'http://cip-paris.fr/salle/reflet-medicis'
    assert len(items[0]['cinemas'][0]['show_times']) == 1
    assert items[0]['cinemas'][0]['show_times'][0] == '2022-03-11T19:30:00'


@pytest.mark.parametrize("day, time ,expected",
                         [
                             ("ven 11/03", "16:10", datetime.datetime(year=2000, day=11, month=3, hour=16, minute=10)),
                             ("jeu 10/03", "20:45", datetime.datetime(year=2000, day=10, month=3, hour=20, minute=45)),
                         ])
def test_parse_show_time(day, time, expected):
    spider = MoviesSpider()

    assert spider.parse_show_time(day, time, 2000) == expected
