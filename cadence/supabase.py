"""Supabase Auth + user-scoped SQL RPCs using a publishable key only.

The server forwards each user's verified JWT. There is no service-role bypass,
database password, or token stored in browser JavaScript/localStorage.
"""
import os
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv
from fastapi import HTTPException

from .db import ROOT


@dataclass(frozen=True)
class SupabaseSettings:
    url: str
    key: str
    secure_cookies: bool = False


def settings_from_env():
    load_dotenv(ROOT / '.env', override=False)
    url = os.environ.get('SUPABASE_URL', '').rstrip('/')
    key = os.environ.get('SUPABASE_PUBLISHABLE_KEY', '')
    if not url and not key:
        return None
    if not url.startswith('https://') or not key:
        raise RuntimeError('Set both SUPABASE_URL (HTTPS) and SUPABASE_PUBLISHABLE_KEY, or unset both for local demo mode.')
    if key.startswith('sb_secret_'):
        raise RuntimeError('Use a publishable key, never a secret/service-role key.')
    # Legacy JWT keys are deliberately excluded to prevent confusing anon and
    # service-role credentials. New Supabase projects provide publishable keys.
    if not key.startswith('sb_publishable_'):
        raise RuntimeError('A modern sb_publishable_ key is required.')
    return SupabaseSettings(url, key, os.environ.get('COOKIE_SECURE') == '1')


class SupabaseGateway:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.client = httpx.Client(base_url=settings.url, timeout=25, transport=transport,
                                   headers={'apikey': settings.key})

    def close(self):
        self.client.close()

    def request(self, method, path, token=None, payload=None):
        headers = {'Authorization': 'Bearer ' + token} if token else {}
        try:
            response = self.client.request(method, path, headers=headers, json=payload)
        except httpx.RequestError:
            raise HTTPException(503, 'The account service is temporarily unavailable') from None
        if response.is_error:
            error = response.json() if 'json' in response.headers.get('content-type', '') else {}
            code = error.get('code', '')
            status = { '42501':403, '23505':409, '23503':422, '23514':422, '22023':422 }.get(code)
            if not status:
                status = 401 if response.status_code == 401 else 429 if response.status_code == 429 else 400 if path.startswith('/auth/') else 502
            # Supabase Auth errors describe confirmation/invalid credentials.
            # Database errors are generalized so SQL internals aren't exposed.
            message = (error.get('msg') or error.get('message') or 'Account request failed') if path.startswith('/auth/') else {
                403:'Access denied',409:'Event key already used',422:'Invalid request data',401:'Please sign in again'
            }.get(status,'Database request failed')
            raise HTTPException(status, message)
        return response.json() if response.content else {}

    def rpc(self, name, token=None, payload=None):
        return self.request('POST', '/rest/v1/rpc/cadence_' + name, token, payload or {})

    def user(self, token):
        return self.request('GET', '/auth/v1/user', token)
