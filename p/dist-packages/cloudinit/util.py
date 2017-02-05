# vi: ts=4 expandtab
#
#    Copyright (C) 2012 Canonical Ltd.
#    Copyright (C) 2012, 2013 Hewlett-Packard Development Company, L.P.
#    Copyright (C) 2012 Yahoo! Inc.
#    Copyright (C) 2014 Amazon.com, Inc. or its affiliates.
#
#    Author: Scott Moser <scott.moser@canonical.com>
#    Author: Juerg Haefliger <juerg.haefliger@hp.com>
#    Author: Joshua Harlow <harlowja@yahoo-inc.com>
#    Author: Andrew Jorgensen <ajorgens@amazon.com>
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

from StringIO import StringIO

import base64
import contextlib
import copy as obj_copy
import ctypes
import errno
import glob
import grp
import gzip
import hashlib
import json
import os
import os.path
import platform
import pwd
import random
import re
import shutil
import socket
import stat
import string
import subprocess
import sys
import tempfile
import time
import urlparse

import yaml

from cloudinit import importer
from cloudinit import log as logging
from cloudinit import mergers
from cloudinit import safeyaml
from cloudinit import type_utils
from cloudinit import url_helper
from cloudinit import version

from cloudinit.settings import (CFG_BUILTIN)


_DNS_REDIRECT_IP = None
LOG = logging.getLogger(__name__)

# Helps cleanup filenames to ensure they aren't FS incompatible
FN_REPLACEMENTS = {
    os.sep: '_',
}
FN_ALLOWED = ('_-.()' + string.digits + string.ascii_letters)

# Helper utils to see if running in a container
CONTAINER_TESTS = ['running-in-container', 'lxc-is-container']

# An imperfect, but close enough regex to detect Base64 encoding
BASE64 = re.compile('^[A-Za-z0-9+/\-_\n]+=?=?$')

class ProcessExecutionError(IOError):

    MESSAGE_TMPL = ('%(description)s\n'
                    'Command: %(cmd)s\n'
                    'Exit code: %(exit_code)s\n'
                    'Reason: %(reason)s\n'
                    'Stdout: %(stdout)r\n'
                    'Stderr: %(stderr)r')

    def __init__(self, stdout=None, stderr=None,
                 exit_code=None, cmd=None,
                 description=None, reason=None):
        if not cmd:
            self.cmd = '-'
        else:
            self.cmd = cmd

        if not description:
            self.description = 'Unexpected error while running command.'
        else:
            self.description = description

        if not isinstance(exit_code, (long, int)):
            self.exit_code = '-'
        else:
            self.exit_code = exit_code

        if not stderr:
            self.stderr = ''
        else:
            self.stderr = stderr

        if not stdout:
            self.stdout = ''
        else:
            self.stdout = stdout

        if reason:
            self.reason = reason
        else:
            self.reason = '-'

        message = self.MESSAGE_TMPL % {
            'description': self.description,
            'cmd': self.cmd,
            'exit_code': self.exit_code,
            'stdout': self.stdout,
            'stderr': self.stderr,
            'reason': self.reason,
        }
        IOError.__init__(self, message)


class SeLinuxGuard(object):
    def __init__(self, path, recursive=False):
        # Late import since it might not always
        # be possible to use this
        try:
            self.selinux = importer.import_module('selinux')
        except ImportError:
            self.selinux = None
        self.path = path
        self.recursive = recursive

    def __enter__(self):
        if self.selinux and self.selinux.is_selinux_enabled():
            return True
        else:
            return False

    def __exit__(self, excp_type, excp_value, excp_traceback):
        if not self.selinux or not self.selinux.is_selinux_enabled():
            return
        if not os.path.lexists(self.path):
            return

        path = os.path.realpath(self.path)
        # path should be a string, not unicode
        path = str(path)
        try:
            stats = os.lstat(path)
            self.selinux.matchpathcon(path, stats[stat.ST_MODE])
        except OSError:
            return

        LOG.debug("Restoring selinux mode for %s (recursive=%s)",
                  path, self.recursive)
        self.selinux.restorecon(path, recursive=self.recursive)


class MountFailedError(Exception):
    pass


class DecodingError(Exception):
    pass


class DecompressionError(Exception):
    pass


def ExtendedTemporaryFile(**kwargs):
    fh = tempfile.NamedTemporaryFile(**kwargs)
    # Replace its unlink with a quiet version
    # that does not raise errors when the
    # file to unlink has been unlinked elsewhere..
    LOG.debug("Created temporary file %s", fh.name)
    fh.unlink = del_file

    # Add a new method that will unlink
    # right 'now' but still lets the exit
    # method attempt to remove it (which will
    # not throw due to our del file being quiet
    # about files that are not there)
    def unlink_now():
        fh.unlink(fh.name)

    setattr(fh, 'unlink_now', unlink_now)
    return fh


def fork_cb(child_cb, *args, **kwargs):
    fid = os.fork()
    if fid == 0:
        try:
            child_cb(*args, **kwargs)
            os._exit(0)
        except:
            logexc(LOG, "Failed forking and calling callback %s",
                   type_utils.obj_name(child_cb))
            os._exit(1)
    else:
        LOG.debug("Forked child %s who will run callback %s",
                  fid, type_utils.obj_name(child_cb))


def is_true(val, addons=None):
    if isinstance(val, (bool)):
        return val is True
    check_set = ['true', '1', 'on', 'yes']
    if addons:
        check_set = check_set + addons
    if str(val).lower().strip() in check_set:
        return True
    return False


def is_false(val, addons=None):
    if isinstance(val, (bool)):
        return val is False
    check_set = ['off', '0', 'no', 'false']
    if addons:
        check_set = check_set + addons
    if str(val).lower().strip() in check_set:
        return True
    return False


def translate_bool(val, addons=None):
    if not val:
        # This handles empty lists and false and
        # other things that python believes are false
        return False
    # If its already a boolean skip
    if isinstance(val, (bool)):
        return val
    return is_true(val, addons)


def rand_str(strlen=32, select_from=None):
    if not select_from:
        select_from = string.letters + string.digits
    return "".join([random.choice(select_from) for _x in range(0, strlen)])


def read_conf(fname):
    try:
        return load_yaml(load_file(fname), default={})
    except IOError as e:
        if e.errno == errno.ENOENT:
            return {}
        else:
            raise


# Merges X lists, and then keeps the
# unique ones, but orders by sort order
# instead of by the original order
def uniq_merge_sorted(*lists):
    return sorted(uniq_merge(*lists))


# Merges X lists and then iterates over those
# and only keeps the unique items (order preserving)
# and returns that merged and uniqued list as the
# final result.
#
# Note: if any entry is a string it will be
# split on commas and empty entries will be
# evicted and merged in accordingly.
def uniq_merge(*lists):
    combined_list = []
    for a_list in lists:
        if isinstance(a_list, (str, basestring)):
            a_list = a_list.strip().split(",")
            # Kickout the empty ones
            a_list = [a for a in a_list if len(a)]
        combined_list.extend(a_list)
    return uniq_list(combined_list)


def clean_filename(fn):
    for (k, v) in FN_REPLACEMENTS.iteritems():
        fn = fn.replace(k, v)
    removals = []
    for k in fn:
        if k not in FN_ALLOWED:
            removals.append(k)
    for k in removals:
        fn = fn.replace(k, '')
    fn = fn.strip()
    return fn


