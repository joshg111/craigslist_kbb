# vi: ts=4 expandtab
#
#    Copyright (C) 2012 Yahoo! Inc.
#    Copyright (C) 2014 Amazon.com, Inc. or its affiliates.
#
#    Author: Joshua Harlow <harlowja@yahoo-inc.com>
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
import re
import string

from cloudinit import util

import configobj

# Valid characters taken from yum/__init__.py
_REPO_ID_VALID = re.compile(
    '[^%s%s%s]' % ('-_.:', string.ascii_letters, string.digits))


def _canonicalize_id(repo_id):
    """Replace invalid characters, so that the ID will be valid."""
    return _REPO_ID_VALID.sub('_', repo_id)


def _format_repo_value(val):
    if isinstance(val, (bool)):
        # Seems like yum prefers 1/0
        return str(int(val))
    if isinstance(val, (list, tuple)):
        # Can handle 'lists' in certain cases
        # See: http://bit.ly/Qqrf1t
        return "\n    ".join([_format_repo_value(v) for v in val])
    if not isinstance(val, (basestring, str)):
        return str(val)
    return val


# TODO(harlowja): move to distro?
# See man yum.conf
def _format_repository_config(repo_id, repo_config):
    #TODO: Use iniparse instead, since that's what yum uses
    #TODO: Sort the keys so that they are more like what you'd normally see
    to_be = configobj.ConfigObj()
    to_be[repo_id] = {}
    # Do basic translation of the items -> values
    for (k, v) in repo_config.items():
        # For now assume that people using this know
        # the format of yum and don't verify keys/values further
        to_be[repo_id][k] = _format_repo_value(v)
    lines = to_be.write()
    lines.insert(0, "# Created by cloud-init on %s" % (util.time_rfc2822()))
    # Ensure there's a newline before EOF
    lines.append('')
    return "\n".join(lines)


def _translate_repo_additions(repos):
    """Translate repo_additions configs to yum_repos configs.

    repo_additions:
     - source: "my_repo"
       filename: my.repo
       enabled: 1
       gpgcheck: 0
       baseurl: http://foo.bar.baz/mypath/
     - source: "your_repo"
       filename: your.repo
       enabled: 0
       key: http://your.site/static/gpg-key.pub
       mirrorlist: http://foo.bar.baz/yourpath/mirrors.list
    """
    # repo_additions defaulted to a 5m mirror_expire
    MIRROR_EXPIRE = '5m'
    translated = {}
    for repo in repos:
        # All of these defaults are derived from the dist_repo_yum module from
        # the Amazon Linux AMI fork of cloud-init-0.5.
        if repo.has_key('key'):
            repo.setdefault('gpgkey', repo.pop('key'))
            repo.setdefault('gpgcheck', True)
        if repo.has_key('mirrorlist'):
            repo.setdefault('mirror_expire', MIRROR_EXPIRE)
        if repo.has_key('source'):
            repo.setdefault('name', repo['source'])
        repo.setdefault('enabled', False)
        repo.setdefault('filename', 'cloud_config.repo')
        translated[_canonicalize_id(repo.pop('source', 'cloud_config'))] = repo
    return translated


def handle(name, cfg, _cloud, log, _args):
    # Get and translate repo_additions first, as we'd like yum_repos values to
    # override them
    repos = _translate_repo_additions(cfg.get('repo_additions', []))
    repos.update(cfg.get('yum_repos', {}))
    if not repos:
        log.debug(("Skipping module named %s,"
                   " no 'yum_repos' configuration found"), name)
        return
    repo_base_path = util.get_cfg_option_str(cfg, 'yum_repo_dir',
                                             '/etc/yum.repos.d/')
    repo_locations = {}
    repo_configs = {}
    for (repo_id, repo_config) in repos.items():
        canon_repo_id = _canonicalize_id(repo_id)
        repo_fn_path = repo_config.pop('filename', "%s.repo" % (canon_repo_id))
        if not os.path.isabs(repo_fn_path):
            repo_fn_pth = os.path.join(repo_base_path, repo_fn_path)
        if os.path.exists(repo_fn_pth):
            log.info("Skipping repo %s, file %s already exists!",
                     repo_id, repo_fn_pth)
            continue
        elif canon_repo_id in repo_locations:
            log.info("Skipping repo %s, file %s already pending!",
                     repo_id, repo_fn_pth)
            continue
        if not repo_config:
            repo_config = {}
        # Do some basic sanity checks/cleaning
        n_repo_config = {}
        for (k, v) in repo_config.items():
            k = k.lower().strip().replace("-", "_")
            if k:
                n_repo_config[k] = v
        repo_config = n_repo_config
        if not (repo_config.has_key('baseurl') or
                repo_config.has_key('mirrorlist')):
            log.warning(("Repository %s does not contain a baseurl or "
                "mirrorlist entry. Skipping."), repo_id)
            continue
        repo_configs[canon_repo_id] = repo_config
        repo_locations[canon_repo_id] = repo_fn_pth
    for (c_repo_id, path) in repo_locations.items():
        repo_blob = _format_repository_config(c_repo_id,
                                              repo_configs.get(c_repo_id))
        util.write_file(path, repo_blob)
