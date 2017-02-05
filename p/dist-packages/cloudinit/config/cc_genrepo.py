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

import cc_yum_configure

from cloudinit.settings import PER_INSTANCE

frequency = PER_INSTANCE
distros = [ 'amazon' ]


def handle(name, cfg, cloud, log, _args):
    cc_yum_configure.handle(name, cfg, cloud, log, _args)
