from scrapy.spiders import CrawlSpider, Rule
from scrapy.selector import HtmlXPathSelector
from craigslist_sample.items import CraigslistSampleItem, KbbItem
from scrapy.linkextractors import LinkExtractor
from scrapy import Request
from subprocess import check_output
import re
import time
import os


DEBUG = True
def Log(myLog):
    if DEBUG:
        print myLog


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

    def spider_closed(self, spider):
        pass

    def parse_start_url(self, response):
        cars = response.xpath('//a[@class="result-image gallery"]/@href').extract()

        for i, c in enumerate(cars):

            url = c
            # Commenting out the following, seems cars array data
            # has changed.
            # url = ""
            # if c.startswith('//'):
            #     url = 'http:' + c
            # else:
            #     url = 'http://sandiego.craigslist.org' + c

            request = Request(url, callback=self.parse_items, errback = lambda x: self.download_errback(x, url, None), dont_filter=True)
            if i <= 50:
                yield request

    def find_model(self, model):
        for sub_make_model in self.input_args.make_model:
            removed_make = sub_make_model[sub_make_model.find('+')+1:]
            removed_plus = removed_make.replace('+', '-').lower()
            if model.lower().find(removed_plus) > -1:
                final_model = removed_plus
                if removed_plus in MySpider.kbb_models:
                    final_model = MySpider.kbb_models[final_model]

                return final_model

        return None

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

        good_condition_price = int(m.group(1))
        craigs_item['good_condition_price'] = good_condition_price

        percent_above_kbb = int(((float(craigs_item['price']) / good_condition_price) - 1) * 100)
        craigs_item["percent_above_kbb"] = percent_above_kbb


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

        # Get the kbb style of the car
        attrs = response.xpath('//div[@class="vehicle-styles-container clear row-white first"]//a/@href')
        final_kbb_url = ""
        if not attrs or not attrs[0]:
            final_kbb_url = response.url.replace('options/', '')

        else:
            item["style"] = attrs[0].extract().replace('options/', '')
            final_kbb_url = "http://www.kbb.com" + item["style"]

        # Get the kbb title of the car
        attrs = response.xpath('//h2[@class="section-title white with-module"]')
        title = None
        items = []
        if attrs and attrs[0]:
            title = attrs[0].xpath('text()').extract()[0]
            item['title'] = title
            items.append(item)

        final_kbb_url += "&condition=good&mileage=" + str(craigs_item['odometer']) + "&pricetype=private-party&printable=true"
        item["url"] = final_kbb_url
        Log("final_kbb_url = " + str(final_kbb_url))
        craigs_item['kbb_url'] = final_kbb_url
        MySpider.kbb_parsed += 1
        craigs_item['id'] = MySpider.kbb_parsed
        request = Request(craigs_item["kbb_url"], callback=self.kbb_final_parse, errback = lambda x: self.download_errback(x, craigs_item["kbb_url"], response.url), dont_filter=True)
        request.meta['item'] = craigs_item
        yield request


    def download_errback(self, e, kbb_url, craigs_url):
        MySpider.download_failures += 1
        pass

    def parse_items(self, response):
        if MySpider.found_cars > 50:
            return


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
        item['location'] = response.xpath('//span[@class="postingtitletext"]/small').xpath('text()').extract()[0]

        for i, attr in enumerate(attrs):
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


        if "make" in item and "model" in item and "year" in item and "odometer" in item and \
        item['odometer'] <= self.input_args.max_miles:
            model_str = '-'.join([str(i) for i in item["model"]])
            model_str = self.find_model(model_str)


            kbb_url = "http://www.kbb.com/" + item["make"] + "/" + model_str + "/" + item["year"] + "-" + item["make"] + "-" + model_str + "/styles/?intent=buy-used"

            if "type" in item:
                kbb_url += "&bodystyle="
                kbb_url += item["type"]

            item["kbb_url"] = kbb_url
            Log("kbb_url = " + str(kbb_url))
            request = Request(item["kbb_url"], callback=self.kbb_parse, errback = lambda x: self.download_errback(x, item["kbb_url"], response.url), dont_filter=True)
            request.meta['item'] = item
            MySpider.found_cars += 1
            Log("found_cars = " + str(MySpider.found_cars))
            yield request

        else:
            MySpider.dropped_cars += 1
            Log("dropped_cars = " + str(MySpider.dropped_cars))
