# vi: ts=4 expandtab
#
#    Copyright (C) 2012 Canonical Ltd.
#    Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
#    Copyright (C) 2012 Yahoo! Inc.
#
#    Author: Scott Moser <scott.moser@canonical.com>
#    Author: Juerg Haefliger <juerg.haefliger@hp.com>
#    Author: Joshua Harlow <harlowja@yahoo-inc.com>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License version 3, as
#    published by the Free Software Foundation.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.

import copy
import os

from cloudinit import log as logging

LOG = logging.getLogger(__name__)

# This class is the high level wrapper that provides
# access to cloud-init objects without exposing the stage objects
# to handler and or module manipulation. It allows for cloud
# init to restrict what those types of user facing code may see
# and or adjust (which helps avoid code messing with each other)
#
# It also provides util functions that avoid having to know
# how to get a certain member from this submembers as well
# as providing a backwards compatible object that can be maintained
# while the stages/other objects can be worked on independently...


class Cloud(object):
    def __init__(self, datasource, paths, cfg, distro, runners):
        self.datasource = datasource
        self.paths = paths
        self.distro = distro
        self._cfg = cfg
        self._runners = runners

    # If a 'user' manipulates logging or logging services
    # it is typically useful to cause the logging to be
    # setup again.
    def cycle_logging(self):
        logging.resetLogging()
        logging.setupLogging(self.cfg)

    @property
    def cfg(self):
        # Ensure that not indirectly modified
        return copy.deepcopy(self._cfg)

    def run(self, name, functor, args, freq=None, clear_on_fail=False):
        return self._runners.run(name, functor, args, freq, clear_on_fail)

    def get_template_filename(self, name):
        fn = self.paths.template_tpl % (name)
        if not os.path.isfile(fn):
            LOG.warn("No template found at %s for template named %s", fn, name)
            return None
        return fn

    # The rest of thes are just useful proxies
    def get_userdata(self, apply_filter=True):
        return self.datasource.get_userdata(apply_filter)

    def get_instance_id(self):
        return self.datasource.get_instance_id()

    @property
    def launch_index(self):
        return self.datasource.launch_index

    def get_public_ssh_keys(self):
        return self.datasource.get_public_ssh_keys()

    def get_locale(self):
        return self.datasource.get_locale()

    def get_hostname(self, fqdn=False):
        return self.datasource.get_hostname(fqdn=fqdn)

    def device_name_to_device(self, name):
        return self.datasource.device_name_to_device(name)

    def get_ipath_cur(self, name=None):
        return self.paths.get_ipath_cur(name)

    def get_cpath(self, name=None):
        return self.paths.get_cpath(name)

    def get_ipath(self, name=None):
        return self.paths.get_ipath(name)
