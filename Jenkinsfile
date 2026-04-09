pipeline {
    agent {
        label 'shark-wrangler'
    }

    stages {
        stage('Deploy') {
            environment {
                FORGEJO_TOKEN = credentials('forgejo-token-aoutler')
                GITHUB_TOKEN = credentials('github-adamoutler-token')
                JENKINS_CRED = credentials('Adam-Jenkins-Token')
            }
            steps {
                sh 'docker compose up -d --build'
            }
        }
    }
}
