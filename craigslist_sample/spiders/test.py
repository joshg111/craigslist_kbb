from scrapy.spiders import CrawlSpider, Rule
from scrapy.selector import HtmlXPathSelector
from craigslist_sample.items import CraigslistSampleItem, KbbItem
from scrapy.linkextractors import LinkExtractor
from scrapy import Request
#import logging
from subprocess import check_output
from selenium import webdriver
import re
from PIL import Image
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import os

class MySpider(CrawlSpider):
    
    name = "craigs"
        
    def __init__(self, url_list, input_args, *args, **kwargs):
        self.input_args = input_args
        self.rules = (
                Rule (LinkExtractor(restrict_xpaths=('//span/span/a[@class="hdrlnk"]')), callback=self.parse_items,  follow= True),
            )
            
        super(MySpider, self).__init__(*args, **kwargs)
            
        self.start_urls = url_list
        self.allowed_domains = ["sandiego.craigslist.org", "kbb.com"]
        print("start_urls1 = " + str(self.start_urls))
        print("input_args = " + str(input_args))
        
        self.web_driver = webdriver.PhantomJS(executable_path=r'phantomjs-2.0.0-windows\bin\phantomjs.exe')
	
    def spider_closed(self, spider):
        self.web_driver.close()
    
    def spider_type(self):
        return "MySpider"
    
    def kbb_request(self, url):
        self.web_driver.get(url)
        WebDriverWait(self.web_driver, 10).until(EC.presence_of_element_located((By.ID, "usedMarketMeter")))
        widget_id = self.web_driver.find_element_by_id("market-meter-widget-image-1")
        img_src = widget_id.get_attribute('src')        
        
        imgstr = re.search(r'base64,(.*)', img_src).group(1)
        output = open('output.png', 'wb')
        output.write(imgstr.decode('base64'))
        output.close()

        self.crop_image()
        price_list = self.tesseract()
        os.remove('output.png')
        if not price_list:
            return 0
        return price_list[0]
    
    def crop_image(self):
        box = (45, 48, 122, 68)
        
        im = Image.open("output.png")
        crop = im.crop(box)
        return crop.save("cropped_output.png")
    
    def to_int(self, price):
        return int(price.replace(',', ''))

    
    def tesseract(self):
        check_output(r'tess1\tesseract.exe cropped_output.png numbers -l kbb', shell=True)

        path = "numbers.txt"
        
        fd = open(path, 'r')
        
        price_list = sorted(map(self.to_int, re.findall("\$(\d+,*\d*)", fd.read())))
        
        return price_list
    
    def kbb_parse(self, response):
        #logging.debug("inside kbb_parse")
        craigs_item = response.meta['item']
        #logging.debug("processing request = " + str(craigs_item["kbb_url"]))
        item = KbbItem()
        
        attrs = response.xpath('//h2[@class="section-title white with-module"]')
        title = None
        items = []
        if attrs and attrs[0]:
            title = attrs[0].xpath('text()').extract()[0]
            item['title'] = title
            items.append(item)
            
            
        attrs = response.xpath('//div[@class="vehicle-styles-container clear row-white first"]//a/@href')
        if not attrs or not attrs[0]:
            #logging.warning("Failed to find style")
            return
        
        item["style"] = attrs[0].extract().replace('options/', '')
        item["url"] = "http://www.kbb.com" + item["style"] + "&condition=good&mileage=" + str(craigs_item['odometer']) + "&pricetype=private-party&printable=true"
        
        craigs_item['kbb_url'] = item["url"]

        good_condition_price = self.kbb_request(item["url"])

        if good_condition_price:            
            craigs_item['good_condition_price'] = good_condition_price
        
        if craigs_item['price'] - ((craigs_item['price'] * self.input_args.excess_price) // 100) <= good_condition_price:
            craigs_item["percent_above_kbb"] = str(int((float(craigs_item['price'] - good_condition_price) / good_condition_price) * 100)) + "%"
            yield craigs_item
    
    def download_errback(self, e):
        #logging.error("type = " + str(type(e)) + ", repr = " + str(repr(e)))
        #logging.error("value = " + str(repr(e.value)))
        pass
    
    def parse_items(self, response):
        #logging.debug("parse_items")
        request = None
        items = []
        item_set = True
        attrs = response.xpath('//p[@class="attrgroup"]/span')
        item = CraigslistSampleItem()
        item['url'] = response.url
        price_list = response.xpath('//span[@class="price"]').xpath('text()').extract()
        if not price_list:
            return
            
        item['price'] = int(price_list[0][1:].replace(',', ''))
        
        
        for i, attr in enumerate(attrs):
            span_text_list = attr.xpath('text()').extract()
            if i == 0:
                desc = attr.xpath('b/text()').extract()[0].split()
                if len(desc) >= 3:
                    item["year"] = desc[0]
                    item["make"] = desc[1]
                    item["model"] = desc[2]
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
                #print "Failed to match attribute = " + str(span_text_list)
                pass
            
        if "make" in item and "model" in item and "year" in item and "odometer" in item and \
        item['odometer'] <= self.input_args.max_miles:
            kbb_url = "http://www.kbb.com/" + item["make"] + "/" + item["model"] + "/" + item["year"] + "-" + item["make"] + "-" + item["model"] + "/styles/?intent=buy-used"
            
            kbb_url += "&bodystyle="
            if "type" in item:
                kbb_url += item["type"]
            else:
                kbb_url += "sedan"
                
            #logging.debug("kbb_url = " + str(kbb_url))
            item["kbb_url"] = kbb_url
            request = Request(item["kbb_url"], callback=self.kbb_parse, errback=self.download_errback, dont_filter=True)
            request.meta['item'] = item
            yield request
            
            
        
        
        
