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
    kbb_models = {
        "land-cruiser-wagon": "land-cruiser"
    }
    dropped_cars = 0
    found_cars = 0
    download_failures = 0
    
    def __init__(self, url_list, input_args, *args, **kwargs):
        self.input_args = input_args
        self.rules = (
                Rule (LinkExtractor(restrict_xpaths=('//span/span/a[@class="hdrlnk"]')), callback=self.parse_items,  follow= True),
            )
            
        super(MySpider, self).__init__(*args, **kwargs)
            
        self.start_urls = url_list
        self.allowed_domains = ["craigslist.org", "kbb.com"]
        print("\nstart_urls = " + str(self.start_urls) + "\n")
        print("input_args = " + str(input_args) + "\n\n")
        
        self.web_driver = webdriver.PhantomJS(executable_path=r'phantomjs-2.0.0-windows\bin\phantomjs.exe')
	
    def spider_closed(self, spider):
        self.web_driver.close()
        print "Dropped cars = " + str(MySpider.dropped_cars)
    
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
        craigs_item = response.meta['item']
        item = KbbItem()
        
        attrs = response.xpath('//h2[@class="section-title white with-module"]')
        title = None
        items = []
        if attrs and attrs[0]:
            title = attrs[0].xpath('text()').extract()[0]
            item['title'] = title
            items.append(item)
            
        attrs = response.xpath('//div[@class="vehicle-styles-container clear row-white first"]//a/@href')
        final_kbb_url = ""
        if not attrs or not attrs[0]:
            final_kbb_url = response.url.replace('options/', '')

        else:
            item["style"] = attrs[0].extract().replace('options/', '')
            final_kbb_url = "http://www.kbb.com" + item["style"]
        
        final_kbb_url += "&condition=good&mileage=" + str(craigs_item['odometer']) + "&pricetype=private-party&printable=true"
        item["url"] = final_kbb_url
        craigs_item['kbb_url'] = final_kbb_url
        good_condition_price = self.kbb_request(final_kbb_url)

        if good_condition_price:            
            craigs_item['good_condition_price'] = good_condition_price
        
        percent_above_kbb = int(((float(craigs_item['price']) / good_condition_price) - 1) * 100)
        craigs_item["percent_above_kbb"] = str(percent_above_kbb) + "%"
        
        if percent_above_kbb <= self.input_args.excess_price:
            yield craigs_item
    
    def download_errback(self, e, kbb_url, craigs_url):
        #print("type = " + str(type(e)) + ", repr = " + str(repr(e)))
        #print("Error downloading" + str(e))
        MySpider.download_failures += 1
        print "Download failures = " + str(MySpider.download_failures)
        print("value = " + str(repr(e.value)))
        print("kbb_url = " + str(kbb_url))
        print("craigs_url = " + str(craigs_url))
        pass
    
    def parse_items(self, response):
        kbb_url = ""
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
                    item["model"] = desc[2:]
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
            model_str = '-'.join([str(i) for i in item["model"]])
            if model_str.lower() in MySpider.kbb_models:
                model_str = MySpider.kbb_models[model_str]
                
            kbb_url = "http://www.kbb.com/" + item["make"] + "/" + model_str + "/" + item["year"] + "-" + item["make"] + "-" + model_str + "/styles/?intent=buy-used"
            kbb_url += "&bodystyle="
            if "type" in item:
                kbb_url += item["type"]
            else:
                kbb_url += "sedan"
                
            item["kbb_url"] = kbb_url
            request = Request(item["kbb_url"], callback=self.kbb_parse, errback = lambda x: self.download_errback(x, item["kbb_url"], response.url), dont_filter=True)
            request.meta['item'] = item
            MySpider.found_cars += 1
            print "Found cars = " + str(MySpider.found_cars)
            print "Response = " + str(response.url)
            yield request
            
        else:
            #print "Didn't find all attributes for this vehicle"
            MySpider.dropped_cars += 1
            print "Dropped cars = " + str(MySpider.dropped_cars)
            print "Response = " + str(response.url)
            for i in item:
                print "i = " + str(i)
                
        
        