def decode_base64(data, quiet=True):
    try:
        # Some builds of python don't throw an exception when the data is not
        # proper Base64, so we check it first.
        if BASE64.match(data):
            return base64.urlsafe_b64decode(data)
        else:
            return data
    except Exception as e:
        if quiet:
            return data
        else:
            raise DecodingError(str(e))


def decomp_gzip(data, quiet=True):
    try:
        buf = StringIO(str(data))
        with contextlib.closing(gzip.GzipFile(None, "rb", 1, buf)) as gh:
            return gh.read()
    except Exception as e:
        if quiet:
            return data
        else:
            raise DecompressionError(str(e))


def extract_usergroup(ug_pair):
    if not ug_pair:
        return (None, None)
    ug_parted = ug_pair.split(':', 1)
    u = ug_parted[0].strip()
    if len(ug_parted) == 2:
        g = ug_parted[1].strip()
    else:
        g = None
    if not u or u == "-1" or u.lower() == "none":
        u = None
    if not g or g == "-1" or g.lower() == "none":
        g = None
    return (u, g)


def find_modules(root_dir):
    entries = dict()
    for fname in glob.glob(os.path.join(root_dir, "*.py")):
        if not os.path.isfile(fname):
            continue
        modname = os.path.basename(fname)[0:-3]
        modname = modname.strip()
        if modname and modname.find(".") == -1:
            entries[fname] = modname
    return entries


def multi_log(text, console=True, stderr=True,
              log=None, log_level=logging.DEBUG):
    if stderr:
        sys.stderr.write(text)
    if console:
        conpath = "/dev/console"
        if os.path.exists(conpath):
            with open(conpath, 'wb') as wfh:
                wfh.write(text)
                wfh.flush()
        else:
            # A container may lack /dev/console (arguably a container bug).  If
            # it does not exist, then write output to stdout.  this will result
            # in duplicate stderr and stdout messages if stderr was True.
            #
            # even though upstart or systemd might have set up output to go to
            # /dev/console, the user may have configured elsewhere via
            # cloud-config 'output'.  If there is /dev/console, messages will
            # still get there.
            sys.stdout.write(text)
    if log:
        if text[-1] == "\n":
            log.log(log_level, text[:-1])
        else:
            log.log(log_level, text)


def load_json(text, root_types=(dict,)):
    decoded = json.loads(text)
    if not isinstance(decoded, tuple(root_types)):
        expected_types = ", ".join([str(t) for t in root_types])
        raise TypeError("(%s) root types expected, got %s instead"
                        % (expected_types, type(decoded)))
    return decoded


def is_ipv4(instr):
    """determine if input string is a ipv4 address. return boolean."""
    toks = instr.split('.')
    if len(toks) != 4:
        return False

    try:
        toks = [x for x in toks if int(x) < 256 and int(x) >= 0]
    except:
        return False

    return len(toks) == 4


def get_cfg_option_bool(yobj, key, default=False):
    if key not in yobj:
        return default
    return translate_bool(yobj[key])


def get_cfg_option_str(yobj, key, default=None):
    if key not in yobj:
        return default
    val = yobj[key]
    if not isinstance(val, (str, basestring)):
        val = str(val)
    return val


def system_info():
    return {
        'platform': platform.platform(),
        'release': platform.release(),
        'python': platform.python_version(),
        'uname': platform.uname(),
        'dist': platform.linux_distribution(),
    }


def get_cfg_option_list(yobj, key, default=None):
    """
    Gets the C{key} config option from C{yobj} as a list of strings. If the
    key is present as a single string it will be returned as a list with one
    string arg.

    @param yobj: The configuration object.
    @param key: The configuration key to get.
    @param default: The default to return if key is not found.
    @return: The configuration option as a list of strings or default if key
        is not found.
    """
    if key not in yobj:
        return default
    if yobj[key] is None:
        return []
    val = yobj[key]
    if isinstance(val, (list)):
        cval = [v for v in val]
        return cval
    if not isinstance(val, (basestring)):
        val = str(val)
    return [val]


# get a cfg entry by its path array
# for f['a']['b']: get_cfg_by_path(mycfg,('a','b'))
def get_cfg_by_path(yobj, keyp, default=None):
    cur = yobj
    for tok in keyp:
        if tok not in cur:
            return default
        cur = cur[tok]
    return cur


def fixup_output(cfg, mode):
    (outfmt, errfmt) = get_output_cfg(cfg, mode)
    redirect_output(outfmt, errfmt)
    return (outfmt, errfmt)


# redirect_output(outfmt, errfmt, orig_out, orig_err)
#  replace orig_out and orig_err with filehandles specified in outfmt or errfmt
#  fmt can be:
#   > FILEPATH
#   >> FILEPATH
#   | program [ arg1 [ arg2 [ ... ] ] ]
#
#   with a '|', arguments are passed to shell, so one level of
#   shell escape is required.
#
#   if _CLOUD_INIT_SAVE_STDOUT is set in environment to a non empty and true
#   value then output input will not be closed (useful for debugging).
#
def redirect_output(outfmt, errfmt, o_out=None, o_err=None):

    if is_true(os.environ.get("_CLOUD_INIT_SAVE_STDOUT")):
        LOG.debug("Not redirecting output due to _CLOUD_INIT_SAVE_STDOUT")
        return

    if not o_out:
        o_out = sys.stdout
    if not o_err:
        o_err = sys.stderr

    if outfmt:
        LOG.debug("Redirecting %s to %s", o_out, outfmt)
        (mode, arg) = outfmt.split(" ", 1)
        if mode == ">" or mode == ">>":
            owith = "ab"
            if mode == ">":
                owith = "wb"
            new_fp = open(arg, owith)
        elif mode == "|":
            proc = subprocess.Popen(arg, shell=True, stdin=subprocess.PIPE)
            new_fp = proc.stdin
        else:
            raise TypeError("Invalid type for output format: %s" % outfmt)

        if o_out:
            os.dup2(new_fp.fileno(), o_out.fileno())

        if errfmt == outfmt:
            LOG.debug("Redirecting %s to %s", o_err, outfmt)
            os.dup2(new_fp.fileno(), o_err.fileno())
            return

    if errfmt:
        LOG.debug("Redirecting %s to %s", o_err, errfmt)
        (mode, arg) = errfmt.split(" ", 1)
        if mode == ">" or mode == ">>":
            owith = "ab"
            if mode == ">":
                owith = "wb"
            new_fp = open(arg, owith)
        elif mode == "|":
            proc = subprocess.Popen(arg, shell=True, stdin=subprocess.PIPE)
            new_fp = proc.stdin
        else:
            raise TypeError("Invalid type for error format: %s" % errfmt)

        if o_err:
            os.dup2(new_fp.fileno(), o_err.fileno())


def make_url(scheme, host, port=None,
                path='', params='', query='', fragment=''):

    pieces = []
    pieces.append(scheme or '')

    netloc = ''
    if host:
        netloc = str(host)

    if port is not None:
        netloc += ":" + "%s" % (port)

    pieces.append(netloc or '')
    pieces.append(path or '')
    pieces.append(params or '')
    pieces.append(query or '')
    pieces.append(fragment or '')

    return urlparse.urlunparse(pieces)


