import json
import os
import sys
from twisted.internet import reactor
from scrapy.crawler import Crawler
from scrapy import signals
from craigslist_sample.spiders.test import MySpider
from scrapy.utils.project import get_project_settings

class JsonWriterPipeline(object):

    def __init__(self):
        self.file = open('items.jl', 'wb')
        #self.kbb_file = open('kbb.jl', 'wb')

    #def parse_kbb(self, item):
    #    url = "http://www.kbb.com/" + item["make"] + "/" + item["model"] + "/" + item["year"] + "-" + #item["make"] + "-" + item["model"] + "/styles/?intent=buy-used" + "\n\n"
    #    self.kbb_file.write(url)
        #spider = KbbSpider(url)
            
        #settings = get_project_settings()
        #crawler = Crawler(settings)
        # Not sure about this line. 
        #crawler.signals.connect(reactor.stop, signal=signals.spider_closed)
        #crawler.configure()
        #crawler.crawl(spider)
        #crawler.start()
        
        
    def process_item(self, item, spider):
        #if spider.spider_type() == "MySpider":
        #    self.parse_kbb(item)
        #    line = json.dumps(dict(item)) + "\n"
        #    self.file.write(line)
        
        
        line = json.dumps(dict(item)) + "\n"
        self.file.write(line)
            
        return item