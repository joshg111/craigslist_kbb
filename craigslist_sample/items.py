from scrapy.item import Item, Field

class CraigslistSampleItem(Item):
    price = Field()
    thumbnail = Field()
    desc = Field()
    location = Field()
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
    style = Field()
    timeago = Field()

class KbbItem(Item):
    title = Field()
    url = Field()
    style = Field()