def mergemanydict(srcs, reverse=False):
    if reverse:
        srcs = reversed(srcs)
    merged_cfg = {}
    for cfg in srcs:
        if cfg:
            # Figure out which mergers to apply...
            mergers_to_apply = mergers.dict_extract_mergers(cfg)
            if not mergers_to_apply:
                mergers_to_apply = mergers.default_mergers()
            merger = mergers.construct(mergers_to_apply)
            merged_cfg = merger.merge(merged_cfg, cfg)
    return merged_cfg


@contextlib.contextmanager
def chdir(ndir):
    curr = os.getcwd()
    try:
        os.chdir(ndir)
        yield ndir
    finally:
        os.chdir(curr)


@contextlib.contextmanager
def umask(n_msk):
    old = os.umask(n_msk)
    try:
        yield old
    finally:
        os.umask(old)


@contextlib.contextmanager
def tempdir(**kwargs):
    # This seems like it was only added in python 3.2
    # Make it since its useful...
    # See: http://bugs.python.org/file12970/tempdir.patch
    tdir = tempfile.mkdtemp(**kwargs)
    try:
        yield tdir
    finally:
        del_dir(tdir)


def center(text, fill, max_len):
    return '{0:{fill}{align}{size}}'.format(text, fill=fill,
                                            align="^", size=max_len)


def del_dir(path):
    LOG.debug("Recursively deleting %s", path)
    shutil.rmtree(path)


def runparts(dirp, skip_no_exist=True, exe_prefix=None):
    if skip_no_exist and not os.path.isdir(dirp):
        return

    failed = []
    attempted = []

    if exe_prefix is None:
        prefix = []
    elif isinstance(exe_prefix, str):
        prefix = [str(exe_prefix)]
    elif isinstance(exe_prefix, list):
        prefix = exe_prefix
    else:
        raise TypeError("exe_prefix must be None, str, or list")

    for exe_name in sorted(os.listdir(dirp)):
        exe_path = os.path.join(dirp, exe_name)
        if os.path.isfile(exe_path) and os.access(exe_path, os.X_OK):
            attempted.append(exe_path)
            try:
                # Use shell=True so that if the user omits the #!, there is
                # still some chance it will succeed.
                subp(prefix + [exe_path], capture=False, shell=True)
            except ProcessExecutionError as e:
                logexc(LOG, "Failed running %s [%s]", exe_path, e.exit_code)
                failed.append(e)

    if failed and attempted:
        raise RuntimeError('Runparts: %s failures in %s attempted commands'
                           % (len(failed), len(attempted)))


# read_optional_seed
# returns boolean indicating success or failure (presense of files)
# if files are present, populates 'fill' dictionary with 'user-data' and
# 'meta-data' entries
def read_optional_seed(fill, base="", ext="", timeout=5):
    try:
        (md, ud) = read_seeded(base, ext, timeout)
        fill['user-data'] = ud
        fill['meta-data'] = md
        return True
    except url_helper.UrlError as e:
        if e.code == url_helper.NOT_FOUND:
            return False
        raise


def fetch_ssl_details(paths=None):
    ssl_details = {}
    # Lookup in these locations for ssl key/cert files
    ssl_cert_paths = [
        '/var/lib/cloud/data/ssl',
        '/var/lib/cloud/instance/data/ssl',
    ]
    if paths:
        ssl_cert_paths.extend([
            os.path.join(paths.get_ipath_cur('data'), 'ssl'),
            os.path.join(paths.get_cpath('data'), 'ssl'),
        ])
    ssl_cert_paths = uniq_merge(ssl_cert_paths)
    ssl_cert_paths = [d for d in ssl_cert_paths if d and os.path.isdir(d)]
    cert_file = None
    for d in ssl_cert_paths:
        if os.path.isfile(os.path.join(d, 'cert.pem')):
            cert_file = os.path.join(d, 'cert.pem')
            break
    key_file = None
    for d in ssl_cert_paths:
        if os.path.isfile(os.path.join(d, 'key.pem')):
            key_file = os.path.join(d, 'key.pem')
            break
    if cert_file and key_file:
        ssl_details['cert_file'] = cert_file
        ssl_details['key_file'] = key_file
    elif cert_file:
        ssl_details['cert_file'] = cert_file
    return ssl_details


def read_file_or_url(url, timeout=5, retries=10,
                     headers=None, data=None, sec_between=1, ssl_details=None,
                     headers_cb=None, exception_cb=None):
    url = url.lstrip()
    if url.startswith("/"):
        url = "file://%s" % url
    if url.lower().startswith("file://"):
        if data:
            LOG.warn("Unable to post data to file resource %s", url)
        file_path = url[len("file://"):]
        try:
            contents = load_file(file_path)
        except IOError as e:
            code = e.errno
            if e.errno == errno.ENOENT:
                code = url_helper.NOT_FOUND
            raise url_helper.UrlError(cause=e, code=code, headers=None)
        return url_helper.FileResponse(file_path, contents=contents)
    else:
        return url_helper.readurl(url,
                                  timeout=timeout,
                                  retries=retries,
                                  headers=headers,
                                  headers_cb=headers_cb,
                                  data=data,
                                  sec_between=sec_between,
                                  ssl_details=ssl_details,
                                  exception_cb=exception_cb)


def load_yaml(blob, default=None, allowed=(dict,)):
    loaded = default
    try:
        blob = str(blob)
        LOG.debug(("Attempting to load yaml from string "
                 "of length %s with allowed root types %s"),
                 len(blob), allowed)
        converted = safeyaml.load(blob)
        if not isinstance(converted, allowed):
            # Yes this will just be caught, but thats ok for now...
            raise TypeError(("Yaml load allows %s root types,"
                             " but got %s instead") %
                            (allowed, type_utils.obj_name(converted)))
        loaded = converted
    except (yaml.YAMLError, TypeError, ValueError):
        if len(blob) == 0:
            LOG.debug("load_yaml given empty string, returning default")
        else:
            logexc(LOG, "Failed loading yaml blob")
    return loaded


def read_seeded(base="", ext="", timeout=5, retries=10, file_retries=0):
    if base.startswith("/"):
        base = "file://%s" % base

    # default retries for file is 0. for network is 10
    if base.startswith("file://"):
        retries = file_retries

    if base.find("%s") >= 0:
        ud_url = base % ("user-data" + ext)
        md_url = base % ("meta-data" + ext)
    else:
        ud_url = "%s%s%s" % (base, "user-data", ext)
        md_url = "%s%s%s" % (base, "meta-data", ext)

    md_resp = read_file_or_url(md_url, timeout, retries, file_retries)
    md = None
    if md_resp.ok():
        md_str = str(md_resp)
        md = load_yaml(md_str, default={})

    ud_resp = read_file_or_url(ud_url, timeout, retries, file_retries)
    ud = None
    if ud_resp.ok():
        ud_str = str(ud_resp)
        ud = ud_str

    return (md, ud)


def read_conf_d(confd):
    # Get reverse sorted list (later trumps newer)
    confs = sorted(os.listdir(confd), reverse=True)

    # Remove anything not ending in '.cfg'
    confs = [f for f in confs if f.endswith(".cfg")]

    # Remove anything not a file
    confs = [f for f in confs
             if os.path.isfile(os.path.join(confd, f))]

    # Load them all so that they can be merged
    cfgs = []
    for fn in confs:
        cfgs.append(read_conf(os.path.join(confd, fn)))

    return mergemanydict(cfgs)


