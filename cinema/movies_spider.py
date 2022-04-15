import datetime
import json
import os
import tempfile

import scrapy
from jinja2 import Template
from scrapy.crawler import CrawlerProcess

import logging
import boto3
from botocore.exceptions import ClientError

CIP_BASE_URL = 'http://cip-paris.fr'


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
            cinemas = []
            for session in sessions:
                cinema_names = session.css(".cinemaTitle")
                reservations = session.css(f".reservations-wrapper")
                for key, cn in enumerate(cinema_names):
                    cinema = cinema_names[key]
                    reservation = reservations[key]
                    cinema = {
                        'name': cinema.css("h3::text").get(),
                        'url': CIP_BASE_URL + cinema.css("a::attr(href)").get(),
                        'show_times': []
                    }
                    session_dates = reservation.css('.session-date')
                    for sd in session_dates:
                        day = sd.css('.sessionDate::text').get().strip()
                        time = sd.css('.time::text').get().strip()
                        cinema['show_times'].append(self.parse_show_time(day, time).isoformat())
                    cinemas.append(cinema)
            yield {
                'movie': {'title': movie_title, 'url': CIP_BASE_URL + container.css(".clearfix > a::attr(href)").get()},
                'cinemas': cinemas
            }

        next_page = response.css('.pagination')[0].css('.current + .page a::attr("href")').get()
        if next_page is not None:
            yield response.follow(next_page, self.parse)


def parse_show_times(show_times):
    sts = []
    for st in show_times:
        sts.append(datetime.datetime.fromisoformat(st))
    return sts


def format_show_times(show_times):
    sts = []
    for st in show_times:
        st.strftime('%a : %H:%Mh (%d/%Y)')
    return sts


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


if __name__ == '__main__':

    with tempfile.TemporaryDirectory() as tmp_dir_name:
        logging.info('created temporary directory', tmp_dir_name)

        # Run Scrapy from a script: https://docs.scrapy.org/en/latest/topics/practices.html#run-from-script
        # Built-in settings reference: https://docs.scrapy.org/en/latest/topics/settings.html#topics-settings-ref
        process = CrawlerProcess(settings={
            "FEEDS": {
                f'{tmp_dir_name}/movies.json': {"format": "json"},
            },
            "LOG_LEVEL": "WARNING"
        })

        process.crawl(MoviesSpider)
        process.start()

        with open(f'{tmp_dir_name}/movies.json', 'r') as f:
            movies = json.load(f)

        cinemas = dict()

        for m in movies:
            for c in m['cinemas']:
                name = c['name']
                c['show_times'] = parse_show_times(c['show_times'])
                cinemas[name] = cinemas.get(name, {"name": name, "url": c['url'], "movies": []})
                cinemas[name]['movies'].append(
                    {'movie': {'title': m['movie']['title'], 'url': m['movie']['url'],
                               'show_times': format_show_times(c['show_times'])}})

        with open('cinema.jinja2', 'r') as t:
            template = Template(t.read())

        html_file_name = f'{tmp_dir_name}/index.html'
        with open(html_file_name, 'w') as t:
            t.write(template.render(movies=movies, cinemas=cinemas.values()))

        if os.environ.get('AWS_BUCKET'):
            upload_file_to_s3(html_file_name, os.environ.get('AWS_BUCKET'))
