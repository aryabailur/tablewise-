#!/usr/bin/env bash
# Build and start the Tablewise Jenkins controller on http://localhost:8080 (admin / admin).
# Usage: JIRA_API_TOKEN='<token>' ./jenkins/run.sh
# GitHub owner + token come from the gh CLI. Tokens are passed as container env vars only, never written to disk.
set -euo pipefail
export MSYS_NO_PATHCONV=1  # stop Git Bash on Windows from rewriting /var/jenkins_home
cd "$(dirname "$0")"

: "${JIRA_API_TOKEN:?Set JIRA_API_TOKEN in the environment}"
GITHUB_OWNER="$(gh repo view --json owner -q .owner.login)"
GITHUB_TOKEN="$(gh auth token)"
export GITHUB_OWNER GITHUB_TOKEN JIRA_API_TOKEN

docker build -t tablewise-jenkins .
docker rm -f tablewise-jenkins >/dev/null 2>&1 || true
docker run -d --name tablewise-jenkins -p 8080:8080 \
  -e GITHUB_OWNER -e GITHUB_TOKEN -e JIRA_API_TOKEN \
  -v jenkins_home:/var/jenkins_home \
  tablewise-jenkins

echo "Jenkins starting on http://localhost:8080 (admin / admin)"
