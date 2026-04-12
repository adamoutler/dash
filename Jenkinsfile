pipeline {
    agent {
        label 'shark-wrangler'
    }

    stages {
        stage('Deploy') {
            environment {
                FORGEJO_TOKEN = credentials('forgejo-token-aoutler')
                GITHUB_TOKEN = credentials('github-adamoutler-token')
                JENKINS_URL = "${env.JENKINS_URL}"
            }
            steps {
                withCredentials([string(credentialsId: 'Adam-Jenkins-Token', variable: 'JENKINS_TOKEN')]) {
                    sh 'docker compose up -d --build'
                }
            }
        }
    }
}
