"""Public Gateway lease protocol against separate PostgreSQL connections."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier
from uuid import uuid4

from test_publish_api import DESKTOP, INTERNAL, claim, video


def desktop(api, capacity=3):
    session = str(uuid4())
    report = dict(sessionId=session, mode='worker', release='0.1.0', cliRelease='0.1.0',
                  contractVersion=1, preparedStarts=True, capacity=capacity, freeSlots=capacity,
                  capabilities=[{'platform': 'tiktok', 'action': 'upload-video'},
                                {'platform': 'instagram', 'action': 'check'}],
                  providers=[{'provider': 'bitbrowser', 'available': True,
                              'profiles': [{'profileId': 'shared', 'name': 'Visible'}]}])
    api.post('/session', headers=DESKTOP, json=report).raise_for_status()
    return session


def enqueue_video(api, merchant, *, earliest=None):
    task = dict(video(merchant), earliestPublishAt=earliest, organizationId=merchant,
                bindingId=merchant + '-binding', provider='bitbrowser', profileId='shared')
    api.post('/internal/occurrences', headers=INTERNAL, json=task).raise_for_status()
    return task


def enqueue_check(api, workflow):
    task = dict(workflowId=workflow, contractVersion=1, release='0.1.0', platform='instagram',
                requiredCapability='instagram.check', action='check', provider='bitbrowser', profileId='shared')
    api.post('/internal/occurrences', headers=INTERNAL, json=task).raise_for_status()


def test_racing_merchants_and_platforms_share_only_with_grant_holder(gateway):
    a, b = desktop(gateway), desktop(gateway)
    enqueue_video(gateway, 'merchant-1')
    enqueue_video(gateway, 'merchant-2')
    enqueue_check(gateway, 'other-platform')
    gate = Barrier(2)

    def poll(session):
        gate.wait()
        return claim(gateway, session)

    with ThreadPoolExecutor(2) as pool:
        records = list(pool.map(poll, [a, b]))
    assert sum(bool(r) for r in records) == 1
    first = next(r for r in records if r)
    owner = first['sessionId']
    other = b if owner == a else a
    assert claim(gateway, other) is None
    second = claim(gateway, owner)
    assert second['task']['platform'] != first['task']['platform']
    assert first['leaseGrantId'] == second['leaseGrantId']
    assert first['renewAfterSeconds'] == 300
    for member in (first, second):
        expiry = datetime.fromisoformat(member['leaseExpiresAt'].replace('Z', '+00:00'))
        claimed = datetime.fromisoformat(member['claimedAt'].replace('Z', '+00:00'))
        assert 899 < (expiry - claimed).total_seconds() < 901
    assert first['leaseExpiresAt'] < second['leaseExpiresAt']
    assert claim(gateway, owner) is None


def event(api, record, action, **fields):
    body = {k: record[k] for k in ('workflowId', 'leaseGrantId', 'sessionId')}
    return api.post('/publish-task/profile-lease/' + action, headers=DESKTOP, json={**body, **fields})


def test_finishing_commands_releases_only_their_own_platform_and_slot(gateway):
    a, b = desktop(gateway, capacity=2), desktop(gateway)
    enqueue_video(gateway, 'merchant-1')
    enqueue_video(gateway, 'merchant-2')
    enqueue_check(gateway, 'concurrent-check')
    enqueue_check(gateway, 'following-check')
    first, second = claim(gateway, a), claim(gateway, a)
    assert claim(gateway, a) is None
    assert event(gateway, second, 'complete').json() == {'idle': False}
    assert event(gateway, second, 'renew').status_code == 409
    assert event(gateway, second, 'release', windowClosed=True).status_code == 409
    third = claim(gateway, a)
    assert third['workflowId'] == 'following-check'
    assert claim(gateway, b) is None
    assert event(gateway, first, 'complete').json() == {'idle': False}
    assert event(gateway, third, 'complete').json() == {'idle': True}
    assert event(gateway, third, 'release', windowClosed=False).status_code == 422
    assert claim(gateway, b) is None
    assert event(gateway, third, 'release', windowClosed=True).is_success
    following = claim(gateway, b)
    assert following['workflowId'] == 'merchant-2'
    assert following['leaseGrantId'] != first['leaseGrantId']


def test_public_and_legacy_lease_routes_require_the_desktop_bearer(gateway):
    # Direct internal callers can finish a grant made before the desktop URL change.
    a = desktop(gateway)
    enqueue_video(gateway, "kept-grant")
    record = claim(gateway, a)
    body = {key: record[key] for key in ("workflowId", "leaseGrantId", "sessionId")}
    for action in ("renew", "complete", "release"):
        payload = {**body, "windowClosed": True} if action == "release" else body
        for base in ("/publish-task/profile-lease/", "/profile-lease/"):
            assert gateway.post(base + action, headers=INTERNAL, json=payload).status_code == 401
        assert gateway.post("/profile-lease/" + action, headers=DESKTOP, json=payload).is_success
