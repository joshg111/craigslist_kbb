import urllib2
import json
import os
import sys
# from twisted.internet import reactor
from scrapy.crawler import Crawler
from scrapy import signals
from craigslist_sample.spiders.test import MySpider
from scrapy.utils.project import get_project_settings
from subprocess import check_output
import re
# from PIL import Image
import threading

threadLock = threading.Lock()
FILE = open('items.jl', 'wb')
result = []

class KbbParser(object):
    def __init__(self, file_id):
        self.file_id = file_id

    def kbb_request(self, url):
        user_agent = 'Mozilla/5.0 (Macintosh; U; Intel Mac OS X 10_6_4; en-US) AppleWebKit/534.3 (KHTML, like Gecko) Chrome/6.0.472.63 Safari/534.3'
        headers = { 'User-Agent' : user_agent }
        req = urllib2.Request(url, None, headers)
        response = urllib2.urlopen(req)
        page = response.read()
        response.close() # its always safe to close an open connection

        m = re.search('defaultprice\': \'(\d*)\'', page)
        if m == None:
            return 0

        return int(m.group(1))

    def kbb_parse(self, craigs_item, excess_price):
        print("kbb_parse(...)")
        final_kbb_url = craigs_item['kbb_url']
        res_item = craigs_item
        ###################################################################################################
        good_condition_price = self.kbb_request(final_kbb_url)
        print("kbb_price = " + str(good_condition_price))

        if good_condition_price:
            res_item['good_condition_price'] = good_condition_price

        print("after set good price")

        percent_above_kbb = int(((float(craigs_item['price']) / good_condition_price) - 1) * 100)
        res_item["percent_above_kbb"] = str(percent_above_kbb) + "%"

        print("percent above kbb = " + str(percent_above_kbb))

        if percent_above_kbb <= excess_price:
            return res_item

        return None

class MyThread(threading.Thread):
    def __init__(self, item, excess_price):
        threading.Thread.__init__(self)
        self.craigs_item = item
        self.excess_price = excess_price
        self.kbb_parser = KbbParser(item['id'])

    def run(self):
        # global result
        res = (self.kbb_parser.kbb_parse(self.craigs_item, self.excess_price))

        # threadLock.acquire()
        # result.append(line)
        # threadLock.release()

        threadLock.acquire()
        if res:
            line = json.dumps(dict(res)) + "\n"
            FILE.write(line)

        threadLock.release()

class JsonWriterPipeline(object):

    def __init__(self):
        print "JsonWriterPipeline"
        pass

    # def close_spider(self, spider):
    #     global result
    #     global FILE
    #     print "closing spider!!!"
    #     print "result = " + str(result)
    #     FILE.write(json.dumps(result))

    def process_item(self, item, spider):
        print "process_item"
        t = MyThread(item, spider.input_args.excess_price)
        t.start()

        #res = self.kbb_parse(item, spider.input_args.excess_price)

        #if res:
        #    line = json.dumps(dict(item)) + "\n"
        #    self.file.write(line)
        #    return item

        #return res
