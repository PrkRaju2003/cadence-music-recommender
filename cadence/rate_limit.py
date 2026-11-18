"""Shared PostgreSQL quotas. Trust forwarding headers only on Vercel."""
import hashlib
import os
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool


def scope_for(path):
    path = path.removeprefix('/demo')
    if path.startswith('/media/'):
        return 'media'
    if not path.startswith('/api/'):
        return None
    if path.startswith('/api/auth/'):
        return 'auth'
    if path.startswith('/api/recommendations/'):
        return 'recommendations'
    if path == '/api/sql/run':
        return 'sql'
    if path.startswith('/api/playback'):
        return 'playback'
    return 'api'


async def check_rate(request, gateway):
    scope = scope_for(request.url.path)
    if not scope:
        return None
    address = request.client.host if request.client else 'unknown'
    if os.environ.get('VERCEL') == '1':
        address = request.headers.get('x-vercel-forwarded-for', address).split(',')[0].strip()
    subject = hashlib.sha256(address.encode()).hexdigest()
    try:
        quota = await run_in_threadpool(gateway.rpc, 'rate_limit', payload={'p_subject':subject,'p_scope':scope})
    except HTTPException:
        raise HTTPException(503,'Rate limit service temporarily unavailable',headers={'Retry-After':'5'}) from None
    if not quota['allowed']:
        raise HTTPException(429,'Too many requests. Please try again shortly.',
                            headers={'Retry-After':str(quota['retry_after']),'X-RateLimit-Limit':str(quota['limit'])})
    return quota
