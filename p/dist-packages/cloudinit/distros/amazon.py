# vi: ts=4 expandtab
#
#    Copyright (C) 2012 Canonical Ltd.
#    Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
#    Copyright (C) 2012 Yahoo! Inc.
#    Copyright (C) 2014 Amazon.com, Inc. or its affiliates.
#
#    Author: Scott Moser <scott.moser@canonical.com>
#    Author: Juerg Haefliger <juerg.haefliger@hp.com>
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

from cloudinit.distros import rhel

from cloudinit import log as logging
from cloudinit import util

LOG = logging.getLogger(__name__)

# for upgrade levels
UPGRADE_ALL       = -1
UPGRADE_NONE      = 0
UPGRADE_CRITICAL  = 1
UPGRADE_IMPORTANT = 2
UPGRADE_MEDIUM    = 3
UPGRADE_LOW       = 4
UPGRADE_BUGFIX    = 5
# the default level for "security"
UPGRADE_SECURITY  = UPGRADE_IMPORTANT

class Distro(rhel.Distro):
    ci_sudoers_fn = "/etc/sudoers.d/cloud-init"

    def upgrade_packages(self, level='none', exclude=[]):
        LOG.debug('Upgrade level: %s', level)
        level = self._resolve_upgrade_level(level)
        args = self._upgrade_level_args(level, exclude)
        return self.package_command('upgrade', args=args)

    def _resolve_upgrade_level(self, level):
        """Map the possible upgrade level choices to well known ones."""
        # the config parser will "helpfully" recognizes the boolean values
        # (on/off true/false 0/1 yes/no) and returns a bool even though we
        # asked for the *string* the user passed in. So now we need to figure
        # if that is the case and handle it.
        if isinstance(level, bool):
            if level: level = 'all'
            else: level = 'none'

        levels_map = dict(
            critical = UPGRADE_CRITICAL,
            important = UPGRADE_IMPORTANT,
            medium = UPGRADE_MEDIUM,
            low = UPGRADE_LOW,
            bugfix = UPGRADE_BUGFIX,
            security = UPGRADE_SECURITY,
            all = UPGRADE_ALL,
            none = UPGRADE_NONE,
            # these are aliases that we have supported in the past - keep them
            # around for backwards compatibility
            fixes = UPGRADE_BUGFIX,
            bugs = UPGRADE_BUGFIX,
            bugfixes = UPGRADE_BUGFIX,
            true = UPGRADE_ALL,
            on = UPGRADE_ALL,
            yes = UPGRADE_ALL,
            )
        return levels_map.get(level.lower(), UPGRADE_NONE)

    def _upgrade_level_args(self, level, exclude=[]):
        """Translate from an upgrade level and list of excludes to yum args."""
        args = ['--exclude=' + exclude_spec for exclude_spec in exclude]
        # 'all' doesn't need extra args because by default all updates are
        # included when running yum
        if level == UPGRADE_CRITICAL:
            args.extend(['--security', '--sec-severity=critical'])
        elif level == UPGRADE_IMPORTANT:
            args.extend(['--security', '--sec-severity=critical',
                         '--sec-severity=important'])
        elif level == UPGRADE_MEDIUM:
            args.extend(['--security', '--sec-severity=critical',
                         '--sec-severity=important', '--sec-severity=medium'])
        elif level == UPGRADE_LOW:
            args.append('--security') # this catches all security updates
        elif level == UPGRADE_BUGFIX:
            # we treat bugfixes like "all" since all updates are in some sense
            # bugfix updates.
            pass
        return args

    def _dist_uses_systemd(self):
        # Amazon Linux AMI doesn't use systemd yet
        return False
