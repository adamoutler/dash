pipeline {
    agent {
        label 'shark-wrangler'
    }

    options {
        buildDiscarder(logRotator(numToKeepStr: '10'))
    }

    stages {
        stage('Deploy') {
            environment {
                GITHUB_TOKEN = credentials('github-adamoutler-token')
                FORGEJO_TOKEN = credentials('forgejo-token-aoutler')
                JENKINS_URL = "${env.JENKINS_URL}"
                DASHBOARD_CREDS = credentials('dashboard-basic-auth')
            }
            steps {
                withCredentials([
                    string(credentialsId: 'Adam-Jenkins-Token', variable: 'JENKINS_TOKEN'),
                    usernamePassword(credentialsId: 'dashboard-basic-auth', usernameVariable: 'DASHBOARD_USER', passwordVariable: 'DASHBOARD_PASSWORD')
                ]) {
                    sh 'docker compose up -d --build'
                }
            }
        }
    }
}
