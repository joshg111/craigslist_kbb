# -*- coding: utf-8 -*-

# Scrapy settings for craigslist_sample project
#
# For simplicity, this file contains only the most important settings by
# default. All the other settings are documented here:
#
#     http://doc.scrapy.org/en/latest/topics/settings.html
#

BOT_NAME = 'craigslist_sample'

SPIDER_MODULES = ['craigslist_sample.spiders']
NEWSPIDER_MODULE = 'craigslist_sample.spiders'
# ITEM_PIPELINES = {
#     'craigslist_sample.pipelines.JsonWriterPipeline': 800,
# }

LOG_FILE = 'log.log'
LOG_LEVEL = 'DEBUG'
LOG_ENABLED = False
#COOKIES_ENABLED = False
DOWNLOAD_DELAY = 0
# USER_AGENT = "Mozilla/5.0 (Windows NT 6.3; rv:36.0) Gecko/20100101 Firefox/36.0"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/64.0.3282.167 Safari/537.36"
# RETRY_HTTP_CODES = [500, 502, 503, 504, 400, 403, 404, 408, 301]
# Crawl responsibly by identifying yourself (and your website) on the user-agent
#USER_AGENT = 'craigslist_sample (+http://www.yourdomain.com)'
CONCURRENT_ITEMS = 300
CONCURRENT_REQUESTS = 300
CONCURRENT_REQUESTS_PER_DOMAIN = 300
REACTOR_THREADPOOL_MAXSIZE = 100
DNSCACHE_ENABLED = True
DNSCACHE_SIZE = 100000
DOWNLOADER_STATS = True
DOWNLOAD_TIMEOUT = 30
RETRY_ENABLED = False
