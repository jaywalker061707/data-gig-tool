#!/bin/bash
# GIG Tool EC2 setup — run once after SSH in
set -e

echo "=== Installing system packages ==="
sudo apt-get update -y -q
sudo apt-get install -y -q python3 python3-pip python3-venv nginx nodejs npm

echo "=== Setting up app directory ==="
sudo mkdir -p /opt/gigtool
sudo chown ubuntu:ubuntu /opt/gigtool

echo "=== Python environment ==="
cd /opt/gigtool
python3 -m venv venv
source venv/bin/activate
pip install -q flask flask-cors duckdb openpyxl pandas scipy anthropic openpyxl

echo "=== Building React frontend ==="
cd /opt/gigtool/frontend
npm install --silent
VITE_API_URL="" npm run build

echo "=== Creating data directories ==="
mkdir -p /opt/gigtool/backend/data/runs

echo "=== Creating systemd service ==="
sudo tee /etc/systemd/system/gigtool.service > /dev/null << 'EOF'
[Unit]
Description=GIG Data Integrity Tool
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/opt/gigtool/backend
Environment="PATH=/opt/gigtool/venv/bin"
Environment="S3_BUCKET=gig-data-integrity-tool"
ExecStart=/opt/gigtool/venv/bin/python local_server.py 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable gigtool
sudo systemctl start gigtool

echo "=== Configuring nginx ==="
sudo tee /etc/nginx/sites-available/gigtool > /dev/null << 'EOF'
server {
    listen 80;
    server_name _;
    client_max_body_size 500M;
    proxy_read_timeout 1800s;
    proxy_connect_timeout 60s;
    proxy_send_timeout 1800s;

    # Serve React frontend
    root /opt/gigtool/frontend/dist;
    index index.html;

    # API calls go to Flask backend
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Everything else serves the React app
    location / {
        try_files $uri $uri/ /index.html;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/gigtool /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx

echo ""
echo "=== Done! Tool running at http://$(curl -s ifconfig.me) ==="
