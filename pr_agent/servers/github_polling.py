import asyncio
import logging
import sys
from datetime import datetime, timezone

import aiohttp

from pr_agent.agent.pr_agent import PRAgent
from pr_agent.config_loader import settings
from pr_agent.git_providers import get_git_provider

logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
NOTIFICATION_URL = "https://api.github.com/notifications"


def now() -> str:
    now_utc = datetime.now(timezone.utc).isoformat()
    now_utc = now_utc.replace("+00:00", "Z")
    return now_utc


async def polling_loop():
    handled_ids = set()
    since = [now()]
    last_modified = [None]
    git_provider = get_git_provider()()
    user_id = git_provider.get_user_id()
    try:
        deployment_type = settings.github.deployment_type
        token = settings.github.user_token
    except AttributeError:
        deployment_type = 'none'
        token = None
    if deployment_type != 'user':
        raise ValueError("Deployment mode must be set to 'user' to get notifications")
    if not token:
        raise ValueError("User token must be set to get notifications")
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                headers = {
                    "Accept": "application/vnd.github.v3+json",
                    "Authorization": f"Bearer {token}"
                }
                params = {
                    "participating": "true"
                }
                if since[0]:
                    params["since"] = since[0]
                if last_modified[0]:
                    headers["If-Modified-Since"] = last_modified[0]
                async with session.get(NOTIFICATION_URL, headers=headers, params=params) as response:
                    if response.status == 200:
                        if 'Last-Modified' in response.headers:
                            last_modified[0] = response.headers['Last-Modified']
                            since[0] = None
                        notifications = await response.json()
                        if not notifications:
                            continue
                        for notification in notifications:
                            handled_ids.add(notification['id'])
                            if 'reason' in notification and notification['reason'] == 'mention':
                                if 'subject' in notification and notification['subject']['type'] == 'PullRequest':
                                    pr_url = notification['subject']['url']
                                    latest_comment = notification['subject']['latest_comment_url']
                                    async with session.get(latest_comment, headers=headers) as comment_response:
                                        if comment_response.status == 200:
                                            comment = await comment_response.json()
                                            if 'id' in comment:
                                                if comment['id'] in handled_ids:
                                                    continue
                                                else:
                                                    handled_ids.add(comment['id'])
                                            if 'user' in comment and 'login' in comment['user']:
                                                if comment['user']['login'] == user_id:
                                                    continue
                                            comment_body = comment['body'] if 'body' in comment else ''
                                            commenter_github_user = comment['user']['login'] if 'user' in comment else ''
                                            logging.info(f"Commenter: {commenter_github_user}\nComment: {comment_body}")
                                            user_tag = "@" + user_id
                                            if user_tag not in comment_body:
                                                continue
                                            rest_of_comment = comment_body.split(user_tag)[1].strip()
                                            agent = PRAgent()
                                            await agent.handle_request(pr_url, rest_of_comment)
                    elif response.status != 304:
                        print(f"Failed to fetch notifications. Status code: {response.status}")

                await asyncio.sleep(5)
            except Exception as e:
                logging.error(f"Exception during processing of a notification: {e}")
                await asyncio.sleep(5)

if __name__ == '__main__':
    asyncio.run(polling_loop())
