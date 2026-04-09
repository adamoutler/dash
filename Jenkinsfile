pipeline {
    agent {
        label 'shark-wrangler'
    }

    stages {
        stage('Deploy') {
            environment {
                FORGEJO_TOKEN = credentials('forgejo-token-aoutler')
                GITHUB_TOKEN = credentials('github-adamoutler-token')
            }
            steps {
                withCredentials([usernamePassword(credentialsId: 'Adam-Jenkins-Token', passwordVariable: 'JENKINS_TOKEN', usernameVariable: 'JENKINS_USER')]) {
                    sh 'docker compose up -d --build'
                }
            }
        }
    }
}
