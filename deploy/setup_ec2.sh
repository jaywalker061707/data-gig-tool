#!/bin/bash
# Run this once on a fresh EC2 Ubuntu 22.04 instance
# Usage: bash setup_ec2.sh

set -e

echo "=== GIG Tool EC2 Setup ==="

# System packages
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip python3-venv nginx nodejs npm git

# App directory
sudo mkdir -p /opt/gigtool
sudo chown $USER:$USER /opt/gigtool

# Copy app files (run from your local machine first: scp -r . ubuntu@EC2_IP:/opt/gigtool/)
cd /opt/gigtool

# Python venv
python3 -m venv venv
source venv/bin/activate
pip install flask flask-cors duckdb openpyxl pandas scipy anthropic openpyxl

# Build React frontend
cd frontend
npm install
npm run build
cd ..

# Create data directories
mkdir -p backend/data/runs

# Create systemd service
sudo tee /etc/systemd/system/gigtool.service > /dev/null << 'EOF'
[Unit]
Description=GIG Data Integrity Tool
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/opt/gigtool/backend
Environment="PATH=/opt/gigtool/venv/bin"
Environment="ANTHROPIC_API_KEY=YOUR_KEY_HERE"
ExecStart=/opt/gigtool/venv/bin/python local_server.py 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable gigtool
sudo systemctl start gigtool

# Nginx reverse proxy
sudo tee /etc/nginx/sites-available/gigtool > /dev/null << 'EOF'
server {
    listen 80;
    server_name _;

    client_max_body_size 500M;
    proxy_read_timeout 1800s;
    proxy_connect_timeout 1800s;
    proxy_send_timeout 1800s;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/gigtool /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx

echo ""
echo "=== Setup complete ==="
echo "Tool is running at http://$(curl -s ifconfig.me)"
echo ""
echo "To update the app:"
echo "  cd /opt/gigtool && git pull"
echo "  cd frontend && npm run build && cd .."
echo "  sudo systemctl restart gigtool"
