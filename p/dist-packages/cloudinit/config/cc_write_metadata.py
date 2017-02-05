# vi: ts=4 expandtab
#
#    Copyright (C) 2012 Yahoo! Inc.
#    Copyright (C) 2014 Amazon.com, Inc. or its affiliates.
#
#    Author: Joshua Harlow <harlowja@yahoo-inc.com>
#    Author: Ian Weller <iweller@amazon.com>
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

from cloudinit.config import cc_write_files
from cloudinit.settings import PER_INSTANCE
from cloudinit import util

frequency = PER_INSTANCE

# list of dictionaries we expose to the user from the cloud.datasource object
EXPOSED_DICTS = ('metadata', 'identity')
# list of optional arguments not supported by write_files
OPTIONAL_ARGUMENTS = ('separator', 'allowempty')


def handle(name, cfg, cloud, log, args):
    """
    Example cloud-config that would write the AWS instance ID to
    /root/.instance-id, with a fallback of "unknown":

    write_metadata:
      - path: /root/.instance-id
        data:
          - metadata: instance-id
          - unknown

    Available places to get data from include identity and metadata.
    Data paths can include slashes as delimiters in the dictionary
    structure; a user can provide their own delimiter if needed:

    write_metadata:
      - path: /root/whatever
        data:
          - metadata: public-keys|this/has/slashes|0
            separator: "|"
          - fallback string

    write_metadata will consider an empty string from a data path an
    error, unless you specifically say that's okay with "allowempty":

    write_metadata:
      - path: /root/.could-be-blank
        data:
          - metadata: could-be-blank
            allowempty: true
          - fallback string
    """
    files = cfg.get('write_metadata')
    if not files:
        log.debug(("Skipping module named %s, no/empty "
                   "'write_metadata' key in configuration"), name)
        return
    write_metadata(name, files, cloud, log)


def write_metadata(name, files, cloud, log):
    if not files:
        return

    new_files = list()

    for i, f_info in enumerate(files):
        path = f_info.get('path')
        if not path:
            log.warn("No path provided to write for entry %s in module %s",
                     i + 1, name)
            continue
        data = f_info.get('data')
        if not data:
            log.warn("No data provided to write for entry %s in module %s",
                     i + 1, name)
            continue

        f_info['content'] = retrieve_metadata(path, data, cloud, log)
        if f_info['content'] is None:
            # if there is no content, don't write anything to the file
            # (this is not the same as empty content)
            continue

        # Use the default permissions, to suppress a warning from write-files
        f_info.setdefault('permissions', cc_write_files.DEFAULT_PERMS)

        # ensure that we don't get unexpected behavior in a future
        # version of the write_files module
        for key in EXPOSED_DICTS + OPTIONAL_ARGUMENTS:
            if key in f_info:
                del f_info[key]

        new_files.append(f_info)

    cc_write_files.write_files(name, files, log)


def retrieve_metadata(path, data, cloud, log):
    for datum in data:
        if isinstance(datum, (str, unicode)):
            # used for fallback data
            return datum
        elif isinstance(datum, dict):
            kwargs = dict()
            if 'separator' in datum:
                kwargs['separator'] = datum['separator']
            for dataset in EXPOSED_DICTS:
                if dataset in datum:
                    if not hasattr(cloud.datasource, dataset):
                        log.warn('there is no %s dataset', dataset)
                        continue
                    try:
                        obj = getattr(cloud.datasource, dataset)
                        value = util.dictpath(obj, datum[dataset], **kwargs)
                        # if the value is an empty string, and the
                        # configuration hasn't told us that's okay, go
                        # to the next fallback
                        if not value and \
                                util.is_false(datum.get('allowempty', False)):
                            continue
                        return value
                    except Exception as exc:
                        # don't return anything, we proceed to the next datum
                        log.warn('using path "%(path)s" against %(dataset)s '
                                 'failed: %(exctype)s: %(excmsg)s',
                                 path=datum[dataset], dataset=dataset,
                                 exctype=type(exc).__name__, excmsg=str(exc))

    # if we reached this point, all attempts to get the data we want
    # failed, and there wasn't a fallback
    log.warn('all attempts to retrieve metadata for %s failed', path)
