import os
import sys
from twisted.internet import reactor
#from scrapy.crawler import Crawler
from scrapy.crawler import CrawlerProcess
from scrapy.crawler import CrawlerRunner
from scrapy import signals
from craigslist_sample.spiders.test import MySpider
from scrapy.utils.project import get_project_settings
import argparse
import logging


TRANSMISSION = {'automatic': '2', 'manual': '1'}

def setup_crawler(spider_type, url_list, args):
    spider = None
    if spider_type == MySpider:
        #spider = spider_type(url_list, input_args=args)
        pass
        
    settings = get_project_settings()
    crawler = CrawlerProcess(settings)
    #crawler.signals.connect(reactor.stop, signal=signals.spider_closed)
    #crawler.configure()
    #crawler.crawl(spider, [], {})
    crawler.crawl('craigs', url_list, args)
    #d.addBoth(lambda _: reactor.stop())
    crawler.start()
    #d.addBoth(lambda _: reactor.stop())
    #reactor.run()

def build_craigs_url(args):
    base_url = "http://sandiego.craigslist.org/search/cto?sort=date&hasPic=1&auto_title_status=1&auto_fuel_type=1"
    make_model_list = args.make_model
    min_price = str(args.min_price)
    max_price = str(args.max_price)
    min_year = str(args.min_year)
    max_year = str(args.max_year)
    min_miles = str(args.min_miles)
    max_miles = str(args.max_miles)
    
    url_list = []
    print("make_model_list = " + str(make_model_list))
    for make_model in make_model_list:
        url = base_url
        if args.transmission:
            url += "&auto_transmission=" + TRANSMISSION[args.transmission]
        
        url += "&min_price=" + min_price + "&max_price=" + max_price + "&auto_make_model=" + make_model + "&min_auto_year=" + min_year + "&max_auto_year=" + max_year + "&min_auto_miles=" + min_miles + "&max_auto_miles=" + max_miles
        
        url_list.append(url)
  
    return url_list

def get_args():
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter, description="Find deals on craigslist cars by comparing the price to kelley blue book.")
    parser.add_argument("make_model", nargs='+', help="The make model of the cars. Models are optional. Ex: Toyota Honda+Civic Nissan+Altima")
    parser.add_argument("-e", "--excess_price", type=int, default=15, choices=xrange(100), metavar="[0-99]", help="The maximum percentage the craigslist price can exceed the kelley blue book price.")
    parser.add_argument("--min_price", type=int, default=0, help="The minimum price of the car.")
    parser.add_argument("--max_price", type=int, default=11000, help="The maximum price of the car.")
    parser.add_argument("--min_year", type=int, default=2000, help="The minimum year of the car.")
    parser.add_argument("--max_year", type=int, default=2014, help="The maximum year of the car.")
    parser.add_argument("--min_miles", type=int, default=0, help="The minimum number of miles on the car.")
    parser.add_argument("--max_miles", type=int, default=140000, help="The maximum number of miles on the car.")
    parser.add_argument("--transmission", choices=["automatic", "manual"], default="automatic", help="The transmission type of the car.")
    
    args = parser.parse_args()
    return args

def main():
    #logging.basicConfig(format='%(asctime)s %(filename)s:%(lineno)s %(levelname)s:%(message)s'
#, filename='log.log', level=logging.DEBUG)
    #logging.debug("main method")
    args = get_args()
    url_list = build_craigs_url(args)
    # For type in spider_types:
    setup_crawler(MySpider, url_list, args)
    
    #log.start()
    # The script will block here until the spider_closed signal was sent
    #reactor.run() 
    print "\n\nspiders finished crawling\n\n"

if __name__ == "__main__":
    main()
    

