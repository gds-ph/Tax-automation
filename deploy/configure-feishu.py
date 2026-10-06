"""Run on the Linux host; prompts privately and checks the app's organization."""
import getpass
import json
import os
from pathlib import Path
import subprocess
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

class SetupError(Exception):
    """Only fixed text and numeric status codes may reach the terminal."""

def error_code(result):
    value = result.get('code') if isinstance(result, dict) else None
    return str(value) if type(value) is int else 'unavailable'

def api(path, payload=None, token=None):
    stage = 'App authentication' if path == 'auth/v3/tenant_access_token/internal' else 'Organization lookup'
    headers={'Content-Type':'application/json'}
    if token: headers['Authorization']='Bearer '+token
    request=Request('https://open.feishu.cn/open-apis/'+path,
                    data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
    try:
        with build_opener(ProxyHandler({}),NoRedirect()).open(request,timeout=20) as response:
            result=json.loads(response.read(100000))
    except HTTPError as exc:
        try:
            code=error_code(json.loads(exc.read(100000)))
        except (ValueError, OSError):
            code='unavailable'
        raise SetupError(f'{stage} failed: HTTP {exc.code}; Feishu code {code}.') from None
    except (URLError, TimeoutError, OSError):
        raise SetupError(f'{stage} failed: connection, TLS verification, or timeout error.') from None
    except ValueError:
        raise SetupError(f'{stage} failed: invalid JSON response.') from None
    if not isinstance(result,dict):
        raise SetupError(f'{stage} failed: unexpected response format.')
    if result.get('code',0)!=0:
        raise SetupError(f'{stage} failed: Feishu code {error_code(result)}.')
    return result

def main():
    root=Path(__file__).resolve().parent.parent
    target=root/'.env.server'
    app_id='cli_aa85547d18799cb6'
    secret=getpass.getpass('Feishu App Secret (hidden): ').strip()
    if not secret: raise ValueError('App Secret required.')
    access=api('auth/v3/tenant_access_token/internal',{'app_id':app_id,'app_secret':secret}).get('tenant_access_token')
    if not isinstance(access,str) or not access:
        raise SetupError('App authentication returned no tenant access token.')
    print('App authentication succeeded.')
    result=api('tenant/v2/tenant/query',token=access)
    data=result.get('data')
    tenant=data.get('tenant') if isinstance(data,dict) else None
    if not isinstance(tenant,dict):
        raise SetupError('Organization lookup returned no organization details.')
    tenant_key=tenant.get('tenant_key')
    if not isinstance(tenant_key,str) or not tenant_key:
        raise SetupError('Organization lookup returned no organization ID.')
    print('Organization returned by Feishu:',tenant.get('name','(no name)'))
    if input('Allow employees of this organization to sign in? Type YES: ').strip()!='YES':
        print('Nothing changed.');return
    values={'FEISHU_APP_ID':app_id,'FEISHU_APP_SECRET':secret,'FEISHU_TENANT_KEY':tenant_key,
            'FEISHU_REDIRECT_URI':'https://192.168.8.200:8443/auth/feishu/callback/'}
    lines=[line for line in target.read_text().splitlines() if line.split('=',1)[0] not in values]
    for key,value in values.items():
        if '\n' in value or '\r' in value: raise ValueError('Invalid value.')
        lines.append(key+"='"+value.replace('\\','\\\\').replace("'","\\'")+"'")
    temp=target.with_name('.env.server.feishu.tmp')
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream: stream.write('\n'.join(lines)+'\n')
    os.replace(temp,target)
    subprocess.run(['docker','compose','--env-file','.env.server','-f','compose.server.yaml','up','-d','--no-deps','web'],cwd=root,check=True)
    print('Feishu configured. Test Sign in with Feishu on the login page.')

if __name__=='__main__':
    try: main()
    except SetupError as exc:
        raise SystemExit(str(exc)+' No credentials were printed; configuration was not changed.')
    except PermissionError:
        raise SystemExit('Cannot access the deployment configuration file. Run as the deployment owner (nodeadmin).')
    except FileExistsError:
        raise SystemExit('A temporary configuration file already exists. Ask the administrator to inspect it before retrying.')
    except subprocess.CalledProcessError:
        raise SystemExit('Configuration saved, but Docker could not restart web. Check Docker service status.')
    except Exception:
        raise SystemExit('Setup did not complete. Check app credentials and permission to retrieve organization information. No credentials were printed.')
