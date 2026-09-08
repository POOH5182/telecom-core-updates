"""Read-only deployed service checks. Never starts a user sign-in or creates users."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'cloud'))
from client import cloud_http, CloudError

settings=cloud_http('/auth/v1/settings')
assert settings.get('external',{}).get('google') is True, 'Enable Google sign-in and save it in Supabase.'
try:
    cloud_http('/rest/v1/rpc/telecom_call',{'request':{'action':'list'}})
except CloudError as error:
    assert error.code in ('42501','401','PGRST301'), str(error)
else:
    raise AssertionError('Anonymous drawing access was permitted.')
print('PASS Google sign-in is enabled and anonymous drawing access is denied')
