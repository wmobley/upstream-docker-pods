"""Print a Tapis access token to stdout using tapipy password grant."""
import os
import sys

from tapipy.tapis import Tapis

base_url = os.environ["TAPIS_BASE_URL"]
username = os.environ["TAPIS_SERVICE_USERNAME"]
password = os.environ["TAPIS_SERVICE_PASSWORD"]

t = Tapis(base_url=base_url, username=username, password=password)
t.get_tokens()
token = t.access_token.access_token
if not token:
    sys.exit("Tapis token acquisition returned an empty token")
print(token)
