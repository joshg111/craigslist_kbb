# vi: ts=4 expandtab
#
#    Copyright (C) 2014 Amazon.com, Inc. or its affiliates.
#
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

import os
import os.path
import tempfile

from glob import glob

from cloudinit import templater
from cloudinit import util
from cloudinit.settings import PER_INSTANCE
from iniparse import INIConfig

frequency = PER_INSTANCE
distros = [ 'amazon' ]

YUMCONF = '/etc/yum.conf'

def handle(name, cfg, cloud, log, _args):
    errors = []
    try:
        _genrepo(cfg, cloud, log)
    except Exception as e:
        errors.append(e)
    if name == 'genrepo':
        # If this was called as the legacy genrepo module, then we are done
        if len(errors) > 0:
            raise errors[-1]
        return

    try:
        _set_releasever(cfg, log)
    except Exception as e:
        errors.append(e)

    if len(errors) > 0:
        raise errors[-1]


def _set_releasever(cfg, log):
    """Set the yum releasever to the value of repo_releasever."""
    releasever = util.get_cfg_option_str(cfg, 'repo_releasever')
    if not releasever:
        log.info("No releasever provided, leaving yum.conf unchanged.")
        return
    log.info('Setting yum releasever to %s', releasever)

    statinfo = os.stat(YUMCONF)

    with open(YUMCONF) as conf:
        cfg = INIConfig(conf)
    cfg.main.releasever = releasever
    util.write_file(YUMCONF, str(cfg))


def _genrepo(cfg, cloud, log):
    """Generate yum repo files from provided templates."""
    # The repo_preserve option is used to disable this feature
    if util.get_cfg_option_bool(cfg, 'repo_preserve', False):
        log.info("Not generating yum repo files, per configuration.")
        return
    log.debug("Generating default repo files");

    # get the repo dir from a legacy option (see cc_yum_add_repo.py)
    # TODO: get it from a more sensible path, or from yum?
    reposdir = util.get_cfg_option_str(cfg, 'yum_repo_dir',
                                       '/etc/yum.repos.d')

    # This function gets the mirror url from the config, with the region
    # name interpolated into it.
    mirror_info = cloud.datasource.get_package_mirror_info()

    # It would be better to get 'name' from the config, but I'm not sure
    # where to put it in there that might end up being standard
    params = {'name': 'amzn', 'mirror': mirror_info['regional']}
    log.debug("Using mirror: %s", params['mirror'])

    repo_templates = glob(cloud.paths.template_tpl % 'amzn-*.repo')

    # extract the prefix and suffix from the template filename so we can
    # extract the filename later
    (tpl_prefix, tpl_suffix) = cloud.paths.template_tpl.split('%s', 1)

    for template_fn in repo_templates:
        out_fn = os.path.join(
            reposdir,
            # extract the filename from the template path
            template_fn[len(tpl_prefix):-len(tpl_suffix)])
        templater.render_to_file(template_fn, out_fn, params)
