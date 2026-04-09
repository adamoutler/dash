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
                JENKINS_USER = "${JENKINS_CRED_USR}"
                JENKINS_TOKEN = "${JENKINS_CRED_PSW}"
            }
            steps {
                sh 'docker compose up -d --build'
            }
        }
    }
}
