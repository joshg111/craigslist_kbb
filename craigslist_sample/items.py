import scrapy
from scrapy.item import Item, Field

class CraigslistSampleItem(scrapy.Item):
    price = Field()
    url = Field()
    year = Field()
    make = Field()
    model = Field()
    odometer = Field()
    type = Field()
    cylinders = Field()
    condition = Field()
    kbb_url = Field()
    good_condition_price = Field()
    percent_above_kbb = Field()
    price_list = Field()
    
class KbbItem(scrapy.Item):
    title = Field()
    url = Field()
    style = Field()