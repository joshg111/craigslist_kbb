#!/usr/bin/python2.7
# vi: ts=4 expandtab
#
#    Copyright (C) 2012 Canonical Ltd.
#    Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
#
#    Author: Scott Moser <scott.moser@canonical.com>
#    Author: Juerg Hafliger <juerg.haefliger@hp.com>
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
import pwd

from cloudinit import log as logging
from cloudinit import util

LOG = logging.getLogger(__name__)

# See: man sshd_config
DEF_SSHD_CFG = "/etc/ssh/sshd_config"

# taken from openssh source key.c/key_type_from_name
VALID_KEY_TYPES = ("rsa", "dsa", "ssh-rsa", "ssh-dss", "ecdsa",
    "ssh-rsa-cert-v00@openssh.com", "ssh-dss-cert-v00@openssh.com",
    "ssh-rsa-cert-v00@openssh.com", "ssh-dss-cert-v00@openssh.com",
    "ssh-rsa-cert-v01@openssh.com", "ssh-dss-cert-v01@openssh.com",
    "ecdsa-sha2-nistp256-cert-v01@openssh.com",
    "ecdsa-sha2-nistp384-cert-v01@openssh.com",
    "ecdsa-sha2-nistp521-cert-v01@openssh.com")


class AuthKeyLine(object):
    def __init__(self, source, keytype=None, base64=None,
                 comment=None, options=None):
        self.base64 = base64
        self.comment = comment
        self.options = options
        self.keytype = keytype
        self.source = source

    def valid(self):
        return (self.base64 and self.keytype)

    def __str__(self):
        toks = []
        if self.options:
            toks.append(self.options)
        if self.keytype:
            toks.append(self.keytype)
        if self.base64:
            toks.append(self.base64)
        if self.comment:
            toks.append(self.comment)
        if not toks:
            return self.source
        else:
            return ' '.join(toks)


class AuthKeyLineParser(object):
    """
    AUTHORIZED_KEYS FILE FORMAT
     AuthorizedKeysFile specifies the file containing public keys for public
     key authentication; if none is specified, the default is
     ~/.ssh/authorized_keys.  Each line of the file contains one key (empty
     (because of the size of the public key encoding) up to a limit of 8 kilo-
     bytes, which permits DSA keys up to 8 kilobits and RSA keys up to 16
     kilobits.  You don't want to type them in; instead, copy the
     identity.pub, id_dsa.pub, or the id_rsa.pub file and edit it.

     sshd enforces a minimum RSA key modulus size for protocol 1 and protocol
     2 keys of 768 bits.

     The options (if present) consist of comma-separated option specifica-
     tions.  No spaces are permitted, except within double quotes.  The fol-
     lowing option specifications are supported (note that option keywords are
     case-insensitive):
    """

    def _extract_options(self, ent):
        """
        The options (if present) consist of comma-separated option specifica-
         tions.  No spaces are permitted, except within double quotes.
         Note that option keywords are case-insensitive.
        """
        quoted = False
        i = 0
        while (i < len(ent) and
               ((quoted) or (ent[i] not in (" ", "\t")))):
            curc = ent[i]
            if i + 1 >= len(ent):
                i = i + 1
                break
            nextc = ent[i + 1]
            if curc == "\\" and nextc == '"':
                i = i + 1
            elif curc == '"':
                quoted = not quoted
            i = i + 1

        options = ent[0:i]

        # Return the rest of the string in 'remain'
        remain = ent[i:].lstrip()
        return (options, remain)

    def parse(self, src_line, options=None):
        # modeled after opensshes auth2-pubkey.c:user_key_allowed2
        line = src_line.rstrip("\r\n")
        if line.startswith("#") or line.strip() == '':
            return AuthKeyLine(src_line)

        def parse_ssh_key(ent):
            # return ketype, key, [comment]
            toks = ent.split(None, 2)
            if len(toks) < 2:
                raise TypeError("To few fields: %s" % len(toks))
            if toks[0] not in VALID_KEY_TYPES:
                raise TypeError("Invalid keytype %s" % toks[0])

            # valid key type and 2 or 3 fields:
            if len(toks) == 2:
                # no comment in line
                toks.append("")

            return toks

        ent = line.strip()
        try:
            (keytype, base64, comment) = parse_ssh_key(ent)
        except TypeError:
            (keyopts, remain) = self._extract_options(ent)
            if options is None:
                options = keyopts

            try:
                (keytype, base64, comment) = parse_ssh_key(remain)
            except TypeError:
                return AuthKeyLine(src_line)

        return AuthKeyLine(src_line, keytype=keytype, base64=base64,
                           comment=comment, options=options)


def parse_authorized_keys(fname):
    lines = []
    try:
        if os.path.isfile(fname):
            lines = util.load_file(fname).splitlines()
    except (IOError, OSError):
        util.logexc(LOG, "Error reading lines from %s", fname)
        lines = []

    parser = AuthKeyLineParser()
    contents = []
    for line in lines:
        contents.append(parser.parse(line))
    return contents


