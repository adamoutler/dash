pipeline {
    agent {
        label 'shark-wrangler'
    }

    options {
        buildDiscarder(logRotator(numToKeepStr: '10'))
        buildName "${env.JOB_NAME}#${env.BUILD_NUMBER}"
    }

    stages {
        stage('Deploy') {
            environment {
                GITHUB_TOKEN = credentials('github-adamoutler-token')
                FORGEJO_TOKEN = credentials('forgejo-token-aoutler')
                JENKINS_URL = "${env.JENKINS_URL}"
                DASHBOARD_CREDS = credentials('dashboard-basic-auth')
                DASHBOARD_USER = "${env.DASHBOARD_CREDS_USR}"
                DASHBOARD_PASSWORD = "${env.DASHBOARD_CREDS_PSW}"
            }
            steps {
                withCredentials([string(credentialsId: 'Adam-Jenkins-Token', variable: 'JENKINS_TOKEN')]) {
                    sh 'docker compose up -d --build'
                }
            }
        }
    }
}
