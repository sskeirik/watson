from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

try:
    version = _dist_version("td-watson")
except PackageNotFoundError:  # running from a source tree that isn't installed
    version = "0+unknown"
