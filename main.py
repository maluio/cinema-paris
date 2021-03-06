import datetime
import json
import os
import tempfile
from typing import List
from dataclasses import dataclass, field

from pydantic import BaseModel

import scrapy
from jinja2 import FileSystemLoader, Environment
from scrapy.crawler import CrawlerProcess

import logging
import boto3
from botocore.exceptions import ClientError

CIP_BASE_URL = 'http://cip-paris.fr'
MAX_DAYS = os.getenv('MAX_DAYS', 10)

# scrapy and boto3 are logging by default debug level and above; disable by default to not pollute the logs
if not os.getenv('DEBUG'):
    logging.disable(logging.DEBUG)


class Cinema(BaseModel):
    url: str
    name: str
    show_times: List[datetime.datetime]


class Movie(BaseModel):
    url: str
    title: str
    image_url: str
    cinemas: List[Cinema]


class MoviesSpider(scrapy.Spider):
    name = 'movies'
    start_urls = [
        # category 2: movies with current show times
        'http://cip-paris.fr/ajax-movies?page=1&category=2&direction=ASC',
        # category 3: movies with future show times
        'http://cip-paris.fr/ajax-movies?page=1&category=3&direction=ASC',
    ]

    def parse_show_time(self, day_raw: str, time: str, curent_year=datetime.datetime.now().year) -> datetime.datetime:
        month = int(day_raw[-2:])
        day = int(day_raw[-5:-3])
        year = curent_year
        hour = int(time[0:2])
        minute = int(time[-2:])

        return datetime.datetime(year=year, month=month, day=day, hour=hour, minute=minute)

    def parse(self, response):
        for container in response.css('.movie-results-container'):
            movie_title = container.css(".desc h3::text").get()
            sessions = container.css(".movie-sessions")
            image_url = container.css(".poster img::attr(src)").get()
            cinemas = []
            for session in sessions:
                cinema_names = session.css(".cinemaTitle")
                reservations = session.css(f".reservations-wrapper")
                for key, cn in enumerate(cinema_names):
                    cinema = cinema_names[key]
                    reservation = reservations[key]
                    cinema = Cinema(
                        name=cinema.css("h3::text").get(),
                        url=CIP_BASE_URL + cinema.css("a::attr(href)").get(),
                        show_times=[]
                    )
                    session_dates = reservation.css('.session-date')
                    for sd in session_dates:
                        day = sd.css('.sessionDate::text').get().strip()
                        time = sd.css('.time::text').get().strip()
                        cinema.show_times.append(self.parse_show_time(day, time))
                    cinemas.append(cinema)
            yield {
                'movie': Movie(title=movie_title, url=CIP_BASE_URL + container.css(".clearfix > a::attr(href)").get(),
                               image_url=image_url,
                               cinemas=cinemas).dict()
            }

        next_page = response.css('.pagination')[0].css('.current + .page a::attr("href")').get()
        if next_page is not None:
            yield response.follow(next_page, self.parse)


def upload_file_to_s3(file_name, bucket, object_name=None):
    """Upload a file to an S3 bucket

    :param file_name: File to upload
    :param bucket: Bucket to upload to
    :param object_name: S3 object name. If not specified then file_name is used
    :return: True if file was uploaded, else False
    """

    # If S3 object_name was not specified, use file_name
    if object_name is None:
        object_name = os.path.basename(file_name)

    # Upload the file
    s3_client = boto3.client('s3')
    try:
        s3_client.upload_file(file_name, bucket, object_name, ExtraArgs={'ContentType': "text/html"})
    except ClientError as e:
        logging.error(e)
        raise Exception("Error when trying to upload file to S3")


def run_crawler(output_file: str):
    # Run Scrapy from a script: https://docs.scrapy.org/en/latest/topics/practices.html#run-from-script
    # Built-in settings reference: https://docs.scrapy.org/en/latest/topics/settings.html#topics-settings-ref
    process = CrawlerProcess(settings={
        "FEEDS": {
            output_file: {"format": "json"},
        }
    })

    process.crawl(MoviesSpider)
    process.start()


@dataclass
class MoviesByCinema:
    """Helper class to keep things organized"""
    cinema: Cinema
    movies: List[Movie] = field(default_factory=list)


def get_movies_by_cinema(movies: List[Movie]) -> List[MoviesByCinema]:
    cinemas = dict()

    for m in movies:
        for c in m.cinemas:
            name = c.name
            if not cinemas.get(name):
                cinemas[name] = MoviesByCinema(cinema=c)
            cinemas[name].movies.append(m)

    return cinemas.values()


@dataclass
class MoviesByDay:
    """Helper class to keep things organized"""
    day: datetime.date
    movies: List[Movie] = field(default_factory=list)


def remove_obsolete_show_times(movies: List[Movie], reference: datetime.date,
                               max_days: int = MAX_DAYS) -> List[Movie]:
    """Remove movies with show times that are in the past or too far in the future"""
    for m in movies[:]:
        has_desired_show_time = False
        for c in m.cinemas:
            for st in c.show_times[:]:
                max_date = reference + datetime.timedelta(days=max_days)
                if reference <= st.date() <= max_date:
                    has_desired_show_time = True
                else:
                    c.show_times.remove(st)
        if not has_desired_show_time:
            movies.remove(m)
    return movies


def show_time_render_filter(show_time: datetime.datetime):
    return show_time.strftime(f'{show_time.strftime("%H:%M")}')


def show_times_by_day_render_filter(show_times: List[datetime.datetime], days: List[datetime.date]):
    by_day = []
    for day in days:
        sts = []
        for st in show_times:
            if day == st.date():
                sts.append(st)
        by_day.append(sts)
    return by_day


def render_html_file(html_file_name, data_file_name, reference: datetime.date = datetime.date.today()):
    with open(data_file_name, 'r') as f:
        movies_raw = json.load(f)

    movies: List[Movie] = []
    for mr in movies_raw:
        movies.append(Movie.parse_obj(mr['movie']))

    movies = remove_obsolete_show_times(movies, reference)

    env = Environment(
        loader=FileSystemLoader("templates")
    )
    env.filters['showtime'] = show_time_render_filter
    env.filters['showtimesdays'] = show_times_by_day_render_filter

    days = []
    for day in range(MAX_DAYS):
        days.append(datetime.date.today() + datetime.timedelta(days=day))

    template = env.get_template("index.jinja2")
    with open(html_file_name, 'w') as t:
        t.write(template.render(movies=movies,
                                movies_by_cinema=get_movies_by_cinema(movies), now=datetime.datetime.now(),
                                image_prefix=CIP_BASE_URL, days=days))


if __name__ == '__main__':

    if not os.environ.get('AWS_BUCKET'):
        raise Exception('AWS_BUCKET not set')
    if not os.environ.get('AWS_ACCESS_KEY_ID'):
        raise Exception('AWS_ACCESS_KEY_ID not set')
    if not os.environ.get('AWS_SECRET_ACCESS_KEY'):
        raise Exception('AWS_SECRET_ACCESS_KEY not set')

    with tempfile.TemporaryDirectory() as tmp_dir_name:
        logging.info(f'created temporary directory {tmp_dir_name}')

        output_file = f'{tmp_dir_name}/movies.json'

        logging.info('start crawler')
        run_crawler(output_file)
        logging.info('end crawler')

        html_file_name = f'{tmp_dir_name}/index.html'

        logging.info('start render html')
        render_html_file(html_file_name, output_file)
        logging.info('end render html')

        logging.info('start upload S3')
        upload_file_to_s3(html_file_name, os.environ.get('AWS_BUCKET'))
        logging.info('end upload S3')
