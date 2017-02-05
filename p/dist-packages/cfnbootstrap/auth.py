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
import endpoint_tool
import urllib
import operator
from cfnbootstrap.resources import documents
from cfnbootstrap.packages.requests.auth import AuthBase, HTTPBasicAuth
import base64
import datetime
import hashlib
import hmac
import logging
import re
import urlparse
import util

_AMZ_CONTENT_SHA_HEADER = 'x-amz-content-sha256'
_AMZ_DATE_HEADER = 'x-amz-date'
_AUTHORIZATION_HEADER = 'Authorization'
_SECURITY_TOKEN_HEADER = 'x-amz-security-token'

log = logging.getLogger("cfn.init")

def _extract_bucket_from_url(unparsed_url):
    endpoint = _get_endpoint_for_url(unparsed_url)
    if endpoint is None:
        # Not an S3 URL, skip
        return None

    bucket = endpoint.get_subdomain_prefix(unparsed_url)
    if not bucket:
        # This means that we're using path-style buckets
        # lop off the first / and return everything up to the next /
        return urlparse.urlparse(unparsed_url).path[1:].partition('/')[0]
    else:
        # Subdomain-style S3 URL
        # Remove the trailing dot if it exists
        return bucket.rstrip('.')

def _get_endpoint_for_url(unparsed_url):
    for endpoint in endpoint_tool.get_endpoints_for_service("AmazonS3"):
        if endpoint.matches_url(unparsed_url):
            return endpoint
    return None

