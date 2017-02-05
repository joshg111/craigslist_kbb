#==============================================================================
# Copyright 2011 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#==============================================================================
from resources import documents
import urlparse

_endpoint_data = documents.get_endpoint_data()

def get_endpoints_for_service(service):
    """Returns service endpoints for all regions."""

    return [Endpoint.from_data(e) for e in _endpoint_data["Services"][service]["Endpoints"]]

def is_service_url(service, unparsed_url):
    for endpoint in _endpoint_data["Services"][service]["Endpoints"]:
        if Endpoint.from_data(endpoint).matches_url(unparsed_url):
            return True
    return False

class Endpoint(object):
    """
    Represents an AWS service endpoint
    """

    @classmethod
    def from_data(cls, endpoint_data):
        is_default = False
        if "Default" in endpoint_data:
            is_default = bool(endpoint_data["Default"])
        return cls(endpoint_data["Region"], endpoint_data["Hostname"], is_default)

    def __init__(self, region, hostname, is_default=False):
        if region is None:
            raise ValueError("region is required")
        if hostname is None:
            raise ValueError("hostname is required")

        self.region = region
        self.hostname = hostname
        self.is_default = is_default

    def matches_url(self, unparsed_url):
        return urlparse.urlparse(unparsed_url).netloc.lower().endswith(self.hostname)

    def get_subdomain_prefix(self, unparsed_url):
        netloc = urlparse.urlparse(unparsed_url).netloc.lower()
        if not netloc.endswith(self.hostname):
            return None
        return netloc.rpartition(self.hostname)[0]
