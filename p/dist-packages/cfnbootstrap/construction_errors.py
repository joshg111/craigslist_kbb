#==============================================================================
# Copyright 2011 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#==============================================================================

class BuildError(Exception):
    """
    Base exception for errors raised while building
    """

    pass

class NoSuchConfigSetError(BuildError):
    """
    Exception signifying no config error with specified name exists
    """
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return self.msg

class NoSuchConfigurationError(BuildError):
    """
    Exception signifying no config error with specified name exists
    """
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return self.msg

class CircularConfigSetDependencyError(BuildError):
    """
    Exception signifying circular dependency in configSets
    """
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return self.msg

class ToolError(BuildError):
    """
    Exception raised by Tools when they cannot successfully change reality

    Attributes:
    msg - a human-readable error message
    code - an error code, if applicable
    """

    def __init__(self, msg, code=None):
        self.msg = msg
        self.code = code

    def __str__(self):
        if (self.code):
            return '%s (return code %s)' % (self.msg, self.code)
        else:
            return self.msg
