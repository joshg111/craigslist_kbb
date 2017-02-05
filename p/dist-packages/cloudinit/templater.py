# vi: ts=4 expandtab
#
#    Copyright (C) 2012 Canonical Ltd.
#    Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
#    Copyright (C) 2012 Yahoo! Inc.
#    Copyright (C) 2015 Amazon.com, Inc. or its affiliates.
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

import collections
import re

try:
    from Cheetah.Template import Template as CTemplate
    CHEETAH_AVAILABLE = True
except (ImportError, AttributeError):
    CHEETAH_AVAILABLE = False

try:
    import jinja2
    from jinja2 import Template as JTemplate
    JINJA_AVAILABLE = True
except (ImportError, AttributeError):
    JINJA_AVAILABLE = False

from cloudinit import log as logging
from cloudinit import type_utils as tu
from cloudinit import util

LOG = logging.getLogger(__name__)
TYPE_MATCHER = re.compile(r"##\s*template:(.*)", re.I)
BASIC_MATCHER = re.compile(r'\$\{([A-Za-z0-9_.]+)\}|\$([A-Za-z0-9_.]+)')


def basic_render(content, params):
    """This does simple replacement of bash variable like templates.

    It identifies patterns like ${a} or $a and can also identify patterns like
    ${a.b} or $a.b which will look for a key 'b' in the dictionary rooted
    by key 'a'.
    """

    def replacer(match):
        # Only 1 of the 2 groups will actually have a valid entry.
        name = match.group(1)
        if name is None:
            name = match.group(2)
        if name is None:
            raise RuntimeError("Match encountered but no valid group present")
        path = collections.deque(name.split("."))
        selected_params = params
        while len(path) > 1:
            key = path.popleft()
            if not isinstance(selected_params, dict):
                raise TypeError("Can not traverse into"
                                " non-dictionary '%s' of type %s while"
                                " looking for subkey '%s'"
                                % (selected_params,
                                   tu.obj_name(selected_params),
                                   key))
            selected_params = selected_params[key]
        key = path.popleft()
        if not isinstance(selected_params, dict):
            raise TypeError("Can not extract key '%s' from non-dictionary"
                            " '%s' of type %s"
                            % (key, selected_params,
                               tu.obj_name(selected_params)))
        return str(selected_params[key])

    return BASIC_MATCHER.sub(replacer, content)


def detect_template(text):

    def cheetah_render(content, params):
        return CTemplate(content, searchList=[params]).respond()

    def jinja_render(content, params):
        return JTemplate(content,
                         undefined=jinja2.StrictUndefined,
                         trim_blocks=True).render(**params)

    if text.find("\n") != -1:
        ident, rest = text.split("\n", 1)
    else:
        ident = text
        rest = ''
    type_match = TYPE_MATCHER.match(ident)
    if not type_match:
        if CHEETAH_AVAILABLE:
            LOG.debug("Using Cheetah as the renderer for unknown template.")
            return ('cheetah', cheetah_render, text)
        else:
            return ('basic', basic_render, text)
    else:
        template_type = type_match.group(1).lower().strip()
        if template_type not in ('jinja', 'cheetah', 'basic'):
            raise ValueError("Unknown template rendering type '%s' requested"
                             % template_type)
        if template_type == 'jinja' and not JINJA_AVAILABLE:
            LOG.warn("Jinja not available as the selected renderer for"
                     " desired template, reverting to the basic renderer.")
            return ('basic', basic_render, rest)
        elif template_type == 'jinja' and JINJA_AVAILABLE:
            return ('jinja', jinja_render, rest)
        if template_type == 'cheetah' and not CHEETAH_AVAILABLE:
            LOG.warn("Cheetah not available as the selected renderer for"
                     " desired template, reverting to the basic renderer.")
            return ('basic', basic_render, rest)
        elif template_type == 'cheetah' and CHEETAH_AVAILABLE:
            return ('cheetah', cheetah_render, rest)
        # Only thing left over is the basic renderer (it is always available).
        return ('basic', basic_render, rest)


def render_from_file(fn, params):
    if not params:
        params = {}
    template_type, renderer, content = detect_template(util.load_file(fn))
    LOG.debug("Rendering content of '%s' using renderer %s", fn, template_type)
    return renderer(content, params)


def render_to_file(fn, outfn, params, mode=0644):
    contents = render_from_file(fn, params)
    util.write_file(outfn, contents, mode=mode)


def render_string(content, params):
    if not params:
        params = {}
    template_type, renderer, content = detect_template(content)
    return renderer(content, params)
