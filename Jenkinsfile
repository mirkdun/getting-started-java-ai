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
                        withCredentials([
                            string(credentialsId: 'getting-started-java-ai-telegram-bot-token', variable: 'TELEGRAM_BOT_TOKEN'),
                            string(credentialsId: 'getting-started-java-ai-telegram-chat-id', variable: 'TELEGRAM_CHAT_ID')
                        ]) {
                            sh '''#!/bin/sh
set -eu
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
python3 - <<'PY' | java -Djava.awt.headless=true -DconfigFile=/dev/stdin -jar "$JAR" >/dev/null 2>&1
import json, os
env = os.environ
print(json.dumps({
    "base": {"project": env["JOB_NAME"], "environment": "Jenkins",
             "comment": "Build #" + env["BUILD_NUMBER"], "reportLink": env["BUILD_URL"] + "artifact/",
             "language": "en", "allureFolder": "build/allure-report", "enableChart": True},
    "telegram": {"token": env["TELEGRAM_BOT_TOKEN"], "chat": env["TELEGRAM_CHAT_ID"]}
}))
PY
echo 'Allure notification command completed'
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
