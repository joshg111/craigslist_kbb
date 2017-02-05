try:
    # Python 3.2+
    from ssl import CertificateError, match_hostname
except ImportError:
    # Backport of the function from a pypi module
    from backports.ssl_match_hostname import CertificateError, match_hostname

# Not needed, but documenting what we provide.
__all__ = ('CertificateError', 'match_hostname')