def read_conf_with_confd(cfgfile):
    cfg = read_conf(cfgfile)

    confd = False
    if "conf_d" in cfg:
        confd = cfg['conf_d']
        if confd:
            if not isinstance(confd, (str, basestring)):
                raise TypeError(("Config file %s contains 'conf_d' "
                                 "with non-string type %s") %
                                 (cfgfile, type_utils.obj_name(confd)))
            else:
                confd = str(confd).strip()
    elif os.path.isdir("%s.d" % cfgfile):
        confd = "%s.d" % cfgfile

    if not confd or not os.path.isdir(confd):
        return cfg

    # Conf.d settings override input configuration
    confd_cfg = read_conf_d(confd)
    return mergemanydict([confd_cfg, cfg])


def read_cc_from_cmdline(cmdline=None):
    # this should support reading cloud-config information from
    # the kernel command line.  It is intended to support content of the
    # format:
    #  cc: <yaml content here> [end_cc]
    # this would include:
    # cc: ssh_import_id: [smoser, kirkland]\\n
    # cc: ssh_import_id: [smoser, bob]\\nruncmd: [ [ ls, -l ], echo hi ] end_cc
    # cc:ssh_import_id: [smoser] end_cc cc:runcmd: [ [ ls, -l ] ] end_cc
    if cmdline is None:
        cmdline = get_cmdline()

    tag_begin = "cc:"
    tag_end = "end_cc"
    begin_l = len(tag_begin)
    end_l = len(tag_end)
    clen = len(cmdline)
    tokens = []
    begin = cmdline.find(tag_begin)
    while begin >= 0:
        end = cmdline.find(tag_end, begin + begin_l)
        if end < 0:
            end = clen
        tokens.append(cmdline[begin + begin_l:end].lstrip().replace("\\n",
                                                                    "\n"))

        begin = cmdline.find(tag_begin, end + end_l)

    return '\n'.join(tokens)


def dos2unix(contents):
    # find first end of line
    pos = contents.find('\n')
    if pos <= 0 or contents[pos - 1] != '\r':
        return contents
    return contents.replace('\r\n', '\n')


def get_hostname_fqdn(cfg, cloud):
    # return the hostname and fqdn from 'cfg'.  If not found in cfg,
    # then fall back to data from cloud
    if "fqdn" in cfg:
        # user specified a fqdn.  Default hostname then is based off that
        fqdn = cfg['fqdn']
        hostname = get_cfg_option_str(cfg, "hostname", fqdn.split('.')[0])
    else:
        if "hostname" in cfg and cfg['hostname'].find('.') > 0:
            # user specified hostname, and it had '.' in it
            # be nice to them.  set fqdn and hostname from that
            fqdn = cfg['hostname']
            hostname = cfg['hostname'][:fqdn.find('.')]
        else:
            # no fqdn set, get fqdn from cloud.
            # get hostname from cfg if available otherwise cloud
            fqdn = cloud.get_hostname(fqdn=True)
            if "hostname" in cfg:
                hostname = cfg['hostname']
            else:
                hostname = cloud.get_hostname()
    return (hostname, fqdn)


def get_fqdn_from_hosts(hostname, filename="/etc/hosts"):
    """
    For each host a single line should be present with
      the following information:

        IP_address canonical_hostname [aliases...]

      Fields of the entry are separated by any number of  blanks  and/or  tab
      characters.  Text  from a "#" character until the end of the line is a
      comment, and is ignored. Host  names  may  contain  only  alphanumeric
      characters, minus signs ("-"), and periods (".").  They must begin with
      an  alphabetic  character  and  end  with  an  alphanumeric  character.
      Optional aliases provide for name changes, alternate spellings, shorter
      hostnames, or generic hostnames (for example, localhost).
    """
    fqdn = None
    try:
        for line in load_file(filename).splitlines():
            hashpos = line.find("#")
            if hashpos >= 0:
                line = line[0:hashpos]
            line = line.strip()
            if not line:
                continue

            # If there there is less than 3 entries
            # (IP_address, canonical_hostname, alias)
            # then ignore this line
            toks = line.split()
            if len(toks) < 3:
                continue

            if hostname in toks[2:]:
                fqdn = toks[1]
                break
    except IOError:
        pass
    return fqdn


def get_cmdline_url(names=('cloud-config-url', 'url'),
                    starts="#cloud-config", cmdline=None):
    if cmdline is None:
        cmdline = get_cmdline()

    data = keyval_str_to_dict(cmdline)
    url = None
    key = None
    for key in names:
        if key in data:
            url = data[key]
            break

    if not url:
        return (None, None, None)

    resp = read_file_or_url(url)
    if resp.contents.startswith(starts) and resp.ok():
        return (key, url, str(resp))

    return (key, url, None)


def is_resolvable(name):
    """determine if a url is resolvable, return a boolean
    This also attempts to be resilent against dns redirection.

    Note, that normal nsswitch resolution is used here.  So in order
    to avoid any utilization of 'search' entries in /etc/resolv.conf
    we have to append '.'.

    The top level 'invalid' domain is invalid per RFC.  And example.com
    should also not exist.  The random entry will be resolved inside
    the search list.
    """
    global _DNS_REDIRECT_IP
    if _DNS_REDIRECT_IP is None:
        badips = set()
        badnames = ("does-not-exist.example.com.", "example.invalid.",
                    rand_str())
        badresults = {}
        for iname in badnames:
            try:
                result = socket.getaddrinfo(iname, None, 0, 0,
                    socket.SOCK_STREAM, socket.AI_CANONNAME)
                badresults[iname] = []
                for (_fam, _stype, _proto, cname, sockaddr) in result:
                    badresults[iname].append("%s: %s" % (cname, sockaddr[0]))
                    badips.add(sockaddr[0])
            except (socket.gaierror, socket.error):
                pass
        _DNS_REDIRECT_IP = badips
        if badresults:
            LOG.debug("detected dns redirection: %s", badresults)

    try:
        result = socket.getaddrinfo(name, None)
        # check first result's sockaddr field
        addr = result[0][4][0]
        if addr in _DNS_REDIRECT_IP:
            return False
        return True
    except (socket.gaierror, socket.error):
        return False


def get_hostname():
    hostname = socket.gethostname()
    return hostname


def gethostbyaddr(ip):
    try:
        return socket.gethostbyaddr(ip)[0]
    except socket.herror:
        return None


def is_resolvable_url(url):
    """determine if this url is resolvable (existing or ip)."""
    return is_resolvable(urlparse.urlparse(url).hostname)


def search_for_mirror(candidates):
    """
    Search through a list of mirror urls for one that works
    This needs to return quickly.
    """
    for cand in candidates:
        try:
            # Allow either a proper URL or a bare hostname / IP
            if is_resolvable_url(cand) or is_resolvable(cand):
                return cand
        except Exception:
            pass
    return None


def close_stdin():
    """
    reopen stdin as /dev/null so even subprocesses or other os level things get
    /dev/null as input.

    if _CLOUD_INIT_SAVE_STDIN is set in environment to a non empty and true
    value then input will not be closed (useful for debugging).
    """
    if is_true(os.environ.get("_CLOUD_INIT_SAVE_STDIN")):
        return
    with open(os.devnull) as fp:
        os.dup2(fp.fileno(), sys.stdin.fileno())


