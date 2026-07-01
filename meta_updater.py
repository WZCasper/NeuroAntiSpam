"""
NeuroAntiSpam - Meta file updater
Writes data/meta.json to GitHub — contains a fine-grained GitHub PAT
with ONLY contents:write scope on ONLY this repository.
This is safe to expose publicly because the token can only overwrite
data/ files in this one repo, nothing else.
"""

import asyncio
import base64
import json
import os
import aiohttp

GITHUB_API = "https://api.github.com"


async def update_meta(write_token: str, repo: str, bot_username: str):
    """
    Writes data/meta.json containing the write token so the static
    dashboard can save settings back to the repo.
    """
    meta = {
        "write_token": write_token,
        "bot_username": bot_username,
        "repo": repo,
    }

    headers = {
        "Authorization": f"token {write_token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    content_b64 = base64.b64encode(
        json.dumps(meta, indent=2).encode()
    ).decode()

    async with aiohttp.ClientSession() as session:
        # Get SHA of existing file
        sha = None
        async with session.get(
            f"{GITHUB_API}/repos/{repo}/contents/data/meta.json",
            headers=headers
        ) as r:
            if r.status == 200:
                sha = (await r.json()).get("sha")

        payload = {
            "message": "🤖 Update meta [skip ci]",
            "content": content_b64,
            "branch": "main",
        }
        if sha:
            payload["sha"] = sha

        async with session.put(
            f"{GITHUB_API}/repos/{repo}/contents/data/meta.json",
            headers=headers,
            json=payload,
        ) as r:
            if r.status in (200, 201):
                print("✅ data/meta.json updated")
            else:
                print(f"❌ Failed: {r.status} {await r.text()}")


if __name__ == "__main__":
    token = os.environ["GH_TOKEN"]
    repo  = os.environ.get("GH_REPO", "WZCasper/NeuroAntiSpam")
    bot   = os.environ.get("BOT_USERNAME", "NeuroAntiSpamBot")
    asyncio.run(update_meta(token, repo, bot))
