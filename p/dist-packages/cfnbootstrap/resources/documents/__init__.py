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
import copy
import imp
import logging
import os
import sys

# Imports define which python packages are added to the windows installer when we build it
# Importing pkg_resources causes import errors since six.py is a dependency it cannot resolve
# as the rest of setuptools is missing, so we don't import it in windows exe's as it isn't used anyway
def _is_from_exe():
    return (hasattr(sys, "frozen") or  # new py2exe
           hasattr(sys, "importers")  # old py2exe
           or imp.is_frozen("__main__"))

if not _is_from_exe():
    import pkg_resources

log = logging.getLogger(__name__)

try:
    import simplejson as json
except ImportError:
    import json

if os.name == 'nt':
    endpoint_override_path = os.path.expandvars(r"${SystemDrive}\cfn\endpoints-override.json")
else:
    endpoint_override_path = "/etc/cfn/endpoints-override.json"

#Overwrite path with environment variable if it exists (either UNIX or Windows)
endpoint_override_path = os.getenv("ENDPOINTS_OVERRIDE", endpoint_override_path)


try:
    #Modification for compilation by py2exe:
    if _is_from_exe():
        #Load endpoints.json from .exe directory, i.e. C:\Program Files\Amazon\cfn-bootstrap
        log.debug('Loading py2exe endpoints.json file')
        with open(os.path.join(os.path.dirname(sys.executable), 'endpoints.json'), 'r') as f:
            _endpoint_data = json.load(f)

    # end py2exe
    else:
        _endpoint_data = json.load(pkg_resources.resource_stream("cfnbootstrap.resources.documents", "endpoints.json"))

except ValueError:
    log.exception("Failed to load endpoints.json")
    raise

try:
    #Apply endpoint_override, if present
    if os.path.isfile(endpoint_override_path):
        log.debug('Loading existing endpoints override file %s' % (endpoint_override_path,))
        with open(endpoint_override_path, 'r') as f:
            _endpoint_data = json.load(f)
except ValueError:
    log.exception("Failed to load endpoints override file: %s" % (endpoint_override_path,))
    raise


def get_endpoint_data():
    return copy.deepcopy(_endpoint_data)