def find_devs_with(criteria=None, oformat='device',
                    tag=None, no_cache=False, path=None):
    """
    find devices matching given criteria (via blkid)
    criteria can be *one* of:
      TYPE=<filesystem>
      LABEL=<label>
      UUID=<uuid>
    """
    blk_id_cmd = ['blkid']
    options = []
    if criteria:
        # Search for block devices with tokens named NAME that
        # have the value 'value' and display any devices which are found.
        # Common values for NAME include  TYPE, LABEL, and UUID.
        # If there are no devices specified on the command line,
        # all block devices will be searched; otherwise,
        # only search the devices specified by the user.
        options.append("-t%s" % (criteria))
    if tag:
        # For each (specified) device, show only the tags that match tag.
        options.append("-s%s" % (tag))
    if no_cache:
        # If you want to start with a clean cache
        # (i.e. don't report devices previously scanned
        # but not necessarily available at this time), specify /dev/null.
        options.extend(["-c", "/dev/null"])
    if oformat:
        # Display blkid's output using the specified format.
        # The format parameter may be:
        # full, value, list, device, udev, export
        options.append('-o%s' % (oformat))
    if path:
        options.append(path)
    cmd = blk_id_cmd + options
    # See man blkid for why 2 is added
    (out, _err) = subp(cmd, rcs=[0, 2])
    entries = []
    for line in out.splitlines():
        line = line.strip()
        if line:
            entries.append(line)
    return entries


def peek_file(fname, max_bytes):
    LOG.debug("Peeking at %s (max_bytes=%s)", fname, max_bytes)
    with open(fname, 'rb') as ifh:
        return ifh.read(max_bytes)


def uniq_list(in_list):
    out_list = []
    for i in in_list:
        if i in out_list:
            continue
        else:
            out_list.append(i)
    return out_list


def load_file(fname, read_cb=None, quiet=False):
    LOG.debug("Reading from %s (quiet=%s)", fname, quiet)
    ofh = StringIO()
    try:
        with open(fname, 'rb') as ifh:
            pipe_in_out(ifh, ofh, chunk_cb=read_cb)
    except IOError as e:
        if not quiet:
            raise
        if e.errno != errno.ENOENT:
            raise
    contents = ofh.getvalue()
    LOG.debug("Read %s bytes from %s", len(contents), fname)
    return contents


def get_cmdline():
    if 'DEBUG_PROC_CMDLINE' in os.environ:
        cmdline = os.environ["DEBUG_PROC_CMDLINE"]
    else:
        try:
            cmdline = load_file("/proc/cmdline").strip()
        except:
            cmdline = ""
    return cmdline


def pipe_in_out(in_fh, out_fh, chunk_size=1024, chunk_cb=None):
    bytes_piped = 0
    while True:
        data = in_fh.read(chunk_size)
        if data == '':
            break
        else:
            out_fh.write(data)
            bytes_piped += len(data)
            if chunk_cb:
                chunk_cb(bytes_piped)
    out_fh.flush()
    return bytes_piped


def chownbyid(fname, uid=None, gid=None):
    if uid in [None, -1] and gid in [None, -1]:
        # Nothing to do
        return
    LOG.debug("Changing the ownership of %s to %s:%s", fname, uid, gid)
    os.chown(fname, uid, gid)


def chownbyname(fname, user=None, group=None):
    uid = -1
    gid = -1
    try:
        if user:
            uid = pwd.getpwnam(user).pw_uid
        if group:
            gid = grp.getgrnam(group).gr_gid
    except KeyError as e:
        raise OSError("Unknown user or group: %s" % (e))
    chownbyid(fname, uid, gid)


# Always returns well formated values
# cfg is expected to have an entry 'output' in it, which is a dictionary
# that includes entries for 'init', 'config', 'final' or 'all'
#   init: /var/log/cloud.out
#   config: [ ">> /var/log/cloud-config.out", /var/log/cloud-config.err ]
#   final:
#     output: "| logger -p"
#     error: "> /dev/null"
# this returns the specific 'mode' entry, cleanly formatted, with value
def get_output_cfg(cfg, mode):
    ret = [None, None]
    if not cfg or 'output' not in cfg:
        return ret

    outcfg = cfg['output']
    if mode in outcfg:
        modecfg = outcfg[mode]
    else:
        if 'all' not in outcfg:
            return ret
        # if there is a 'all' item in the output list
        # then it applies to all users of this (init, config, final)
        modecfg = outcfg['all']

    # if value is a string, it specifies stdout and stderr
    if isinstance(modecfg, str):
        ret = [modecfg, modecfg]

    # if its a list, then we expect (stdout, stderr)
    if isinstance(modecfg, list):
        if len(modecfg) > 0:
            ret[0] = modecfg[0]
        if len(modecfg) > 1:
            ret[1] = modecfg[1]

    # if it is a dictionary, expect 'out' and 'error'
    # items, which indicate out and error
    if isinstance(modecfg, dict):
        if 'output' in modecfg:
            ret[0] = modecfg['output']
        if 'error' in modecfg:
            ret[1] = modecfg['error']

    # if err's entry == "&1", then make it same as stdout
    # as in shell syntax of "echo foo >/dev/null 2>&1"
    if ret[1] == "&1":
        ret[1] = ret[0]

    swlist = [">>", ">", "|"]
    for i in range(len(ret)):
        if not ret[i]:
            continue
        val = ret[i].lstrip()
        found = False
        for s in swlist:
            if val.startswith(s):
                val = "%s %s" % (s, val[len(s):].strip())
                found = True
                break
        if not found:
            # default behavior is append
            val = "%s %s" % (">>", val.strip())
        ret[i] = val

    return ret


def logexc(log, msg, *args):
    # Setting this here allows this to change
    # levels easily (not always error level)
    # or even desirable to have that much junk
    # coming out to a non-debug stream
    if msg:
        log.warn(msg, *args)
    # Debug gets the full trace
    log.debug(msg, exc_info=1, *args)


def hash_blob(blob, routine, mlen=None):
    hasher = hashlib.new(routine)
    hasher.update(blob)
    digest = hasher.hexdigest()
    # Don't get to long now
    if mlen is not None:
        return digest[0:mlen]
    else:
        return digest


def is_user(name):
    try:
        if pwd.getpwnam(name):
            return True
    except KeyError:
        return False


def is_group(name):
    try:
        if grp.getgrnam(name):
            return True
    except KeyError:
        return False


def rename(src, dest):
    LOG.debug("Renaming %s to %s", src, dest)
    # TODO(harlowja) use a se guard here??
    os.rename(src, dest)


def ensure_dirs(dirlist, mode=0755):
    for d in dirlist:
        ensure_dir(d, mode)


def read_write_cmdline_url(target_fn):
    if not os.path.exists(target_fn):
        try:
            (key, url, content) = get_cmdline_url()
        except:
            logexc(LOG, "Failed fetching command line url")
            return
        try:
            if key and content:
                write_file(target_fn, content, mode=0600)
                LOG.debug(("Wrote to %s with contents of command line"
                          " url %s (len=%s)"), target_fn, url, len(content))
            elif key and not content:
                LOG.debug(("Command line key %s with url"
                          " %s had no contents"), key, url)
        except:
            logexc(LOG, "Failed writing url content to %s", target_fn)


