# vi: ts=4 expandtab
#
#    Copyright (C) 2013 Craig Tracey
#    Copyright (C) 2013 Hewlett-Packard Development Company, L.P.
#    Copyright (C) 2015 Amazon.com, Inc. or its affiliates.
#
#    Author: Craig Tracey <craigtracey@gmail.com>
#    Author: Juerg Haefliger <juerg.haefliger@hp.com>
#    Author: Andrew Jorgensen <ajorgens@amazon.com>
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

#    Note:
#    This module is intended to manage resolv.conf in environments where
#    early configuration of resolv.conf is necessary for further
#    bootstrapping and/or where configuration management such as puppet or
#    chef own dns configuration. As Debian/Ubuntu will, by default, utilize
#    resovlconf, and similarly RedHat will use sysconfig, this module is
#    likely to be of little use unless those are configured correctly.
#
#    For RedHat with sysconfig, be sure to set PEERDNS=no for all DHCP
#    enabled NICs.  And, in Ubuntu/Debian it is recommended that DNS
#    be configured via the standard /etc/network/interfaces configuration
#    file.
#
#
#    Usage Example:
#
#    #cloud-config
#    manage_resolv_conf: true
#
#    resolv_conf:
#      nameservers: ['8.8.4.4', '8.8.8.8']
#      searchdomains:
#        - foo.example.com
#        - bar.example.com
#      domain: example.com
#      options:
#        rotate: true
#        timeout: 1
#


from cloudinit import log as logging
from cloudinit.settings import PER_INSTANCE
from cloudinit import templater
from cloudinit import util

LOG = logging.getLogger(__name__)

frequency = PER_INSTANCE

distros = ['redhat', 'sles']


def generate_resolv_conf(template_fn, params, target_fname="/etc/resolv.conf"):
    flags = []
    false_flags = []

    if 'options' in params:
        for key, val in params['options'].iteritems():
            if type(val) == bool:
                if val:
                    flags.append(key)
                else:
                    false_flags.append(key)

    for flag in flags + false_flags:
        del params['options'][flag]

    if not params.get('options'):
        params['options'] = {}

    params['flags'] = flags
    LOG.debug("Writing resolv.conf from template %s" % template_fn)
    templater.render_to_file(template_fn, target_fname, params)


def handle(name, cfg, cloud, log, _args):
    """
    Handler for resolv.conf

    @param name: The module name "resolv-conf" from cloud.cfg
    @param cfg: A nested dict containing the entire cloud config contents.
    @param cloud: The L{CloudInit} object in use.
    @param log: Pre-initialized Python logger object to use for logging.
    @param args: Any module arguments from cloud.cfg
    """
    if "manage_resolv_conf" not in cfg:
        log.debug(("Skipping module named %s,"
                   " no 'manage_resolv_conf' key in configuration"), name)
        return

    if not util.get_cfg_option_bool(cfg, "manage_resolv_conf", False):
        log.debug(("Skipping module named %s,"
                   " 'manage_resolv_conf' present but set to False"), name)
        return

    if "resolv_conf" not in cfg or not cfg["resolv_conf"]:
        log.warn("manage_resolv_conf True but no parameters provided!")

    template_fn = cloud.get_template_filename('resolv.conf')
    if not template_fn:
        log.warn("No template found, not rendering /etc/resolv.conf")
        return

    generate_resolv_conf(template_fn=template_fn, params=cfg["resolv_conf"])
    log.warn("You must set PEERDNS=no for any DHCP configured interfaces to "
             "prevent resolv.conf being overwritten.")
    return
