#!/bin/bash
# Deploy latest code to EC2
# Usage: bash deploy.sh ubuntu@YOUR_EC2_IP

EC2=$1
if [ -z "$EC2" ]; then
  echo "Usage: bash deploy.sh ubuntu@EC2_IP"
  exit 1
fi

echo "Deploying to $EC2..."

# Sync files (exclude node_modules, __pycache__, data/runs)
rsync -avz --exclude 'node_modules' --exclude '__pycache__' \
  --exclude 'backend/data/runs' --exclude '*.pyc' \
  --exclude '.git' \
  . $EC2:/opt/gigtool/

# Build frontend and restart on server
ssh $EC2 << 'REMOTE'
  cd /opt/gigtool/frontend
  npm install --silent
  npm run build
  sudo systemctl restart gigtool
  echo "Deploy complete. Service restarted."
REMOTE

echo "Done. Tool available at http://$(ssh $EC2 curl -s ifconfig.me 2>/dev/null)"