def yaml_dumps(obj):
    formatted = yaml.dump(obj,
                    line_break="\n",
                    indent=4,
                    explicit_start=True,
                    explicit_end=True,
                    default_flow_style=False)
    return formatted


def ensure_dir(path, mode=None):
    if not os.path.isdir(path):
        # Make the dir and adjust the mode
        with SeLinuxGuard(os.path.dirname(path), recursive=True):
            os.makedirs(path)
        chmod(path, mode)
    else:
        # Just adjust the mode
        chmod(path, mode)


@contextlib.contextmanager
def unmounter(umount):
    try:
        yield umount
    finally:
        if umount:
            umount_cmd = ["umount", umount]
            subp(umount_cmd)


def mounts():
    mounted = {}
    try:
        # Go through mounts to see what is already mounted
        if os.path.exists("/proc/mounts"):
            mount_locs = load_file("/proc/mounts").splitlines()
            method = 'proc'
        else:
            (mountoutput, _err) = subp("mount")
            mount_locs = mountoutput.splitlines()
            method = 'mount'
        mountre = r'^(/dev/[\S]+) on (/.*) \((.+), .+, (.+)\)$'
        for mpline in mount_locs:
            # Linux: /dev/sda1 on /boot type ext4 (rw,relatime,data=ordered)
            # FreeBSD: /dev/vtbd0p2 on / (ufs, local, journaled soft-updates)
            try:
                if method == 'proc':
                    (dev, mp, fstype, opts, _freq, _passno) = mpline.split()
                else:
                    m = re.search(mountre, mpline)
                    dev = m.group(1)
                    mp = m.group(2)
                    fstype = m.group(3)
                    opts = m.group(4)
            except:
                continue
            # If the name of the mount point contains spaces these
            # can be escaped as '\040', so undo that..
            mp = mp.replace("\\040", " ")
            mounted[dev] = {
                'fstype': fstype,
                'mountpoint': mp,
                'opts': opts,
            }
        LOG.debug("Fetched %s mounts from %s", mounted, method)
    except (IOError, OSError):
        logexc(LOG, "Failed fetching mount points")
    return mounted


def mount_cb(device, callback, data=None, rw=False, mtype=None, sync=True):
    """
    Mount the device, call method 'callback' passing the directory
    in which it was mounted, then unmount.  Return whatever 'callback'
    returned.  If data != None, also pass data to callback.

    mtype is a filesystem type.  it may be a list, string (a single fsname)
    or a list of fsnames.
    """

    if isinstance(mtype, str):
        mtypes = [mtype]
    elif isinstance(mtype, (list, tuple)):
        mtypes = list(mtype)
    elif mtype is None:
        mtypes = None

    # clean up 'mtype' input a bit based on platform.
    platsys = platform.system().lower()
    if platsys == "linux":
        if mtypes is None:
            mtypes = ["auto"]
    elif platsys.endswith("bsd"):
        if mtypes is None:
            mtypes = ['ufs', 'cd9660', 'vfat']
        for index, mtype in enumerate(mtypes):
            if mtype == "iso9660":
                mtypes[index] = "cd9660"
    else:
        # we cannot do a smart "auto", so just call 'mount' once with no -t
        mtypes = ['']

    mounted = mounts()
    with tempdir() as tmpd:
        umount = False
        if device in mounted:
            mountpoint = mounted[device]['mountpoint']
        else:
            for mtype in mtypes:
                mountpoint = None
                try:
                    mountcmd = ['mount']
                    mountopts = []
                    if rw:
                        mountopts.append('rw')
                    else:
                        mountopts.append('ro')
                    if sync:
                        # This seems like the safe approach to do
                        # (ie where this is on by default)
                        mountopts.append("sync")
                    if mountopts:
                        mountcmd.extend(["-o", ",".join(mountopts)])
                    if mtype:
                        mountcmd.extend(['-t', mtype])
                    mountcmd.append(device)
                    mountcmd.append(tmpd)
                    subp(mountcmd)
                    umount = tmpd  # This forces it to be unmounted (when set)
                    mountpoint = tmpd
                    break
                except (IOError, OSError) as exc:
                    LOG.debug("Failed mount of '%s' as '%s': %s",
                              device, mtype, exc)
                    pass
            if not mountpoint:
                raise MountFailedError("Failed mounting %s to %s due to: %s" %
                                       (device, tmpd, exc))

        # Be nice and ensure it ends with a slash
        if not mountpoint.endswith("/"):
            mountpoint += "/"
        with unmounter(umount):
            if data is None:
                ret = callback(mountpoint)
            else:
                ret = callback(mountpoint, data)
            return ret


def get_builtin_cfg():
    # Deep copy so that others can't modify
    return obj_copy.deepcopy(CFG_BUILTIN)


def sym_link(source, link, force=False):
    LOG.debug("Creating symbolic link from %r => %r", link, source)
    if force and os.path.exists(link):
        del_file(link)
    os.symlink(source, link)


def del_file(path):
    LOG.debug("Attempting to remove %s", path)
    try:
        os.unlink(path)
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise e


def copy(src, dest):
    LOG.debug("Copying %s to %s", src, dest)
    shutil.copy(src, dest)


def time_rfc2822():
    try:
        ts = time.strftime("%a, %d %b %Y %H:%M:%S %z", time.gmtime())
    except:
        ts = "??"
    return ts


def uptime():
    uptime_str = '??'
    method = 'unknown'
    try:
        if os.path.exists("/proc/uptime"):
            method = '/proc/uptime'
            contents = load_file("/proc/uptime").strip()
            if contents:
                uptime_str = contents.split()[0]
        else:
            method = 'ctypes'
            libc = ctypes.CDLL('/lib/libc.so.7')
            size = ctypes.c_size_t()
            buf = ctypes.c_int()
            size.value = ctypes.sizeof(buf)
            libc.sysctlbyname("kern.boottime", ctypes.byref(buf),
                              ctypes.byref(size), None, 0)
            now = time.time()
            bootup = buf.value
            uptime_str = now - bootup

    except:
        logexc(LOG, "Unable to read uptime using method: %s" % method)
    return uptime_str


def append_file(path, content):
    write_file(path, content, omode="ab", mode=None)


def ensure_file(path, mode=0644):
    write_file(path, content='', omode="ab", mode=mode)


def safe_int(possible_int):
    try:
        return int(possible_int)
    except (ValueError, TypeError):
        return None


def chmod(path, mode):
    real_mode = safe_int(mode)
    if path and real_mode:
        with SeLinuxGuard(path):
            os.chmod(path, real_mode)


def write_file(filename, content, mode=0644, omode="wb"):
    """
    Writes a file with the given content and sets the file mode as specified.
    Resotres the SELinux context if possible.

    @param filename: The full path of the file to write.
    @param content: The content to write to the file.
    @param mode: The filesystem mode to set on the file.
    @param omode: The open mode used when opening the file (r, rb, a, etc.)
    """
    ensure_dir(os.path.dirname(filename))
    LOG.debug("Writing to %s - %s: [%o] %s bytes",
               filename, omode, mode, len(content))
    with SeLinuxGuard(path=filename):
        with open(filename, omode) as fh:
            fh.write(content)
            fh.flush()
    chmod(filename, mode)


