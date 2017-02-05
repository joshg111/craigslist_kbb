# Copyright 2012-2015 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy of
# the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific
# language governing permissions and limitations under the License.

import hashlib
import logging
import threading
import os
import sys

import botocore
import botocore.exceptions
from awscli.vendored.s3transfer.manager import TransferManager
from awscli.vendored.s3transfer.subscribers import BaseSubscriber

from awscli.customizations.cloudformation import exceptions

LOG = logging.getLogger(__name__)


class S3Uploader(object):
    """
    Class to upload objects to S3 bucket that use versioning. If bucket
    does not already use versioning, this class will turn on versioning.
    """

    def __init__(self, s3_client,
                 bucket_name,
                 prefix=None,
                 kms_key_id=None,
                 force_upload=False,
                 transfer_manager=None):
        self.bucket_name = bucket_name
        self.prefix = prefix
        self.kms_key_id = kms_key_id or None
        self.force_upload = force_upload
        self.s3 = s3_client

        self.transfer_manager = transfer_manager
        if not transfer_manager:
            self.transfer_manager = TransferManager(self.s3)

    def upload(self, file_name, remote_path):
        """
        Uploads given file to S3
        :param file_name: Path to the file that will be uploaded
        :param remote_path:  be uploaded
        :return: VersionId of the latest upload
        """

        if self.prefix and len(self.prefix) > 0:
            remote_path = "{0}/{1}".format(self.prefix, remote_path)

        # Check if a file with same data exists
        if not self.force_upload and self.file_exists(remote_path):
            LOG.debug("File with same data is already exists at {0}. "
                      "Skipping upload".format(remote_path))
            return self.make_url(remote_path)

        try:

            # Default to regular server-side encryption unless customer has
            # specified their own KMS keys
            additional_args = {
                "ServerSideEncryption": "AES256"
            }

            if self.kms_key_id:
                additional_args["ServerSideEncryption"] = "aws:kms"
                additional_args["SSEKMSKeyId"] = self.kms_key_id

            print_progress_callback = \
                ProgressPercentage(file_name, remote_path)
            future = self.transfer_manager.upload(file_name,
                                                  self.bucket_name,
                                                  remote_path,
                                                  additional_args,
                                                  [print_progress_callback])
            future.result()

            return self.make_url(remote_path)

        except botocore.exceptions.ClientError as ex:
            error_code = ex.response["Error"]["Code"]
            if error_code == "NoSuchBucket":
                raise exceptions.NoSuchBucketError(
                        bucket_name=self.bucket_name)
            raise ex

    def upload_with_dedup(self, file_name, extension=None):
        """
        Makes and returns name of the S3 object based on the file's MD5 sum

        :param file_name: file to upload
        :param extension: String of file extension to append to the object
        :return: S3 URL of the uploaded object
        """

        # This construction of remote_path is critical to preventing duplicate
        # uploads of same object. Uploader will check if the file exists in S3
        # and re-upload only if necessary. So the template points to same file
        # in multiple places, this will upload only once

        filemd5 = self.file_checksum(file_name)
        remote_path = filemd5
        if extension:
            remote_path = remote_path + "." + extension

        return self.upload(file_name, remote_path)

    def file_exists(self, remote_path):
        """
        Check if the file we are trying to upload already exists in S3

        :param remote_path:
        :return: True, if file exists. False, otherwise
        """

        try:
            # Find the object that matches this ETag
            self.s3.head_object(
                Bucket=self.bucket_name, Key=remote_path)
            return True
        except botocore.exceptions.ClientError:
            # Either File does not exist or we are unable to get
            # this information.
            return False

    def make_url(self, obj_path):
        return "s3://{0}/{1}".format(
            self.bucket_name, obj_path)

    def file_checksum(self, file_name):

        with open(file_name, "rb") as file_handle:
            md5 = hashlib.md5()
            # Read file in chunks of 4096 bytes
            block_size = 4096

            # Save current cursor position and reset cursor to start of file
            curpos = file_handle.tell()
            file_handle.seek(0)

            buf = file_handle.read(block_size)
            while len(buf) > 0:
                md5.update(buf)
                buf = file_handle.read(block_size)

            # Restore file cursor's position
            file_handle.seek(curpos)

            return md5.hexdigest()


class ProgressPercentage(BaseSubscriber):
    # This class was copied directly from S3Transfer docs

    def __init__(self, filename, remote_path):
        self._filename = filename
        self._remote_path = remote_path
        self._size = float(os.path.getsize(filename))
        self._seen_so_far = 0
        self._lock = threading.Lock()

    def on_progress(self, future, bytes_transferred, **kwargs):

        # To simplify we'll assume this is hooked up
        # to a single filename.
        with self._lock:
            self._seen_so_far += bytes_transferred
            percentage = (self._seen_so_far / self._size) * 100
            sys.stdout.write(
                    "\rUploading to %s  %s / %s  (%.2f%%)" %
                    (self._remote_path, self._seen_so_far,
                     self._size, percentage))
            sys.stdout.flush()
