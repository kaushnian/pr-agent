import logging
import sys

import uvicorn
from fastapi import APIRouter, FastAPI, HTTPException, Request, Response

from pr_agent.agent.pr_agent import PRAgent
from pr_agent.config_loader import settings
from pr_agent.servers.utils import verify_signature

logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
router = APIRouter()


@router.post("/api/v1/github_webhooks")
async def handle_github_webhooks(request: Request, response: Response):
    logging.debug("Received a github webhook")
    try:
        body = await request.json()
    except Exception as e:
        logging.error("Error parsing request body", e)
        raise HTTPException(status_code=400, detail="Error parsing request body") from e
    body_bytes = await request.body()
    signature_header = request.headers.get('x-hub-signature-256', None)
    try:
        webhook_secret = settings.github.webhook_secret
    except AttributeError:
        webhook_secret = None
    if webhook_secret:
        verify_signature(body_bytes, webhook_secret, signature_header)
    logging.debug(f'Request body:\n{body}')
    return await handle_request(body)


async def handle_request(body):
    action = body.get("action", None)
    installation_id = body.get("installation", {}).get("id", None)
    agent = PRAgent(installation_id)
    if action == 'created':
        if "comment" not in body:
            return {}        
        if 'sender' in body and 'login' in body['sender'] and 'bot' in body['sender']['login']:
            return {}
        if "issue" not in body and "pull_request" not in body["issue"]:
            return {}
        
        pr_agent_name = '@propcheck-pr-agent'
        comment_body = body.get("comment", {}).get("body", None)
        
        if pr_agent_name not in comment_body:
            return {}
        
        api_url = body["issue"]["pull_request"].get("url", None)
        request_body = comment_body.replace(pr_agent_name, '')
        
        await agent.handle_request(api_url, request_body)

    elif action in ["opened"] or 'reopened' in action:
        pull_request = body.get("pull_request", None)
        if not pull_request:
            return {}
        api_url = pull_request.get("url", None)
        if api_url is None:
            return {}
        await agent.handle_request(api_url, "please review")
    else:
        return {}


@router.get("/")
async def root():
    return {"status": "ok"}


def start():
    if settings.get("GITHUB.DEPLOYMENT_TYPE", "user") != "app":
        raise Exception("Please set deployment type to app in .secrets.toml file")
    app = FastAPI()
    app.include_router(router)

    uvicorn.run(app, host="0.0.0.0", port=3000)


if __name__ == '__main__':
    start()
