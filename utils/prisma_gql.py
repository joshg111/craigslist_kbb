import os
import sys
import unittest
from scrapy import Request

here = os.path.dirname(os.path.realpath(__file__))

sys.path.append(os.path.join(here, "../p"))

from gql import gql, Client
from gql.transport.requests import RequestsHTTPTransport
import json

DEBUG = False
PRISMA_URL = 'https://us1.prisma.sh/jagreenf111-8fe67d/kbb_prisma/dev'

def Log(x):
    if DEBUG:
        print x

class GqlClient():
    def __init__(self):
        _transport = RequestsHTTPTransport(
            url='https://us1.prisma.sh/jagreenf111-8fe67d/kbb_prisma/dev',
            use_json=True,
        )

        self.client = Client(
            retries=3,
            transport=_transport,
            fetch_schema_from_transport=True,
        )

    def put(self, item):
        ''' Takes `item` object (scrapy object) and creats a cache value using the
        craigslist url as the key.'''
        fields = ""
        for i in item.iterkeys():
            if item[i] == None:
                # Not allowed to put None into graphql syntax.
                continue

            fields += "{key}: ".format(key=i)
            if type(item[i]) == str or type(item[i]) == unicode:
                fields += '"{val}"'.format(val=item[i])
            else:
                fields += '{val}'.format(val=item[i])

            fields += "\n"

        mutation = '''mutation {{
              createCar(
                data: {{
                  {fields}
              	}}
              )
              {{
                id
              }}
            }}'''.format(fields=fields)

        Log("mutation = " + str(mutation))
        gql_mutation = gql(mutation)
        return self.client.execute(gql_mutation)

    def get(self, url):

        # Create scrapy request

        where = '''url: "{url}"
        '''.format(url=url)

        gql_str = '''
        {{
          car (where: {{
            {where}
          }})
          {{
            url
            percent_above_kbb
            good_condition_price
            kbb_url
            price
            thumbnail
            desc
            location
            year
            make
            model
            odometer
            type
            cylinders
            condition
            style
            timeago
          }}
        }}
        '''

        gql_str = gql_str.format(where=where)

        # return Request(PRISMA_URL, body=gql_str)

        query = gql(gql_str)

        res = self.client.execute(query)
        Log(res)
        return res

    def delete(self, url):
        mutation = '''mutation {{
                      deleteCar( where: {{
                        url: "{url}"
                      }}){{
                        id
                      }}
                    }}'''.format(url=url)

        gql_mutation = gql(mutation)
        return self.client.execute(gql_mutation)

class TestGqlClient(unittest.TestCase):
    def setUp(self):
        self.client = GqlClient()

    def test_get(self):
        self.assertTrue(self.client.get("a")["car"] == None)

    def test_put(self):
        item = {'style': u'mystyle', 'cylinders': 4, 'timeago': u'2018-05-10T15:06:22-0700', 'percent_above_kbb': 38, 'good_condition_price': 5071, 'url': 'x', 'price': 6999, 'odometer': 146000, 'thumbnail': u'https://images.craigslist.org/00w0w_4Upb4k1E3ye_600x450.jpg', 'location': u' (la mesa)', 'kbb_url': u'https://www.kbb.com/toyota/camry/2007/hybrid-sedan-4d/?vehicleid=84284&intent=buy-used&category=sedan&condition=good&mileage=146000&pricetype=private-party', 'year': u'2007', 'model': 'camry', 'type': u'sedan', 'make': u'toyota', 'condition': u'excellent', 'desc': u'2007 toyota camry'}

        self.assertTrue(self.client.put(item)["createCar"]["id"])
        self.assertTrue(self.client.delete("x")["deleteCar"]["id"])




if __name__ == '__main__':
    unittest.main()
