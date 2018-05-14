import os
import sys

here = os.path.dirname(os.path.realpath(__file__))
#sys.path.append(os.path.join(here, "./site-packages"))
sys.path.append(os.path.join(here, "./p/lib-site-packages"))
sys.path.append(os.path.join(here, "./p/lib64-site-packages"))
sys.path.append(os.path.join(here, "./p/dist-packages"))
sys.path.append(os.path.join(here, "./craigslist_sample"))
sys.path.append(os.path.join(here, "./craigslist_sample/spiders"))

from scrapy.crawler import CrawlerProcess
from scrapy.crawler import CrawlerRunner
from scrapy import signals
from craigslist_sample.spiders.test import MySpider
from scrapy.utils.project import get_project_settings
import argparse
import json
import time
from twisted.internet import reactor
from multiprocessing import Process, Pipe


DEBUG = True
def Log(myLog):
    if DEBUG:
        print myLog

TRANSMISSION = {'automatic': '2', 'manual': '1'}
RESULT = []

def my_handler():
    print "engine started"
    pass

def scraped_handler(item):
    global RESULT
    Log("scraped_handler")
    if item != None:
        RESULT.append(dict(item))


def run_process(url_list, my_args):
    processes = []
    parent_conn, child_conn = Pipe()
    process = Process(target=setup_crawler, args=(url_list, my_args, child_conn))

    process.start()
    process.join()
    return parent_conn.recv()


def setup_crawler(url_list, args, conn):

    settings = get_project_settings()

    # runner = CrawlerRunner(settings)
    crawler = CrawlerProcess(settings)


    d = crawler.crawl('craigs', url_list, args)
    d.addBoth(lambda _: reactor.stop())

    # my_crawler = next(iter(runner.crawlers))
    my_crawler = next(iter(crawler.crawlers))
    my_crawler.signals.connect(my_handler, signals.engine_started)
    my_crawler.signals.connect(scraped_handler, signals.item_scraped)

    # reactor.run()
    crawler.start()
    # crawler.stop()

    conn.send(RESULT)
    conn.close()


def build_craigs_url(args):

    make_model_list = args.make_model
    min_price = str(args.min_price)
    max_price = str(args.max_price)
    min_year = str(args.min_year)
    max_year = str(args.max_year)
    min_miles = str(args.min_miles)
    max_miles = str(args.max_miles)
    city = str(args.city)
    base_url = "http://" + city + ".craigslist.org/search/cto?sort=date&hasPic=1&auto_title_status=1&auto_fuel_type=1"

    url_list = []
    for make_model in make_model_list:
        url = base_url
        if args.transmission:
            url += "&auto_transmission=" + TRANSMISSION[args.transmission]

        url += "&min_price=" + min_price + "&max_price=" + max_price + "&auto_make_model=" + make_model + "&min_auto_year=" + min_year + "&max_auto_year=" + max_year + "&min_auto_miles=" + min_miles + "&max_auto_miles=" + max_miles

        url_list.append(url)

    return url_list

def get_args(my_args=[]):
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter, description="Find deals on craigslist cars by comparing the price to kelley blue book.")
    parser.add_argument("--make_model", nargs='*', default=["toyota+camry"], help="The make model of the cars. Models are optional. Ex: Honda Nissan+Altima toyota+land+cruiser+wagon. This example will search on all Honda's, Nissan Altimas, and Toyota land cruiser wagon's")
    parser.add_argument("-e", "--excess_price", type=int, default=15, choices=xrange(100), metavar="[0-99]", help="The maximum percentage the craigslist price can exceed the kelley blue book price.")
    parser.add_argument("--min_price", type=int, default=0, help="The minimum price of the car.")
    parser.add_argument("--max_price", type=int, default=20000, help="The maximum price of the car.")
    parser.add_argument("--min_year", type=int, default=2000, help="The minimum year of the car.")
    parser.add_argument("--max_year", type=int, default=2020, help="The maximum year of the car.")
    parser.add_argument("--min_miles", type=int, default=0, help="The minimum number of miles on the car.")
    parser.add_argument("--max_miles", type=int, default=200000, help="The maximum number of miles on the car.")
    parser.add_argument("--transmission", choices=["automatic", "manual"], default="automatic", help="The transmission type of the car.")
    parser.add_argument("--city", default="sandiego", help="The craigslist city, eg. sandiego, sfbay")

    if my_args:
        args = parser.parse_args(my_args)
    else:
        args = parser.parse_args()
    return args

def entry_point(event, context):
    start = time.time()
    my_args = []
    if event:
        # Convert event dict to flatten list.
        for k,v in event.iteritems():
            my_args.append(k)
            my_args.append(v)

    args = get_args(my_args)
    url_list = build_craigs_url(args)

    # setup_crawler(url_list, args)
    res = run_process(url_list, args)

    # Sort the results
    res = sorted(res, key=lambda o: float(o["percent_above_kbb"]))
    Log("Result length = " + str(len(res)))
    Log("Time Elapsed = " + str(time.time() - start))
    # f = open("items.jl", 'r')
    # body = {
    #     "message": f.read()
    # }
    #
    # f.close()

    # response = {
    #     "statusCode": 200,
    #     "body": str(url_list)
    # }

    # response = {
    #     "statusCode": 200,
    #     # "body": RESULT
    #     "body": res
    # }

    return res


if __name__ == "__main__":
    sys.stdout.write(str(entry_point(None, None)))
    # sys.stdout.write(json.dumps({1:2, 3:4}))
