#!/bin/bash

# Install tools
brew install john
cd Server
curl -L -o rockyou.txt.gz https://github.com/brannondorsey/naive-hashcat/releases/download/data/rockyou.txt.gz
gunzip rockyou.txt.gz
echo "Rockyou.txt downloaded"


# DB
cd Server
docker-compose up -d --build mongo
echo "Database in docker started"

# Backend
cd src/backend
pip install -r requirements.txt
echo "Backend ready, run :"
echo "cd src/backend && sudo python3 main.py"

# Frontend
cd frontend
npm install
echo "Frontend ready, run :"
echo "cd src/frontend && npm run start"