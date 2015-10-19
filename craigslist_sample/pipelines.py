import json
import os
import sys
from twisted.internet import reactor
from scrapy.crawler import Crawler
from scrapy import signals
from craigslist_sample.spiders.test import MySpider
from scrapy.utils.project import get_project_settings
from subprocess import check_output
from selenium import webdriver
import re
from PIL import Image
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import threading

threadLock = threading.Lock()
FILE = open('items.jl', 'wb')

class KbbParser(object):
    def __init__(self, file_id):
        self.file_id = file_id
        
    def kbb_request(self, url):
        web_driver = webdriver.PhantomJS(executable_path=r'phantomjs-2.0.0-windows\bin\phantomjs.exe')
        web_driver.get(url)
        print("url = " + url)
        #WebDriverWait(web_driver, 8).until(EC.presence_of_element_located((By.ID, "usedMarketMeter")))
        widget_id = web_driver.find_element_by_id("market-meter-widget-image-1")
        img_src = widget_id.get_attribute('src')
        web_driver.quit()
        imgstr = re.search(r'base64,(.*)', img_src).group(1)
        output = open('output' + str(self.file_id) + '.png', 'wb')
        output.write(imgstr.decode('base64'))
        output.close()

        self.crop_image()
        price_list = self.tesseract()
        os.remove('output' + str(self.file_id) + '.png')
        if not price_list:
            return 0
        return price_list[0]

    def crop_image(self):
        box = (45, 48, 122, 68)
        im = Image.open('output' + str(self.file_id) + '.png')
        crop = im.crop(box)
        crop.save("cropped_output" + str(self.file_id) + ".png")
        #im.close()
        
    def to_int(self, price):
        return int(price.replace(',', ''))

    def tesseract(self):
        check_output(r'tess1\tesseract.exe ' + "cropped_output" + str(self.file_id) + ".png" + ' numbers' + str(self.file_id) + ' -l kbb', shell=True)
        path = "numbers" + str(self.file_id) + ".txt"
        fd = open(path, 'r')
        price_list = sorted(map(self.to_int, re.findall("\$(\d+,*\d*)", fd.read())))
        fd.close()
        os.remove(path)
        os.remove("cropped_output" + str(self.file_id) + ".png")
        return price_list

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
        res = self.kbb_parser.kbb_parse(self.craigs_item, self.excess_price)
        threadLock.acquire()
        if res:
            line = json.dumps(dict(res)) + "\n"
            FILE.write(line)
            
        threadLock.release()

class JsonWriterPipeline(object):

    def __init__(self):
        pass
        
    def process_item(self, item, spider):
        t = MyThread(item, spider.input_args.excess_price)
        t.start()
    
        #res = self.kbb_parse(item, spider.input_args.excess_price)
        
        #if res:
        #    line = json.dumps(dict(item)) + "\n"
        #    self.file.write(line)
        #    return item
            
        #return res
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        