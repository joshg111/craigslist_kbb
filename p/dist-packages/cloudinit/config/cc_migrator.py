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
import fnmatch
import shutil

from cloudinit import helpers
from cloudinit import util

from cloudinit.settings import PER_ALWAYS, PER_INSTANCE, PER_ONCE, FREQUENCIES
from cloudinit.config.cc_scripts_user import SCRIPT_SUBDIR


frequency = PER_ALWAYS
LEGACY_SEM_MAP = {
    'apt-update-upgrade': [
        'config-apt-configure',
        'config-package-update-upgrade-install',
    ],
    'config-genrepo': [
        'config-yum-configure',
    ],
    'config-package-setup': [
        'config-yum-configure',
        'config-yum-add-repo',
        'config-package-update-upgrade-install',
    ],
    'consume-userdata': [
        'consume-data',
    ],
    'set-hostname': [
        'config-set-hostname',
    ],
    'update-hostname': [
        'config-update-hostname',
    ],
    'user-scripts': [
        'config-scripts-user',
    ],
    # We don't want customers who upgraded from 0.5 to have any new modules run
    # after the next reboot, so we will take this semaphore that only existed
    # on 0.5 and create all the new semaphores.
    'set-defaults': [
        'config-power-state-change',
        'config-phone-home',
        'config-keys-to-console',
        'config-ssh-authkey-fingerprints',
        'config-scripts-per-instance',
        ('config-scripts-per-once', PER_ONCE),
        # Don't migrate this one, because if user-scripts hasn't run, we want
        # to have a chance to run them if cloud-init has upgraded itself.
        # If it has run, it will get migrated by the user-scripts entry.
        #'config-scripts-user',
        'config-timezone',
        'config-set-passwords',
        'config-set-hostname',
        'config-users-groups',
        'config-write-files',
        'config-rsyslog',
    ],
}


def _migrate_legacy_per_instance(cloud, log):
    """Migrates legacy per_instance semaphores to their new location."""
    instance_id = cloud.get_instance_id()
    # Old per-instance semaphores were stored in the cpath:
    # /var/lib/cloud/sem
    cpath = cloud.paths.get_cpath('sem')
    if not cpath or not os.path.isdir(cpath):
        return
    sem_helper = helpers.FileSemaphores(cloud.paths.get_ipath('sem'))
    log.debug('Searching for legacy per-instance semaphores under %s', cpath)
    # We're only interested in the current instance-id, since any
    # previous should never show up again.
    for p in fnmatch.filter(os.listdir(cpath), '*.' + instance_id):
        # isfile to avoid any directories
        if not os.path.isfile(os.path.join(cpath, p)):
            continue
        log.debug('Looking at %s', p)
        (name, _freq) = os.path.splitext(p)
        if sem_helper.has_run(name, PER_INSTANCE):
            continue
        with sem_helper.lock(name, PER_INSTANCE):
            log.warning("Migrated semaphore %s with frequency %s",
                        name, PER_INSTANCE)


def _migrate_canon_sems(cloud, log):
    """Migrates non-canonical semaphores to their canonical names."""
    paths = (cloud.paths.get_ipath('sem'), cloud.paths.get_cpath('sem'))
    log.debug('Migrating semaphores which are not named canonically.')
    for sem_path in paths:
        if not sem_path or not os.path.isdir(sem_path):
            continue
        for p in os.listdir(sem_path):
            if not os.path.isfile(os.path.join(sem_path, p)):
                continue
            log.debug('Looking at %s', p)
            (name, ext) = os.path.splitext(p)
            canon_name = helpers.canon_sem_name(name)
            source = os.path.join(sem_path, p)
            destination = os.path.join(sem_path, canon_name + ext)
            if canon_name == name or os.path.exists(destination):
                continue
            shutil.copy(source, destination)
            log.warning("Migrated semaphore %s to %s", name, canon_name)


def _migrate_legacy_sems(cloud, log):
    """Migrates semaphores which have been renamed or split."""
    ipath = cloud.paths.get_ipath('sem')
    isem_helper = helpers.FileSemaphores(ipath)
    cpath = cloud.paths.get_cpath('sem')
    csem_helper = helpers.FileSemaphores(cpath)

    log.debug("Migrating semaphores which have been renamed or split.")
    for sem_path in (ipath, cpath):
        if not sem_path or not os.path.isdir(sem_path):
            continue
        log.debug("Looking in %s", sem_path)
        listed = os.listdir(sem_path)
        for (mod_name, migrate_to) in LEGACY_SEM_MAP.items():
            mod_name = helpers.canon_sem_name(mod_name)
            for p in fnmatch.filter(listed, mod_name + '*'):
                if not os.path.isfile(os.path.join(sem_path, p)):
                    continue
                (_name, freq) = os.path.splitext(p)
                if freq:
                    # Trim the .
                    freq = freq[1:]
                    if freq not in FREQUENCIES:
                        continue
                elif sem_path == ipath:
                    freq = PER_INSTANCE
                else:
                    continue
                for m in migrate_to:
                    to_freq = freq
                    if not isinstance(m, basestring):
                        # If it's not a string, it should have a frequency
                        (m, to_freq) = m
                    if to_freq == PER_INSTANCE:
                        sem_helper = isem_helper
                    else:
                        sem_helper = csem_helper
                    if sem_helper.has_run(m, to_freq):
                        continue
                    with sem_helper.lock(m, to_freq):
                        log.warning(
                            "Migrated semaphore %s to %s with frequency %s",
                            p, m, to_freq)


def handle(name, cfg, cloud, log, _args):
    do_migrate = util.get_cfg_option_str(cfg, "migrate", True)
    if not util.translate_bool(do_migrate):
        log.debug("Skipping module named %s, migration disabled", name)
        return
    _migrate_canon_sems(cloud, log)
    _migrate_legacy_per_instance(cloud, log)
    _migrate_legacy_sems(cloud, log)
