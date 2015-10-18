import re
from subprocess import check_output
from selenium import webdriver
from PIL import Image
import logging
from selenium.webdriver.common.keys import Keys
import ctypes
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time

def kbb_request():
    image_file_name = 'output.png'
    #driver = webdriver.Firefox()
    driver = webdriver.PhantomJS(executable_path=r'phantomjs-2.0.0-windows\bin\phantomjs.exe')
    
    url = 'http://www.kbb.com/honda/accord/2001-honda-accord/dx-sedan-4d/?vehicleid=4387&intent=buy-used&category=sedan&condition=good&mileage=130000&pricetype=private-party&printable=true'
    
    driver.get(url)
    widget_id = driver.find_element_by_id("market-meter-widget-image-1")
    
    img_src = widget_id.get_attribute('src')
    
    imgstr = re.search(r'base64,(.*)', img_src).group(1)
    output = open(image_file_name, 'wb')
    output.write(imgstr.decode('base64'))
    output.close()
    
    driver.close()
    
    crop_image()
    tess1(image_file_name)
    
def to_int(price):
    res = price.replace(',', '')
    res = res.replace('.', '')
    return int(res)

    
def tesseract():
    check_output(r'C:"\Program Files (x86)"\Tesseract-OCR\tesseract.exe new.png numbers', shell=True)

    path = "numbers.txt"
    
    fd = open(path, 'r')
    
    m = sorted(map(to_int, re.findall("\$(\d+[,|.]\d+)", fd.read())))[1]
    
    print m   

def tess1(image_file_name):
    check_output(r'tess1\tesseract.exe -l kbb ' + image_file_name + ' numbers', shell=True)
    path = "numbers.txt"
    fd = open(path, 'r')
    #m = to_int(re.findall("\$(\d+[,|.]\d+)", fd.read())[0])
    m = to_int(re.findall("\$(\d+,*\d*)", fd.read())[0])
    
    print m   
    
def crop_image():
    box = (45, 48, 122, 68)
    
    im = Image.open("output.png")
    crop = im.crop(box)
    return crop.save("output.png")
   
def test_ghost_driver():
    driver = webdriver.PhantomJS(executable_path=r'phantomjs-2.0.0-windows\bin\phantomjs.exe')
    driver.get("http://www.google.com")
    print driver.title
    print driver.current_url
   
def main():
    tess1('output.png')
    #tess1("cropped_output.png")
    #test_ghost_driver()
    


if __name__ == "__main__":
    main()