def delete_dir_contents(dirname):
    """
    Deletes all contents of a directory without deleting the directory itself.

    @param dirname: The directory whose contents should be deleted.
    """
    for node in os.listdir(dirname):
        node_fullpath = os.path.join(dirname, node)
        if os.path.isdir(node_fullpath):
            del_dir(node_fullpath)
        else:
            del_file(node_fullpath)


def subp(args, data=None, rcs=None, env=None, capture=True, shell=False,
         close_stdin=False, pipe_cat=False, logstring=False):
    if data and close_stdin:
        raise ValueError('Incompatible parameters: data and close_stdin')
    if rcs is None:
        rcs = [0]
    try:

        if not logstring:
            LOG.debug(("Running command %s with allowed return codes %s"
                       " (shell=%s, capture=%s)"), args, rcs, shell, capture)
        else:
            LOG.debug(("Running hidden command to protect sensitive "
                       "input/output logstring: %s"), logstring)

        if not capture:
            stdout = None
            stderr = None
        else:
            stdout = subprocess.PIPE
            stderr = subprocess.PIPE
        stdin = subprocess.PIPE
        # Some processes are less chatty when piped through cat, because they
        # won't detect a terminal (yum being a prime example).
        if pipe_cat:
            cat = subprocess.Popen('cat', stdout=stdout, stderr=stderr,
                                   stdin=subprocess.PIPE)
            sp = subprocess.Popen(args, stdout=cat.stdin,
                                  stderr=stderr, stdin=stdin,
                                  env=env, shell=shell)
            if close_stdin:
                sp.stdin.close()
            (_out, err) = sp.communicate(data)
            (out, _err) = cat.communicate()
        else:
            sp = subprocess.Popen(args, stdout=stdout,
                            stderr=stderr, stdin=stdin,
                            env=env, shell=shell)
            if close_stdin:
                sp.stdin.close()
            (out, err) = sp.communicate(data)
    except OSError as e:
        raise ProcessExecutionError(cmd=args, reason=e)
    rc = sp.returncode
    if rc not in rcs:
        raise ProcessExecutionError(stdout=out, stderr=err,
                                    exit_code=rc,
                                    cmd=args)
    # Just ensure blank instead of none?? (iff capturing)
    if not out and capture:
        out = ''
    if not err and capture:
        err = ''
    return (out, err)


def make_header(comment_char="#", base='created'):
    ci_ver = version.version_string()
    header = str(comment_char)
    header += " %s by cloud-init v. %s" % (base.title(), ci_ver)
    header += " on %s" % time_rfc2822()
    return header


def abs_join(*paths):
    return os.path.abspath(os.path.join(*paths))


# shellify, takes a list of commands
#  for each entry in the list
#    if it is an array, shell protect it (with single ticks)
#    if it is a string, do nothing
def shellify(cmdlist, add_header=True):
    content = ''
    if add_header:
        content += "#!/bin/sh\n"
    escaped = "%s%s%s%s" % ("'", '\\', "'", "'")
    cmds_made = 0
    for args in cmdlist:
        # If the item is a list, wrap all items in single tick.
        # If its not, then just write it directly.
        if isinstance(args, list):
            fixed = []
            for f in args:
                fixed.append("'%s'" % (str(f).replace("'", escaped)))
            content = "%s%s\n" % (content, ' '.join(fixed))
            cmds_made += 1
        elif isinstance(args, (str, basestring)):
            content = "%s%s\n" % (content, args)
            cmds_made += 1
        else:
            raise RuntimeError(("Unable to shellify type %s"
                                " which is not a list or string")
                               % (type_utils.obj_name(args)))
    LOG.debug("Shellified %s commands.", cmds_made)
    return content


def strip_prefix_suffix(line, prefix=None, suffix=None):
    if prefix and line.startswith(prefix):
        line = line[len(prefix):]
    if suffix and line.endswith(suffix):
        line = line[:-len(suffix)]
    return line


def is_container():
    """
    Checks to see if this code running in a container of some sort
    """

    for helper in CONTAINER_TESTS:
        try:
            # try to run a helper program. if it returns true/zero
            # then we're inside a container. otherwise, no
            subp([helper])
            return True
        except (IOError, OSError):
            pass

    # this code is largely from the logic in
    # ubuntu's /etc/init/container-detect.conf
    try:
        # Detect old-style libvirt
        # Detect OpenVZ containers
        pid1env = get_proc_env(1)
        if "container" in pid1env:
            return True
        if "LIBVIRT_LXC_UUID" in pid1env:
            return True
    except (IOError, OSError):
        pass

    # Detect OpenVZ containers
    if os.path.isdir("/proc/vz") and not os.path.isdir("/proc/bc"):
        return True

    try:
        # Detect Vserver containers
        lines = load_file("/proc/self/status").splitlines()
        for line in lines:
            if line.startswith("VxID:"):
                (_key, val) = line.strip().split(":", 1)
                if val != "0":
                    return True
    except (IOError, OSError):
        pass

    return False


def get_proc_env(pid):
    """
    Return the environment in a dict that a given process id was started with.
    """

    env = {}
    fn = os.path.join("/proc/", str(pid), "environ")
    try:
        contents = load_file(fn)
        toks = contents.split("\x00")
        for tok in toks:
            if tok == "":
                continue
            (name, val) = tok.split("=", 1)
            if name:
                env[name] = val
    except (IOError, OSError):
        pass
    return env


def keyval_str_to_dict(kvstring):
    ret = {}
    for tok in kvstring.split():
        try:
            (key, val) = tok.split("=", 1)
        except ValueError:
            key = tok
            val = True
        ret[key] = val
    return ret


def is_partition(device):
    if device.startswith("/dev/"):
        device = device[5:]

    return os.path.isfile("/sys/class/block/%s/partition" % device)


def expand_package_list(version_fmt, pkgs):
    # we will accept tuples, lists of tuples, or just plain lists
    if not isinstance(pkgs, list):
        pkgs = [pkgs]

    pkglist = []
    for pkg in pkgs:
        if isinstance(pkg, basestring):
            pkglist.append(pkg)
            continue

        if isinstance(pkg, (tuple, list)):
            if len(pkg) < 1 or len(pkg) > 2:
                raise RuntimeError("Invalid package & version tuple.")

            if len(pkg) == 2 and pkg[1]:
                pkglist.append(version_fmt % tuple(pkg))
                continue

            pkglist.append(pkg[0])

        else:
            raise RuntimeError("Invalid package type.")

    return pkglist