class S3Signer(object):

    def __init__(self, creds, region=None):
        self._creds = creds
        self._region = region
        self._nowfunction = datetime.datetime.utcnow

    # Inspired by digest auth handling: https://github.com/kennethreitz/requests/blob/v2.6.0/requests/auth.py#L172
    def handle_redirect(self, r, **kwargs):
        if r.is_redirect and 'Location' in r.headers:
            if _extract_bucket_from_url(r.headers['Location']) is not None:
                log.warn("Handling redirect to S3 location: %s", r.headers['Location'])

                # Consume content and release the original connection
                # to allow our new request to reuse the same one.
                r.content
                r.raw.release_conn()
                prep = r.request.copy()

                # Remove V2 S3 auth headers
                prep.headers.pop(_SECURITY_TOKEN_HEADER, '')
                prep.headers.pop(_AUTHORIZATION_HEADER, '')
                prep.headers.pop(_AMZ_DATE_HEADER, '')
                prep.headers.pop(_AMZ_CONTENT_SHA_HEADER, '')

                # Accept the S3 redirect
                prep.url = r.headers['Location']

                prep = self.sign(prep)

                _r = r.connection.send(prep, **kwargs)
                _r.history.append(r)
                _r.request = prep
                return _r
            else:
                log.error('S3 redirected to non-S3 url: %s', r.headers['Location'])

        return r

    def sign(self, req):
        # S3 will redirect requests to the appropriate endpoint for a bucket.  This response handler will handle that redirect
        req.register_hook('response', self.handle_redirect)

        # Requests only quotes illegal characters in a URL, leaving reserved chars.
        # We want to fully quote the URL, so we first unquote the url before requoting it in our signature calculation
        full_url = urllib.unquote(req.full_url if hasattr(req, 'full_url') else req.url)

        region = self._region
        if not region:
            endpoint = _get_endpoint_for_url(full_url)
            if endpoint.is_default:
                log.warn('Falling back to Signature Version 2 as no region was specified in S3 URL')
                return S3V2Signer(self._creds).sign(req)
            region = endpoint.region

        parsed = urlparse.urlparse(full_url)

        timestamp = self._nowfunction()
        timestamp_formatted = timestamp.strftime('%Y%m%dT%H%M%SZ')
        timestamp_short = timestamp.strftime('%Y%m%d')

        scope =  timestamp_short + '/' + region + '/s3/aws4_request'

        req.headers[_AMZ_DATE_HEADER] = timestamp_formatted
        if self._creds.security_token:
            req.headers[_SECURITY_TOKEN_HEADER] = self._creds.security_token
        req.headers['host'] = parsed.netloc

        hashed_payload = hashlib.sha256(req.body if req.body is not None else '').hexdigest()
        req.headers[_AMZ_CONTENT_SHA_HEADER] = hashed_payload

        canonical_request = req.method + '\n'
        canonical_request += self._canonicalize_uri(full_url) + '\n'
        canonical_request += self._canonicalize_query(urlparse.parse_qs(parsed.query, True)) + '\n'

        headers_to_sign = req.headers.copy()
        (canonical_headers, signed_headers) = self._canonicalize_headers(headers_to_sign)
        canonical_request += canonical_headers + '\n' + signed_headers + '\n'
        canonical_request += hashed_payload

        string_to_sign = 'AWS4-HMAC-SHA256\n' + timestamp_formatted + '\n' + scope + '\n' + hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()

        derived_key = hmac.new(("AWS4" + self._creds.secret_key).encode('utf-8'), timestamp_short.encode('utf-8'), hashlib.sha256).digest()
        derived_key = hmac.new(derived_key, region.encode('utf-8'), hashlib.sha256).digest()
        derived_key = hmac.new(derived_key, 's3'.encode('utf-8'), hashlib.sha256).digest()
        derived_key = hmac.new(derived_key, "aws4_request".encode('utf-8'), hashlib.sha256).digest()

        signature = hmac.new(derived_key, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()

        credential = self._creds.access_key + '/' + scope
        req.headers[_AUTHORIZATION_HEADER] = 'AWS4-HMAC-SHA256 Credential=%s,SignedHeaders=%s,Signature=%s' % (credential, signed_headers, signature)

        return req

    def _canonicalize_uri(self, uri):
        split = urlparse.urlsplit(uri)
        if not split.path:
            return '/'
        path = urlparse.urlsplit(urlparse.urljoin('http://foo.com', split.path.lstrip('/'))).path
        return urllib.quote(path, '/~') if path else '/'

    def _canonicalize_query(self, params):
        if not params:
            return ''
        encoded_pairs = []
        for entry in params.iteritems():
            for value in entry[1]:
                encoded_pairs.append((urllib.quote(entry[0], '~'), urllib.quote(value, '~') if value else ''))

        sorted_pairs = sorted(encoded_pairs, key=operator.itemgetter(0, 1))

        return '&'.join(('='.join(pair) for pair in sorted_pairs))

    def _canonicalize_headers(self, headers):
        canon_headers = {}
        for key, value in ((key.lower(), re.sub(r'(?su)[\s]+', ' ', value).strip()) for key, value in headers.iteritems()):
            if key in canon_headers:
                canon_headers[key] = canon_headers[key] + ',' + value
            else:
                canon_headers[key] = value

        sorted_entries = sorted(canon_headers.iteritems(), key=operator.itemgetter(0))

        return '\n'.join((':'.join(entry) for entry in sorted_entries)) + '\n', ';'.join((entry[0] for entry in sorted_entries))


class S3V2Signer(object):

    def __init__(self, creds):
        self._creds = creds

    def sign(self, req):
        if 'Date' not in req.headers:
            req.headers[_AMZ_DATE_HEADER] = datetime.datetime.utcnow().replace(microsecond=0).strftime("%a, %d %b %Y %H:%M:%S GMT")

        if self._creds.security_token:
            req.headers[_SECURITY_TOKEN_HEADER] = self._creds.security_token

        stringToSign = req.method + '\n'
        stringToSign += req.headers.get('content-md5', '') + '\n'
        stringToSign += req.headers.get('content-type', '') + '\n'
        stringToSign += req.headers.get('date', '') + '\n'
        stringToSign += self._canonicalize_headers(req)
        stringToSign += self._canonicalize_resource(req)

        signed = base64.encodestring(hmac.new(self._creds.secret_key.encode('utf-8'), stringToSign.encode('utf-8'), hashlib.sha1).digest()).strip()

        req.headers[_AUTHORIZATION_HEADER] = 'AWS %s:%s' % (self._creds.access_key, signed)

        return req

    def _canonicalize_headers(self, req):
        headers = [(hdr.lower(), val) for hdr, val in req.headers.iteritems() if hdr.lower().startswith('x-amz')]
        return '\n'.join([hdr + ':' + val for hdr, val in sorted(headers)]) + '\n' if headers else ''

    def _canonicalize_resource(self, req):
        unparsed_url = req.full_url if hasattr(req, 'full_url') else req.url
        endpoint = _get_endpoint_for_url(unparsed_url)
        bucket = endpoint.get_subdomain_prefix(unparsed_url)
        url = urlparse.urlparse(unparsed_url)
        if not bucket:
            # Path-style
            return url.path
        else:
            # Subdomain-style
            return '/' + bucket.rstrip('.') + url.path

class S3DefaultAuth(AuthBase):

    def __init__(self):
        self._bucketToAuth = {}

    def add_auth_for_bucket(self, bucket, auth_impl):
        self._bucketToAuth[bucket] = auth_impl

    def __call__(self, req):
        bucket = self._extract_bucket(req)
        if bucket and bucket in self._bucketToAuth:
            return self._bucketToAuth[bucket](req)
        return req

    def _extract_bucket(self, req):
        return _extract_bucket_from_url(req.full_url if hasattr(req, 'full_url') else req.url)


class S3RoleAuth(AuthBase):

    def __init__(self, roleName):
        self._roleName=roleName

    def __call__(self, req):
        return S3Signer(util.get_role_creds(self._roleName)).sign(req)

class S3Auth(AuthBase):

    def __init__(self, access_key, secret_key):
        self._signer = S3Signer(util.Credentials(access_key, secret_key))

    def __call__(self, req):
        return self._signer.sign(req)

class BasicDefaultAuth(AuthBase):

    def __init__(self):
        self._auths = {}

    def __call__(self, req):
        base_uri = urlparse.urlparse(req.full_url if hasattr(req, 'full_url') else req.url).netloc
        if base_uri in self._auths:
            return self._auths[base_uri](req)
        return req

    def add_password(self, uri, username, password):
        self._auths[uri] = HTTPBasicAuth(username, password)

class DefaultAuth(AuthBase):

    def __init__(self, s3, basic):
        self._s3 = s3
        self._basic = basic

    def __call__(self, req):
        return self._s3(self._basic(req))

class AuthenticationConfig(object):

    def __init__(self, model):

        self._auths = {}

        s3Auth = S3DefaultAuth()
        basicAuth = BasicDefaultAuth()

        for key, config in model.iteritems():
            configType = config.get('type', '')
            if 's3' == configType.lower():
                auth_impl = None
                if 'accessKeyId' in config and 'secretKey' in config:
                    auth_impl = S3Auth(config['accessKeyId'], config['secretKey'])
                elif 'roleName' in config:
                    auth_impl = S3RoleAuth(config['roleName'])
                else:
                    log.warn('S3 auth requires either "accessKeyId" and "secretKey" or "roleName"')
                    continue

                self._auths[key] = auth_impl

                if 'buckets' in config:
                    buckets = [config['buckets']] if isinstance(config['buckets'], basestring) else config['buckets']
                    for bucket in buckets:
                        s3Auth.add_auth_for_bucket(bucket, auth_impl)

            elif 'basic' == configType.lower():
                self._auths[key] = HTTPBasicAuth(config.get('username'), config.get('password'))
                if 'uris' in config:
                    if isinstance(config['uris'], basestring):
                        basicAuth.add_password(config['uris'], config.get('username'), config.get('password'))
                    else:
                        for u in config['uris']:
                            basicAuth.add_password(u, config.get('username'), config.get('password'))
            else:
                log.warn("Unrecognized authentication type: %s", configType)

        self._defaultAuth = DefaultAuth(s3Auth, basicAuth)

    def get_auth(self, key):
        if not key or not key in self._auths:
            return self._defaultAuth

        return self._auths[key]
