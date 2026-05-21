import base64
import logging

import requests

logger = logging.getLogger(__name__)

BASE = "https://api.github.com"


class GitHubClient:
    def __init__(self, pat: str, repo: str):
        self.repo = repo  # e.g. "nihidev/getsafe-dbt"
        self._headers = {
            "Authorization": f"Bearer {pat}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _get(self, path: str) -> dict:
        resp = requests.get(f"{BASE}{path}", headers=self._headers, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict) -> dict:
        resp = requests.post(f"{BASE}{path}", json=body, headers=self._headers, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _put(self, path: str, body: dict) -> dict:
        resp = requests.put(f"{BASE}{path}", json=body, headers=self._headers, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_main_sha(self) -> str:
        data = self._get(f"/repos/{self.repo}/git/ref/heads/main")
        return data["object"]["sha"]

    def create_branch(self, branch_name: str) -> str:
        sha = self.get_main_sha()
        try:
            self._post(f"/repos/{self.repo}/git/refs", {
                "ref": f"refs/heads/{branch_name}",
                "sha": sha,
            })
        except requests.HTTPError as e:
            if e.response.status_code != 422:  # 422 = branch already exists
                raise
        return branch_name

    def push_file(self, path: str, content: str, branch: str, commit_msg: str) -> dict:
        encoded = base64.b64encode(content.encode()).decode()
        body: dict = {"message": commit_msg, "content": encoded, "branch": branch}
        # Get existing file SHA if it exists (needed for updates)
        try:
            existing = self._get(f"/repos/{self.repo}/contents/{path}?ref={branch}")
            body["sha"] = existing["sha"]
        except requests.HTTPError:
            pass
        return self._put(f"/repos/{self.repo}/contents/{path}", body)

    def open_pr(self, title: str, body: str, branch: str, base: str = "main") -> dict:
        try:
            return self._post(f"/repos/{self.repo}/pulls", {
                "title": title,
                "body": body,
                "head": branch,
                "base": base,
            })
        except requests.HTTPError as e:
            if e.response.status_code == 422:
                # PR already exists for this branch — return the existing one
                owner = self.repo.split("/")[0]
                existing = self._get(
                    f"/repos/{self.repo}/pulls?head={owner}:{branch}&state=open"
                )
                if existing:
                    return existing[0]
            raise

    def get_pr(self, pr_number: int) -> dict:
        return self._get(f"/repos/{self.repo}/pulls/{pr_number}")