def update_authorized_keys(old_entries, keys):
    to_add = list(keys)

    for i in range(0, len(old_entries)):
        ent = old_entries[i]
        if not ent.valid():
            continue
        # Replace those with the same base64
        for k in keys:
            if not ent.valid():
                continue
            if k.base64 == ent.base64:
                # Replace it with our better one
                ent = k
                # Don't add it later
                if k in to_add:
                    to_add.remove(k)
        old_entries[i] = ent

    # Now append any entries we did not match above
    for key in to_add:
        old_entries.append(key)

    # Now format them back to strings...
    lines = [str(b) for b in old_entries]

    # Ensure it ends with a newline
    lines.append('')
    return '\n'.join(lines)


def users_ssh_info(username):
    pw_ent = pwd.getpwnam(username)
    if not pw_ent or not pw_ent.pw_dir:
        raise RuntimeError("Unable to get ssh info for user %r" % (username))
    return (os.path.join(pw_ent.pw_dir, '.ssh'), pw_ent)


def extract_authorized_keys(username):
    (ssh_dir, pw_ent) = users_ssh_info(username)
    auth_key_fn = None
    with util.SeLinuxGuard(ssh_dir, recursive=True):
        try:
            # The 'AuthorizedKeysFile' may contain tokens
            # of the form %T which are substituted during connection set-up.
            # The following tokens are defined: %% is replaced by a literal
            # '%', %h is replaced by the home directory of the user being
            # authenticated and %u is replaced by the username of that user.
            ssh_cfg = parse_ssh_config_map(DEF_SSHD_CFG)
            auth_key_fn = ssh_cfg.get("authorizedkeysfile", '').strip()
            if not auth_key_fn:
                auth_key_fn = "%h/.ssh/authorized_keys"
            auth_key_fn = auth_key_fn.replace("%h", pw_ent.pw_dir)
            auth_key_fn = auth_key_fn.replace("%u", username)
            auth_key_fn = auth_key_fn.replace("%%", '%')
            if not auth_key_fn.startswith('/'):
                auth_key_fn = os.path.join(pw_ent.pw_dir, auth_key_fn)
        except (IOError, OSError):
            # Give up and use a default key filename
            auth_key_fn = os.path.join(ssh_dir, 'authorized_keys')
            util.logexc(LOG, "Failed extracting 'AuthorizedKeysFile' in ssh "
                        "config from %r, using 'AuthorizedKeysFile' file "
                        "%r instead", DEF_SSHD_CFG, auth_key_fn)
    return (auth_key_fn, parse_authorized_keys(auth_key_fn))


def setup_user_keys(keys, username, options=None):
    # Make sure the users .ssh dir is setup accordingly
    (ssh_dir, pwent) = users_ssh_info(username)
    if not os.path.isdir(ssh_dir):
        util.ensure_dir(ssh_dir, mode=0700)
        util.chownbyid(ssh_dir, pwent.pw_uid, pwent.pw_gid)

    # Turn the 'update' keys given into actual entries
    parser = AuthKeyLineParser()
    key_entries = []
    for k in keys:
        key_entries.append(parser.parse(str(k), options=options))

    # Extract the old and make the new
    (auth_key_fn, auth_key_entries) = extract_authorized_keys(username)
    with util.SeLinuxGuard(ssh_dir, recursive=True):
        content = update_authorized_keys(auth_key_entries, key_entries)
        util.ensure_dir(os.path.dirname(auth_key_fn), mode=0700)
        util.write_file(auth_key_fn, content, mode=0600)
        util.chownbyid(auth_key_fn, pwent.pw_uid, pwent.pw_gid)


class SshdConfigLine(object):
    def __init__(self, line, k=None, v=None):
        self.line = line
        self._key = k
        self.value = v

    @property
    def key(self):
        if self._key is None:
            return None
        # Keywords are case-insensitive
        return self._key.lower()

    def __str__(self):
        if self._key is None:
            return str(self.line)
        else:
            v = str(self._key)
            if self.value:
                v += " " + str(self.value)
            return v


def parse_ssh_config(fname):
    # See: man sshd_config
    # The file contains keyword-argument pairs, one per line.
    # Lines starting with '#' and empty lines are interpreted as comments.
    # Note: key-words are case-insensitive and arguments are case-sensitive
    lines = []
    if not os.path.isfile(fname):
        return lines
    for line in util.load_file(fname).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            lines.append(SshdConfigLine(line))
            continue
        (key, val) = line.split(None, 1)
        lines.append(SshdConfigLine(line, key, val))
    return lines


def parse_ssh_config_map(fname):
    lines = parse_ssh_config(fname)
    if not lines:
        return {}
    ret = {}
    for line in lines:
        if not line.key:
            continue
        ret[line.key] = line.value
    return ret
