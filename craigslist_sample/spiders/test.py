from scrapy.spiders import CrawlSpider, Rule
from scrapy.selector import HtmlXPathSelector
from craigslist_sample.items import CraigslistSampleItem, KbbItem
from scrapy.linkextractors import LinkExtractor
from scrapy import Request
from subprocess import check_output
import re
import time
import os
from utils.prisma_gql import *
from utils.find_style import *


PARSED_NUM = 0
DEBUG = True
def Log(myLog):
    if DEBUG:
        print myLog


def aggregate_item(car):
    item = CraigslistSampleItem()

    for i in car.iterkeys():
        item[i] = car[i]

    return item


def remove_nearby_cars(rsp):
    '''Craigslist returns nearby locations when the number of car results
    is less than the 100.'''
    body = rsp.body
    pos = body.find('Here are some from nearby areas')
    if pos < 0:
        print "Nearby cars not found."
    else:
        print "Nearby cars were found."
        body = body[:pos]
        return rsp.replace(body=body)

    return rsp


class MySpider(CrawlSpider):

    name = "craigs"
    kbb_models = {
        "land-cruiser-wagon": "land-cruiser"
    }
    dropped_cars = 0
    found_cars = 0
    download_failures = 0
    kbb_parsed = 0

    def __init__(self, url_list, input_args, *args, **kwargs):
        self.input_args = input_args
        # self.rules = (
        #         Rule (LinkExtractor(restrict_xpaths=('//a[@class="result-image gallery"]')), callback=self.parse_items,  follow= True),
        #     )

        super(MySpider, self).__init__(*args, **kwargs)

        print "url_list = ", url_list

        self.start_urls = url_list
        self.allowed_domains = ["craigslist.org", "kbb.com"]
        self.cacheClient = GqlClient()

    def spider_closed(self, spider):
        pass

    def parse_start_url(self, response):

        response = remove_nearby_cars(response)
        print "encoding = " + str(response.encoding)
        cars = response.xpath('//a[@class="result-image gallery"]/@href').extract()
        Log("Number of craigslist cars to crawl = " + str(len(cars)))

        for i, url in enumerate(cars[:30]):

            # Check cache
            # car = self.find_cached_car(url)
            # if car["car"]:
            #     item = aggregate_item(car["car"])
            #     yield item
            #
            # else:
                # request = Request(url, callback=self.parse_items, errback = lambda x: self.download_errback(x, url, None), dont_filter=True)
                # yield request


            request = Request(url, callback=self.parse_items, errback = lambda x: self.download_errback(x, url, None), dont_filter=True)
            yield request



    def find_style_by_desc(self, desc):
        model = self.find_model_by_desc(desc).lower()
        desc = desc.lower()
        if desc.find(model) > -1:
            return desc[desc.find(model) + len(model):]

        return None

    def find_model_by_desc(self, desc):
        ''' Return a hyphenated version of the model which is consumed by kbb '''

        for sub_make_model in self.input_args.make_model:
            input_make_model = " ".join(sub_make_model.split('+')[1:])

            if desc.lower().find(input_make_model.lower()) > -1:
                final_model = input_make_model
                return final_model

        return None


    def find_kbb_model(self, model):
        ''' Return a hyphenated version of the model which is consumed by kbb '''
        for sub_make_model in self.input_args.make_model:
            removed_make = sub_make_model[sub_make_model.find('+')+1:]
            removed_plus = removed_make.replace('+', '-').lower()
            if model.lower().find(removed_plus) > -1:
                final_model = removed_plus
                if removed_plus in MySpider.kbb_models:
                    final_model = MySpider.kbb_models[final_model]

                return final_model

        return None

    def put_cache(self, craigs_item):
        self.cacheClient.put(craigs_item)

    def find_cached_car(self, craigs_url):
        return self.cacheClient.get(craigs_url)

    def kbb_final_parse(self, response):
        Log("kbb_final_parse")
        craigs_item = response.meta['item']
        page = response.body
        # 3/27/18: The following regex no longer works
        # m = re.search('defaultprice\': \'(\d*)\'', page)
        m = re.search('defaultprice%22%3a(\d*)', page)
        if m == None:
            Log("failed to find final price")
            return

        Log("kbb_final_parse url = " + response.url)
        Log(m.group(1))
        good_condition_price = int(m.group(1))
        craigs_item['good_condition_price'] = good_condition_price

        percent_above_kbb = int(((float(craigs_item['price']) / good_condition_price) - 1) * 100)
        craigs_item["percent_above_kbb"] = percent_above_kbb

        self.put_cache(craigs_item)

        # if percent_above_kbb > self.input_args.excess_price:
        #     return
        Log("kbb_final_parse: Returning item")
        yield craigs_item


    def kbb_parse(self, response):
        Log("kbb_parse")
        craigs_item = response.meta['item']
        item = KbbItem()

        # Get the kbb style type of the car, optional.
        attrs = response.xpath('//div[@class="mod-single"]')
        if attrs:
            attrs = response.xpath('//div[@class="mod-category-inner"]//a/@href')
            if attrs and attrs[0]:
                craigs_item["kbb_url"] = "http://www.kbb.com" + attrs[0].extract()
                request = Request(craigs_item["kbb_url"], callback=self.kbb_parse, errback = lambda x: self.download_errback(x, craigs_item["kbb_url"], response.url), dont_filter=True)
                request.meta['item'] = craigs_item
                yield request
                return

        attrs = find_style(response, craigs_item["style"])
        # Get the kbb style of the car
        # attrs = response.xpath('//div[@class="vehicle-styles-container clear row-white first"]//a/@href')
        final_kbb_url = ""
        if not attrs:
            final_kbb_url = response.url.replace('options/', '')

        else:
            item["style"] = attrs.replace('options/', '')
            final_kbb_url = "http://www.kbb.com" + item["style"]
            Log("Found kbb style = " + item["style"])

        # Get the kbb title of the car
        attrs = response.xpath('//h2[@class="section-title white with-module"]')
        title = None
        items = []
        if attrs and attrs[0]:
            title = attrs[0].xpath('text()').extract()[0]
            item['title'] = title
            items.append(item)

        # final_kbb_url += "&condition=good&mileage=" + str(craigs_item['odometer']) + "&pricetype=private-party&printable=true"
        final_kbb_url += "&condition=good&mileage=" + str(craigs_item['odometer']) + "&pricetype=private-party"
        item["url"] = final_kbb_url
        Log("final_kbb_url = " + str(final_kbb_url))
        craigs_item['kbb_url'] = final_kbb_url
        MySpider.kbb_parsed += 1
        request = Request(craigs_item["kbb_url"], callback=self.kbb_final_parse, errback = lambda x: self.download_errback(x, craigs_item["kbb_url"], response.url), dont_filter=True)
        request.meta['item'] = craigs_item
        yield request


    def download_errback(self, e, kbb_url, craigs_url):
        MySpider.download_failures += 1
        Log("Download failures = " + str(MySpider.download_failures) + ", err = " + str(e) + ", kbb url = " + str(kbb_url) + ", craigs_url = " + craigs_url)
        pass

    def parse_items(self, response):
        global PARSED_NUM
        PARSED_NUM += 1
        Log("parsed items = " + str(PARSED_NUM))

        kbb_url = ""
        request = None
        items = []
        item_set = True
        attrs = response.xpath('//p[@class="attrgroup"]/span')
        item = CraigslistSampleItem()
        item['url'] = response.url
        price_list = response.xpath('//span[@class="price"]').xpath('text()').extract()
        if not price_list:
            Log("Failed to find price_list")
            return

        price = str(price_list[0][1:].replace(',', ''))
        if len(price) < 3 and len(price) > 0:
            price += "000"
        item['price'] = int(price)
        pic = response.xpath('//div[@class="slide first visible"]/img/@src')[0].extract()
        item['thumbnail'] = pic
        location = response.xpath('//span[@class="postingtitletext"]/small').xpath('text()').extract()
        item['location'] = location[0] if location else None
        timeago = response.xpath('//div[@class="postinginfos"]//time/@datetime').extract()
        item['timeago'] = timeago[0] if timeago else None

        for i, attr in enumerate(attrs):
            if i == 0:
                Log("Processing craigs attributes")

            span_text_list = attr.xpath('text()').extract()
            if i == 0:
                desc = attr.xpath('b/text()').extract()[0].split()
                if len(desc) >= 3:
                    item["year"] = desc[0]
                    item["make"] = desc[1]
                    item["model"] = desc[2:]
                    item["desc"] = ' '.join(desc)


            elif span_text_list and span_text_list[0].find("odometer") > -1:
                odometer = attr.xpath('b/text()').extract()[0]
                if len(odometer) <= 3:
                    odometer += "000"
                item["odometer"] = int(odometer)
            elif span_text_list and span_text_list[0].find("cylinders") > -1:
                item["cylinders"] = int(attr.xpath('b/text()').extract()[0].split()[0])

            elif span_text_list and span_text_list[0].find("condition") > -1:
                item["condition"] = attr.xpath('b/text()').extract()[0].split()[0]

            elif span_text_list and span_text_list[0].find("type") > -1:
                item["type"] = attr.xpath('b/text()').extract()[0].split()[0]

            else:
                pass


        Log("Done craigs attributes")

        if "make" in item and "model" in item and "year" in item and "odometer" in item and \
        item['odometer'] <= self.input_args.max_miles:

            MySpider.found_cars += 1
            Log("found_cars = " + str(MySpider.found_cars))
            Log("Processing valid item")

            model_str = '-'.join([str(i) for i in item["model"]])
            model_str = self.find_kbb_model(model_str)
            item["model"] = model_str
            item["style"] = self.find_style_by_desc(item["desc"])
            Log("craigslist style = " + str(item["style"]))

            kbb_url = "http://www.kbb.com/" + item["make"] + "/" + model_str + "/" + item["year"] + "-" + item["make"] + "-" + model_str + "/styles/?intent=buy-used"

            if "type" in item:
                kbb_url += "&bodystyle="
                kbb_url += item["type"]

            item["kbb_url"] = kbb_url
            Log("kbb_url = " + str(kbb_url))

            # Check cache
            car = self.find_cached_car(item["url"])
            if car["car"]:
                item = aggregate_item(car["car"])
                yield item

            else:
                # Build request
                request = Request(item["kbb_url"], callback=self.kbb_parse, errback = lambda x: self.download_errback(x, item["kbb_url"], response.url), dont_filter=True)
                request.meta['item'] = item
                yield request

        else:
            MySpider.dropped_cars += 1
            Log("dropped_cars = " + str(MySpider.dropped_cars))
