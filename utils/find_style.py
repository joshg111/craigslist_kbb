import unittest
import httplib
from scrapy.http import TextResponse, Request
from urlparse import urlparse


DEBUG = True
def Log(x):
    if DEBUG:
        print x

def find_style(response, craigs_style):
    '''Tries to find the style based on the given craigslist style.
    If it can't find the style, then the first style is returned'''

    Log("find_style: response = " + str(response))
    Log("find_style: craigs_style = " + str(craigs_style))
    default_style = None
    attrs = response.xpath('//div[contains(@class, "js-style-container")]//a[contains(@class, "style-link")]')

    if attrs and attrs[0]:
        default_style = attrs[0].xpath('./@href')[0].extract()
        if not craigs_style:
            return default_style

        craigs_style = craigs_style.strip()

        for style_container in attrs:
            style = style_container.xpath('.//div[@class="button-header"]/text()')[0].extract()
            Log("style = " + str(style))
            if style:
                style_name = style.strip()
                Log('kbb style_name = ' + style_name)
                # Log("Matching kbb style = " + style_name + ", matching craigs style = " + craigs_style)
                if craigs_style.lower().split(' ')[0] in [i.lower() for i in style_name.split(' ')]:
                    Log("Matched craigs style = " + craigs_style + ", with kbb style = " + style_name)
                    # Found the kbb style that matches the craigslist style
                    return style_container.xpath('./@href')[0].extract()

    return default_style



class TestFindStyle(unittest.TestCase):
    def setUp(self):
        pass

    def create_response(self, url):
        print url
        parsed = urlparse(url)
        domain = parsed.netloc
        path_params = parsed.path + '?' + parsed.query
        conn = httplib.HTTPSConnection(domain)
        conn.request("GET", path_params, headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/64.0.3282.167 Safari/537.36'})
        resp = conn.getresponse()
        body = resp.read()
        result = TextResponse(url = url, request = Request(url), body = body)
        # result.encoding = 'utf-8'
        return result


    def test_a(self):
        # self.assertTrue(self.client.get("a")["car"] == None)
        print "res = " + find_style(self.create_response('https://www.kbb.com/toyota/camry/2005/styles/?intent=buy-used'), 'se')
        pass

    def test_b(self):
        print "res = " + find_style(self.create_response('https://www.kbb.com/toyota/camry/2017/styles/?intent=buy-used'), 'se')


if __name__ == '__main__':
    unittest.main()
