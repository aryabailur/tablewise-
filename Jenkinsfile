// Tablewise CI: backend lint + tests, RAG ingest smoke test, frontend build, packaged artifact,
// and a build-status comment on any TAB-### Jira issue named in the latest commit message.

def notifyJira(String outcome) {
  try {
    withCredentials([string(credentialsId: 'jira-token', variable: 'JT')]) {
      withEnv(["BUILD_OUTCOME=${outcome}"]) {
        sh(label: 'Jira: comment on TAB issues', script: '''
          set +e
          keys=$(git log -1 --pretty=%B | grep -oE 'TAB-[0-9]+' | sort -u)
          if [ -z "$keys" ]; then echo "No TAB-### keys in the latest commit message"; exit 0; fi
          if [ "$BUILD_OUTCOME" = "passed" ]; then icon='\\u2705'; else icon='\\u274c'; fi
          for key in $keys; do
            printf '{"body":{"type":"doc","version":1,"content":[{"type":"paragraph","content":[{"type":"text","text":"Jenkins build #%s %s %s: %s"}]}]}}' \
              "$BUILD_NUMBER" "$icon" "$BUILD_OUTCOME" "$BUILD_URL" > jira-comment.json
            code=$(curl -s -o jira-response.txt -w '%{http_code}' -u "$JIRA_EMAIL:$JT" \
              -H 'Content-Type: application/json' -X POST --data @jira-comment.json \
              "$JIRA_BASE/rest/api/3/issue/$key/comment")
            echo "Jira comment on $key -> HTTP $code"
          done
          rm -f jira-comment.json jira-response.txt
          exit 0
        ''')
      }
    }
  } catch (err) {
    echo "Jira notification skipped: ${err}"
  }
}

pipeline {
  agent any

  options {
    timestamps()
    ansiColor('xterm')
    timeout(time: 15, unit: 'MINUTES')
    disableConcurrentBuilds()
  }

  environment {
    JIRA_BASE = 'https://aryabailur.atlassian.net'
    JIRA_EMAIL = 'aryabailur@gmail.com'
    HF_HUB_DISABLE_SYMLINKS_WARNING = '1'
  }

  stages {
    stage('Checkout') {
      steps {
        sh 'echo "Commit: $(git rev-parse HEAD)"; echo "Message: $(git log -1 --pretty=%s)"'
      }
    }

    stage('Backend: Install') {
      steps {
        sh '''
          export PIP_CACHE_DIR="$WORKSPACE/.cache/pip"
          python3 -m venv .venv-ci
          . .venv-ci/bin/activate
          pip install -q --upgrade pip
          pip install -q -r backend/requirements.txt ruff==0.17.0 pytest
        '''
      }
    }

    stage('Backend: Lint') {
      steps {
        sh '. .venv-ci/bin/activate && ruff check backend'
      }
    }

    stage('Backend: Tests') {
      steps {
        sh '''
          . .venv-ci/bin/activate
          mkdir -p reports
          cd backend && python -m pytest --junitxml=../reports/junit.xml -q
        '''
      }
    }

    stage('RAG: Ingest Smoke Test') {
      steps {
        sh '''
          . .venv-ci/bin/activate
          export CHROMA_DIR="$(mktemp -d)" FASTEMBED_CACHE_DIR="$WORKSPACE/.cache/fastembed"
          cd backend
          python -m app.seed
          python -c "from app import rag; n = rag.count(); print(f'chunks in collection: {n}'); assert n > 0"
          rm -rf "$CHROMA_DIR"
        '''
      }
    }

    stage('Frontend: Build') {
      steps {
        dir('frontend') {
          sh '''
            export npm_config_cache="$WORKSPACE/.cache/npm"
            npm ci --no-audit --no-fund
            npm run build
          '''
        }
      }
    }

    stage('Package') {
      steps {
        sh '''
          rm -f tablewise-build-*.tar.gz
          tar --exclude='backend/.venv' --exclude='backend/data' --exclude='__pycache__' --exclude='backend/.env' \
              -czf "tablewise-build-${BUILD_NUMBER}.tar.gz" backend frontend/dist
          ls -lh "tablewise-build-${BUILD_NUMBER}.tar.gz"
        '''
      }
    }
  }

  post {
    always {
      junit testResults: 'reports/junit.xml', allowEmptyResults: true
      archiveArtifacts artifacts: "tablewise-build-${env.BUILD_NUMBER}.tar.gz", allowEmptyArchive: true, fingerprint: true
    }
    success {
      notifyJira('passed')
    }
    failure {
      notifyJira('failed')
    }
  }
}
