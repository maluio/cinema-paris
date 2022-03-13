import datetime
import json

import scrapy
from jinja2 import Template
from scrapy.crawler import CrawlerProcess


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
                        'url': cinema.css("a::attr(href)").get(),
                        'show_times': []
                    }
                    session_dates = reservation.css('.session-date')
                    for sd in session_dates:
                        day = sd.css('.sessionDate::text').get().strip()
                        time = sd.css('.time::text').get().strip()
                        cinema['show_times'].append(self.parse_show_time(day, time).isoformat())
                    cinemas.append(cinema)
            yield {
                'movie': {'title': movie_title},
                'cinemas': cinemas
            }

        next_page = response.css('.pagination')[0].css('.current + .page a::attr("href")').get()
        if next_page is not None:
            yield response.follow(next_page, self.parse)


if __name__ == '__main__':
    # Run Scrapy from a script: https://docs.scrapy.org/en/latest/topics/practices.html#run-from-script
    # Built-in settings reference: https://docs.scrapy.org/en/latest/topics/settings.html#topics-settings-ref
    process = CrawlerProcess(settings={
        "FEEDS": {
            "movies.json": {"format": "json"},
        },
    })

    process.crawl(MoviesSpider)
    process.start()

    with open('movies.json', 'r') as f:
        movies = json.load(f)

    with open('cinema.jinja2', 'r') as t:
        template = Template(t.read())

    with open('cinema.html', 'w') as t:
        t.write(template.render(movies=movies))
