pipeline {
    agent { label 'java-jdk21' }
    options {
        timestamps()
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '10'))
        timeout(time: 30, unit: 'MINUTES')
    }
    parameters {
        choice(name: 'BROWSER', choices: ['chrome'], description: 'Browser')
        choice(name: 'BROWSER_MODE', choices: ['local', 'selenoid'], description: 'Local agent Chrome or QA.GURU Selenoid: https://selenoid.qa.guru/#/statistics')
        string(name: 'BROWSER_SIZE', defaultValue: '1920x1080', description: 'Browser window size, WIDTHxHEIGHT')
        booleanParam(name: 'NOTIFY_TELEGRAM', defaultValue: false, description: 'Send Telegram notification with project credentials')
    }
    environment {
        BROWSER = "${params.BROWSER ?: 'chrome'}"
        BROWSER_SIZE = "${params.BROWSER_SIZE ?: '1920x1080'}"
        BASE_URL = 'https://github.com'
        HEADLESS = 'true'
        ALLURE_VERSION = '2.46.1'
        ALLURE_SHA256 = '37428164f310c8d137cfdd2c3a25d049b233261ddab13e1bd4dfd7627b5cbf8d'
        ALLURE_NOTIFICATIONS_JAR_VERSION = '4.11.1'
    }
    stages {
        stage('Validate parameters') {
            steps {
                sh '''#!/bin/sh
set -eu
if [ "${BROWSER}" != "chrome" ]; then
  echo "Unsupported browser: only Chrome is supported"
  exit 1
fi
case "$BROWSER_MODE" in
  local|selenoid) ;;
  *) echo "Unsupported BROWSER_MODE"; exit 1 ;;
esac
if ! printf '%s' "${BROWSER_SIZE}" | grep -Eq '^[0-9]{3,4}x[0-9]{3,4}$'; then
  echo "BROWSER_SIZE must match WIDTHxHEIGHT, e.g. 1920x1080"
  exit 1
fi
'''
            }
        }
        stage('Show tool versions') {
            steps {
                sh '''#!/bin/sh
set -eu
echo "JAVA_HOME=${JAVA_HOME:-<unset>}"
java -version
./gradlew --version
if [ "$BROWSER_MODE" = local ]; then
  (google-chrome --version || chromium --version || chromium-browser --version || true)
  (chromedriver --version || true)
else
  echo 'Remote Chrome: https://selenoid.qa.guru/#/statistics'
fi
'''
            }
        }
        stage('Compile tests') {
            steps {
                sh './gradlew --no-daemon clean testClasses --console=plain'
                script { env.COMPILE_OUTCOME = 'success' }
            }
        }
        stage('Run UI tests') {
            when { expression { return env.COMPILE_OUTCOME == 'success' } }
            steps {
                script {
                    def remote = params.BROWSER_MODE == 'selenoid'
                    def bindings = remote ? [usernamePassword(credentialsId: 'getting-started-java-ai-selenoid',
                        usernameVariable: 'SELENOID_USERNAME', passwordVariable: 'SELENOID_PASSWORD')] : []
                    withCredentials(bindings) {
                        env.TESTS_STARTED = 'true'
                        sh '''#!/bin/sh
set -eu
driver="$BROWSER"
if [ "$BROWSER_MODE" = selenoid ]; then
  driver=tests.SelenoidChromeDriverFactory
fi
./gradlew --no-daemon test --console=plain \
  -DbaseUrl="${BASE_URL}" \
  "-Dbrowser=${driver}" \
  "-DbrowserSize=${BROWSER_SIZE}" \
  -Dheadless="${HEADLESS}"
'''
                    }
                    env.TESTS_OUTCOME = 'success'
                }
            }
        }
    }
    post {
        always {
            script {
                env.REPORT_OUTCOME = 'skipped'
                if (env.TESTS_STARTED == 'true') {
                    catchError(buildResult: 'FAILURE', catchInterruptions: false) {
                        archiveArtifacts artifacts: 'build/allure-results/**,build/test-results/test/**,build/reports/tests/test/**', allowEmptyArchive: false
                    }
                    catchError(buildResult: 'FAILURE', catchInterruptions: false) {
                        def tests = junit testResults: 'build/test-results/test/*.xml', skipMarkingBuildUnstable: true
                        if (tests.failCount > 0) {
                            error("JUnit reported ${tests.failCount} failed tests")
                        }
                    }

                    def reportStatus = sh(script: '''#!/bin/sh
set -eu
if ! find build/allure-results -maxdepth 1 -name '*-result.json' | grep -q .; then
  echo 'No Allure test results in build/allure-results; the report is not generated'
  exit 1
fi
ARCHIVE="build/allure-cli/allure-commandline-${ALLURE_VERSION}.tgz"
mkdir -p build/allure-cli
downloaded=false
for url in \
  "https://repo.maven.apache.org/maven2/io/qameta/allure/allure-commandline/${ALLURE_VERSION}/allure-commandline-${ALLURE_VERSION}.tgz" \
  "https://repo1.maven.org/maven2/io/qameta/allure/allure-commandline/${ALLURE_VERSION}/allure-commandline-${ALLURE_VERSION}.tgz"; do
  rm -f "$ARCHIVE"
  if curl -fsSL --retry 2 --retry-delay 2 --retry-all-errors -o "$ARCHIVE" "$url"; then
    downloaded=true
    break
  fi
  echo "warning: failed to download Allure CLI from $url" >&2
done
if [ "$downloaded" != "true" ] || [ ! -s "$ARCHIVE" ]; then
  echo "error: failed to download Allure CLI ${ALLURE_VERSION}" >&2
  exit 1
fi
echo "${ALLURE_SHA256}  $ARCHIVE" | sha256sum --check --strict
tar -xzf "$ARCHIVE" -C build/allure-cli
build/allure-cli/allure-${ALLURE_VERSION}/bin/allure generate build/allure-results --clean -o build/allure-report
''', returnStatus: true)
                    if (reportStatus == 0) {
                        catchError(buildResult: 'FAILURE', catchInterruptions: false) {
                            archiveArtifacts artifacts: 'build/allure-report/**'
                            env.REPORT_OUTCOME = 'success'
                        }
                    } else {
                        env.REPORT_OUTCOME = 'failure'
                        echo "Allure report generation failed with exit code ${reportStatus}"
                    }
                } else {
                    echo 'Tests did not start; no test results to publish'
                }

                if (params.NOTIFY_TELEGRAM) {
                    catchError(buildResult: 'SUCCESS', stageResult: 'UNSTABLE', catchInterruptions: false, message: 'Telegram delivery not confirmed') {
                        sh '''#!/bin/sh
set -eu
if ! command -v python3 >/dev/null 2>&1; then
  [ "$(uname -s)/$(uname -m)" = Linux/x86_64 ] || { echo 'Install Python 3 on this agent'; exit 1; }
  dir=build/notification-runtime
  mkdir -p "$dir"
  archive="$dir/python.tar.gz"
  curl -fsSL --retry 2 -o "$archive" 'https://github.com/astral-sh/python-build-standalone/releases/download/20261013/cpython-3.13.16+20261013-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz'
  echo "d0080766b6b74aeb81e1949ef0d9a20e6c17f7b160fb295a69b936ccb17660be  $archive" | sha256sum --check --strict
  tar -xzf "$archive" -C "$dir"
fi
'''
                        def telegramBindings = [
                            string(credentialsId: 'telegram-bot-token', variable: 'TELEGRAM_BOT_TOKEN'),
                            string(credentialsId: 'getting-started-java-ai-telegram-chat-id', variable: 'TELEGRAM_CHAT_ID')
                        ]
                        if (env.REPORT_OUTCOME == 'success') {
                            telegramBindings << usernamePassword(credentialsId: 'getting-started-java-ai-telegram-proxy',
                                usernameVariable: 'MICROSOCKS_USER', passwordVariable: 'MICROSOCKS_PASS')
                        }
                        withCredentials(telegramBindings) {
                            sh '''#!/bin/sh
set -eu
if ! command -v python3 >/dev/null 2>&1; then
  PATH="$PWD/build/notification-runtime/python/bin:$PATH"
  export PATH
fi
if [ "$REPORT_OUTCOME" != success ] || [ ! -s build/allure-report/widgets/summary.json ]; then
  export PROJECT_NAME="$JOB_NAME" CI_NAME=Jenkins RUN_URL="$BUILD_URL"
  export BRANCH="${GIT_BRANCH:-unknown}" COMMIT_SHA="${GIT_COMMIT:-}"
  junit_dir=build/test-results/test
  if [ "${TESTS_STARTED:-}" != true ]; then
    status=BUILD_ERROR
    junit_dir=/dev/null
  elif [ "${TESTS_OUTCOME:-}" != success ]; then
    status=TESTS_FAILED
  else
    status=REPORT_ERROR
  fi
  python3 scripts/telegram_notify.py --status "$status" --junit-dir "$junit_dir" | grep -F 'Telegram notification sent (HTTP 200, ok=true)'
  exit
fi
JAR_VERSION="${ALLURE_NOTIFICATIONS_JAR_VERSION}"
JAR="allure-notifications-${JAR_VERSION}.jar"
if [ ! -f "$JAR" ]; then
  curl -fsSL --retry 2 -o "$JAR" "https://github.com/qa-guru/allure-notifications/releases/download/${JAR_VERSION}/${JAR}"
fi
echo "480408b93291a27bf1b1ae19cd3a1475437c0634d4d558154403d8bc0cb61182  $JAR" | sha256sum --check --strict
python3 - "$JAR" <<'PY'
import json, os, subprocess, sys
env = os.environ
config = {
    "base": {"project": env["JOB_NAME"], "environment": "Jenkins",
             "comment": "Build #" + env["BUILD_NUMBER"], "reportLink": env["BUILD_URL"] + "artifact/",
             "language": "en", "allureFolder": "build/allure-report", "enableChart": True},
    "telegram": {"token": env["TELEGRAM_BOT_TOKEN"], "chat": env["TELEGRAM_CHAT_ID"], "replyTo": ""},
    "proxy": {"type": "socks5", "host": "proxy.qaguru.school", "port": 7777}
}
run = subprocess.run(
    ["java", "-Djava.awt.headless=true", "-DconfigFile=/dev/stdin", "-jar", sys.argv[1]],
    input=json.dumps(config).encode(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
response = run.stdout.rpartition(b"===RESPONSE===")[2]
header, _, body = response.partition(b"BODY:")
status = header.strip().split()
if len(status) != 3 or status[:2] != [b"STATUS", b"CODE:"] or not status[2].isdigit():
    for marker, reason in [(b"SOCKS5 proxy rejected", "proxy authentication"), (b"SOCKS5 proxy requested username/password", "proxy authentication"),
                           (b"SOCKS5 proxy authentication failed", "proxy authentication"),
                           (b"SOCKS5 CONNECT failed", "proxy connection"), (b"ConnectTimeoutException", "network timeout"),
                           (b"Fontconfig", "agent fonts"), (b"UnsatisfiedLinkError", "agent native libraries"),
                           (b"UnknownHostException", "DNS"), (b"SocketTimeoutException", "network timeout"),
                           (b"ConnectException", "network connection"), (b"SSLHandshakeException", "TLS")]:
        if marker in run.stdout:
            sys.exit(f"Telegram: no HTTP response confirmed ({reason})")
    sys.exit("Telegram: no HTTP response confirmed")
code = int(status[2])
if code != 200 or run.returncode != 0:
    sys.exit(f"Telegram: notification not confirmed (HTTP {code})")
try:
    data = json.JSONDecoder().raw_decode(body.decode(errors="replace").lstrip())[0]
except ValueError:
    sys.exit("Telegram: invalid response")
message = data.get("result") if isinstance(data, dict) and data.get("ok") is True else None
if not isinstance(message, dict) or not message.get("message_id"):
    sys.exit("Telegram: no message confirmed")
print("Telegram notification sent (HTTP 200, ok=true)")
PY
'''
                        }
                    }
                } else {
                    echo 'Telegram notification disabled by NOTIFY_TELEGRAM=false'
                }

                if (env.REPORT_OUTCOME == 'failure') {
                    error('Allure report generation failed')
                }
            }
        }
    }
}
