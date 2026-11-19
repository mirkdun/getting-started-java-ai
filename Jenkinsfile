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
        string(name: 'BROWSER_SIZE', defaultValue: '1920x1080', description: 'Browser window size, WIDTHxHEIGHT')
        booleanParam(name: 'NOTIFY_TELEGRAM', defaultValue: true, description: 'Send Telegram notification after the run')
    }
    environment {
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
  echo "Unsupported browser: only the agent Chrome is used"
  exit 1
fi
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
(google-chrome --version || chromium --version || chromium-browser --version || true)
(chromedriver --version || true)
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
                sh '''#!/bin/sh
set -eu
./gradlew --no-daemon test --console=plain \
  -DbaseUrl="${BASE_URL}" \
  "-Dbrowser=${BROWSER}" \
  "-DbrowserSize=${BROWSER_SIZE}" \
  -Dheadless="${HEADLESS}"
'''
                script { env.TESTS_OUTCOME = 'success' }
            }
        }
    }
    post {
        always {
            script {
                env.REPORT_OUTCOME = 'skipped'
                if (env.COMPILE_OUTCOME == 'success') {
                    junit testResults: 'build/test-results/test/*.xml', allowEmptyResults: true
                    archiveArtifacts artifacts: 'build/allure-results/**,build/test-results/test/**,build/reports/tests/test/**', allowEmptyArchive: true, fingerprint: false

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
                        env.REPORT_OUTCOME = 'success'
                        archiveArtifacts artifacts: 'build/allure-report/**', allowEmptyArchive: false, fingerprint: false
                    } else {
                        env.REPORT_OUTCOME = 'failure'
                        echo "Allure report generation failed with exit code ${reportStatus}"
                    }
                } else {
                    echo 'Compile did not succeed; skipping result publishing'
                }

                if (params.NOTIFY_TELEGRAM) {
                    try {
                        withCredentials([
                            string(credentialsId: 'telegram-monitoring-bot-token', variable: 'TELEGRAM_BOT_TOKEN'),
                            string(credentialsId: 'telegram-allure-notifications-group-chat-id', variable: 'TELEGRAM_CHAT_ID'),
                            string(credentialsId: 'telegram-java-topic-id', variable: 'TELEGRAM_TOPIC_ID')
                        ]) {
                            sh '''#!/bin/sh
set -eu
if [ ! -f build/allure-report/widgets/summary.json ]; then
  echo 'No Allure summary; Telegram notification skipped'
  exit 0
fi
mkdir -p notifications
cat > notifications/config.json <<'EOF'
{
  "base": {
    "project": "${JOB_BASE_NAME}",
    "environment": "jenkins",
    "comment": "Jenkins pipeline",
    "reportLink": "${BUILD_URL}artifact/build/allure-report/index.html",
    "language": "en",
    "allureFolder": "build/allure-report",
    "enableChart": true
  },
  "telegram": {
    "token": "${TELEGRAM_BOT_TOKEN}",
    "chat": "${TELEGRAM_CHAT_ID}",
    "topic": "${TELEGRAM_TOPIC_ID}",
    "replyTo": ""
  },
  "proxy": {
    "type": "socks5",
    "host": "proxy.qaguru.school",
    "port": 7777
  }
}
EOF
JAR_VERSION="${ALLURE_NOTIFICATIONS_JAR_VERSION}"
JAR="allure-notifications-${JAR_VERSION}.jar"
if [ ! -f "$JAR" ]; then
  curl -fsSL --retry 2 --retry-delay 2 --retry-all-errors -o "$JAR" \
    "https://github.com/qa-guru/allure-notifications/releases/download/${JAR_VERSION}/${JAR}" \
    || curl -fsSL --retry 2 --retry-delay 2 --retry-all-errors -o "$JAR" \
    "https://github.com/qa-guru/allure-notifications/releases/download/v${JAR_VERSION}/${JAR}"
fi
java -DconfigFile=notifications/config.json -jar "$JAR"
'''
                        }
                    } catch (err) {
                        echo "Telegram notification failed: ${err}"
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
