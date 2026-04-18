#!/bin/bash
# Radar 1.0 - Production Deployment Script

echo "🚀 Starting Radar deployment..."

# 1. Pull latest code
echo "📥 Pulling latest changes from Git..."
git pull origin main

# 2. Rebuild and restart containers
echo "🏗️ Rebuilding Docker containers..."
docker-compose up -d --build radar-app

# 3. Clean up unused images (optional)
echo "🧹 Cleaning up old Docker images..."
docker image prune -f

echo "✅ Radar is now up and running on port 8005!"
echo "📍 Access: https://daisoftwares.com/solutions/radar/login"