def parse_mount_info(path, mountinfo_lines, log=LOG):
    """Return the mount information for PATH given the lines from
    /proc/$$/mountinfo."""

    path_elements = [e for e in path.split('/') if e]
    devpth = None
    fs_type = None
    match_mount_point = None
    match_mount_point_elements = None
    for i, line in enumerate(mountinfo_lines):
        parts = line.split()

        # Completely fail if there is anything in any line that is
        # unexpected, as continuing to parse past a bad line could
        # cause an incorrect result to be returned, so it's better
        # return nothing than an incorrect result.

        # The minimum number of elements in a valid line is 10.
        if len(parts) < 10:
            log.debug("Line %d has two few columns (%d): %s",
                      i + 1, len(parts), line)
            return None

        mount_point = parts[4]
        mount_point_elements = [e for e in mount_point.split('/') if e]

        # Ignore mounts deeper than the path in question.
        if len(mount_point_elements) > len(path_elements):
            continue

        # Ignore mounts where the common path is not the same.
        l = min(len(mount_point_elements), len(path_elements))
        if mount_point_elements[0:l] != path_elements[0:l]:
            continue

        # Ignore mount points higher than an already seen mount
        # point.
        if (match_mount_point_elements is not None and
                len(match_mount_point_elements) > len(mount_point_elements)):
            continue

        # Find the '-' which terminates a list of optional columns to
        # find the filesystem type and the path to the device.  See
        # man 5 proc for the format of this file.
        try:
            i = parts.index('-')
        except ValueError:
            log.debug("Did not find column named '-' in line %d: %s",
                      i + 1, line)
            return None

        # Get the path to the device.
        try:
            fs_type = parts[i + 1]
            devpth = parts[i + 2]
        except IndexError:
            log.debug("Too few columns after '-' column in line %d: %s",
                      i + 1, line)
            return None

        match_mount_point = mount_point
        match_mount_point_elements = mount_point_elements

    if devpth and fs_type and match_mount_point:
        return (devpth, fs_type, match_mount_point)
    else:
        return None


def parse_mtab(path):
    """On older kernels there's no /proc/$$/mountinfo, so use mtab."""
    for line in load_file("/etc/mtab").splitlines():
        devpth, mount_point, fs_type = line.split()[:3]
        if mount_point == path:
            return devpth, fs_type, mount_point
    return None


def parse_mount(path):
    (mountoutput, _err) = subp("mount")
    mount_locs = mountoutput.splitlines()
    for line in mount_locs:
        m = re.search(r'^(/dev/[\S]+) on (/.*) \((.+), .+, (.+)\)$', line)
        devpth = m.group(1)
        mount_point = m.group(2)
        fs_type = m.group(3)
        if mount_point == path:
            return devpth, fs_type, mount_point
    return None


def get_mount_info(path, log=LOG):
    # Use /proc/$$/mountinfo to find the device where path is mounted.
    # This is done because with a btrfs filesystem using os.stat(path)
    # does not return the ID of the device.
    #
    # Here, / has a device of 18 (decimal).
    #
    # $ stat /
    #   File: '/'
    #   Size: 234               Blocks: 0          IO Block: 4096   directory
    # Device: 12h/18d   Inode: 256         Links: 1
    # Access: (0755/drwxr-xr-x)  Uid: (    0/    root)   Gid: (    0/    root)
    # Access: 2013-01-13 07:31:04.358011255 +0000
    # Modify: 2013-01-13 18:48:25.930011255 +0000
    # Change: 2013-01-13 18:48:25.930011255 +0000
    #  Birth: -
    #
    # Find where / is mounted:
    #
    # $ mount | grep ' / '
    # /dev/vda1 on / type btrfs (rw,subvol=@,compress=lzo)
    #
    # And the device ID for /dev/vda1 is not 18:
    #
    # $ ls -l /dev/vda1
    # brw-rw---- 1 root disk 253, 1 Jan 13 08:29 /dev/vda1
    #
    # So use /proc/$$/mountinfo to find the device underlying the
    # input path.
    mountinfo_path = '/proc/%s/mountinfo' % os.getpid()
    if os.path.exists(mountinfo_path):
        lines = load_file(mountinfo_path).splitlines()
        return parse_mount_info(path, lines, log)
    elif os.path.exists("/etc/mtab"):
        return parse_mtab(path)
    else:
        return parse_mount(path)


def which(program):
    # Return path of program for execution if found in path
    def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

    _fpath, _ = os.path.split(program)
    if _fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ.get("PATH", "").split(os.pathsep):
            path = path.strip('"')
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file

    return None


def log_time(logfunc, msg, func, args=None, kwargs=None, get_uptime=False):
    if args is None:
        args = []
    if kwargs is None:
        kwargs = {}

    start = time.time()

    ustart = None
    if get_uptime:
        try:
            ustart = float(uptime())
        except ValueError:
            pass

    try:
        ret = func(*args, **kwargs)
    finally:
        delta = time.time() - start
        udelta = None
        if ustart is not None:
            try:
                udelta = float(uptime()) - ustart
            except ValueError:
                pass

        tmsg = " took %0.3f seconds" % delta
        if get_uptime:
            if isinstance(udelta, (float)):
                tmsg += " (%0.2f)" % udelta
            else:
                tmsg += " (N/A)"
        try:
            logfunc(msg + tmsg)
        except:
            pass
    return ret


def expand_dotted_devname(dotted):
    toks = dotted.rsplit(".", 1)
    if len(toks) > 1:
        return toks
    else:
        return (dotted, None)


def pathprefix2dict(base, required=None, optional=None, delim=os.path.sep):
    # return a dictionary populated with keys in 'required' and 'optional'
    # by reading files in prefix + delim + entry
    if required is None:
        required = []
    if optional is None:
        optional = []

    missing = []
    ret = {}
    for f in required + optional:
        try:
            ret[f] = load_file(base + delim + f, quiet=False)
        except IOError as e:
            if e.errno != errno.ENOENT:
                raise
            if f in required:
                missing.append(f)

    if len(missing):
        raise ValueError("Missing required files: %s", ','.join(missing))

    return ret


def read_meminfo(meminfo="/proc/meminfo", raw=False):
    # read a /proc/meminfo style file and return
    # a dict with 'total', 'free', and 'available'
    mpliers = {'kB': 2**10, 'mB': 2 ** 20, 'B': 1, 'gB': 2 ** 30}
    kmap = {'MemTotal:': 'total', 'MemFree:': 'free',
            'MemAvailable:': 'available'}
    ret = {}
    for line in load_file(meminfo).splitlines():
        try:
            key, value, unit = line.split()
        except ValueError:
            key, value = line.split()
            unit = 'B'
        if raw:
            ret[key] = int(value) * mpliers[unit]
        elif key in kmap:
            ret[kmap[key]] = int(value) * mpliers[unit]

    return ret


def human2bytes(size):
    """Convert human string or integer to size in bytes
      10M => 10485760
      .5G => 536870912
    """
    size_in = size
    if size.endswith("B"):
        size = size[:-1]

    mpliers = {'B': 1, 'K': 2 ** 10, 'M': 2 ** 20, 'G': 2 ** 30, 'T': 2 ** 40}

    num = size
    mplier = 'B'
    for m in mpliers:
        if size.endswith(m):
            mplier = m
            num = size[0:-len(m)]

    try:
        num = float(num)
    except ValueError:
        raise ValueError("'%s' is not valid input." % size_in)

    if num < 0:
        raise ValueError("'%s': cannot be negative" % size_in)

    return int(num * mpliers[mplier])


def dictpath(obj, path, separator='/'):
    """
    Returns the element at a given path in a nested dictionary/list
    object.

    If the object is a dictionary, the path element is a string key. If
    the object is a list, the path element is an index.

    For instance, given the following object:

        {"hello": "world",
         "days": ["Monday", "Wednesday", "Friday"]}

    dictpath(obj, "days/-1") would return "Friday".

    This function deliberately does not catch any exceptions.
    """

    for element in path.split(separator):
        # handle empty elements (for instance, if the path starts with
        # the separator)
        if not element:
            continue

        if isinstance(obj, dict):
            obj = obj[element]
        elif isinstance(obj, (list, tuple)):
            index = int(element)
            obj = obj[index]

    return obj
