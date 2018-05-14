import os
import sys
import unittest

here = os.path.dirname(os.path.realpath(__file__))

sys.path.append(os.path.join(here, "../p"))

from gql import gql, Client
from gql.transport.requests import RequestsHTTPTransport
import json

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

    def put(self, craigs_url, good_condition_price, percent_above_kbb, kbb_url):
        mutation = '''mutation {{
              createCar(
                data: {{
                  craigs_url: "{craigs_url}"
                  kbb_value: {{
                    create: {{
                      percent_above_kbb: {percent_above_kbb}
                      good_condition_price: {good_condition_price}
                      kbb_url: "{kbb_url}"
                    }}
                  }}
              	}}
              )
              {{
                id
              }}
            }}'''.format(craigs_url=craigs_url, percent_above_kbb=percent_above_kbb, good_condition_price=good_condition_price, kbb_url=kbb_url)

        gql_mutation = gql(mutation)
        return self.client.execute(gql_mutation)

    def get(self, craigs_url):

        where = '''craigs_url: "{craigs_url}"
        '''.format(craigs_url=craigs_url)

        gql_str = '''
        {{
          car (where: {{
            {where}
          }})
          {{
            kbb_value {{
                percent_above_kbb
                good_condition_price
                kbb_url
            }}
          }}
        }}
        '''

        gql_str = gql_str.format(where=where)

        query = gql(gql_str)

        res = self.client.execute(query)
        print res
        return res

    def delete(self, craigs_url):
        mutation = '''mutation {{
                      deleteCar( where: {{
                        craigs_url: "{craigs_url}"
                      }}){{
                        id
                      }}
                    }}'''.format(craigs_url=craigs_url)

        gql_mutation = gql(mutation)
        return self.client.execute(gql_mutation)

class TestGqlClient(unittest.TestCase):
    def setUp(self):
        self.client = GqlClient()

    def test_get(self):
        self.assertTrue(self.client.get("a")["car"] == None)

    def test_put(self):
        self.assertTrue(self.client.put("x", 1, 2, "y")["createCar"]["id"])
        self.assertTrue(self.client.delete("x")["deleteCar"]["id"])




if __name__ == '__main__':
    unittest.main()
